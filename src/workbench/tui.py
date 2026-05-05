from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Select, Static

from workbench.state import (
    Project,
    add_repo,
    add_worktree_to_project,
    create_project,
    delete_project,
    find_project_for_worktree,
    load_projects,
    load_repos,
    remove_worktree_from_project,
)
from workbench.status import get_git_status, get_last_commit_time
from workbench.tools.ai_agent import ClaudeCodeAgent
from workbench.tools.base import PR
from workbench.tools.ide import IntelliJIDE
from workbench.tools.pr_viewer import GitHubCLIPR
from workbench.tools.vcs_client import EmacsMagit
from workbench.worktree import (
    WorktreeInfo,
    create_worktree,
    get_repo_name,
    list_all_worktrees,
    remove_worktree,
)

# Tool instances (swap these for different implementations)
ai_agent = ClaudeCodeAgent()
ide = IntelliJIDE()
vcs_client = EmacsMagit()
pr_viewer = GitHubCLIPR()


@dataclass
class RowItem:
    """Represents a row in the main table — either a project header or a worktree."""
    is_project: bool
    project_name: str | None = None
    worktree: WorktreeInfo | None = None


class MainScreen(Screen):
    """Top-level view: projects (expandable) + unassigned worktrees."""

    BINDINGS = [
        Binding("enter", "drill_down", "Open"),
        Binding("c", "open_claude", "Claude"),
        Binding("i", "open_ide", "IDE"),
        Binding("g", "open_git", "Git"),
        Binding("p", "open_pr", "PR"),
        Binding("x", "close_worktree", "Close WT"),
        Binding("n", "new_worktree", "New WT"),
        Binding("P", "new_project", "New Project"),
        Binding("X", "delete_project", "Del Project"),
        Binding("a", "assign_to_project", "Assign"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    rows: list[RowItem] = []
    pr_cache: dict[str, PR] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="main-table")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#main-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("", "Branch", "Repo", "Status", "Claude", "PR", "Last Commit")
        self.load_data()
        self.set_interval(5, self.load_data)

    @work(thread=True)
    def load_data(self) -> None:
        repos = load_repos()
        all_worktrees = list_all_worktrees(repos)
        projects = load_projects()

        try:
            self.pr_cache = pr_viewer.list_prs()
        except Exception:
            self.pr_cache = {}

        # Build row list
        rows: list[RowItem] = []

        # Projects with their worktrees
        assigned_paths: set[str] = set()
        for project in projects:
            rows.append(RowItem(is_project=True, project_name=project.name))
            for pw in project.worktrees:
                assigned_paths.add(pw.worktree_path)
                # Find matching WorktreeInfo
                matching = [wt for wt in all_worktrees if str(wt.path) == pw.worktree_path]
                if matching:
                    rows.append(RowItem(is_project=False, project_name=project.name, worktree=matching[0]))

        # Unassigned worktrees
        unassigned = [wt for wt in all_worktrees if str(wt.path) not in assigned_paths]
        if unassigned:
            rows.append(RowItem(is_project=True, project_name=None))  # "Unassigned" header
            for wt in unassigned:
                rows.append(RowItem(is_project=False, project_name=None, worktree=wt))

        self.rows = rows
        self.app.call_from_thread(self._update_table)

    def _update_table(self) -> None:
        table = self.query_one("#main-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()

        for row in self.rows:
            if row.is_project:
                name = row.project_name or "Unassigned"
                wt_count = sum(
                    1 for r in self.rows
                    if not r.is_project and r.project_name == row.project_name
                )
                table.add_row(
                    "▼", f"[bold]{name}[/bold]", "", "", "", "", f"{wt_count} worktrees",
                )
            else:
                wt = row.worktree
                if not wt:
                    continue
                git_status = get_git_status(wt.path)
                claude_active = ai_agent.is_active(wt.path)
                claude_col = "● active" if claude_active else "○ idle"
                pr = self.pr_cache.get(wt.branch)
                pr_col = f"#{pr.number}" if pr else "—"
                last_commit = get_last_commit_time(wt.path)
                repo_name = get_repo_name(wt.repo)
                table.add_row("  ", wt.branch, repo_name, git_status, claude_col, pr_col, last_commit)

        if self.rows and cursor_row < len(self.rows):
            table.move_cursor(row=cursor_row)

        projects = load_projects()
        status = self.query_one("#status-bar", Static)
        total_wts = sum(1 for r in self.rows if not r.is_project)
        status.update(f" {len(projects)} projects · {total_wts} worktrees")

    def _selected_row(self) -> RowItem | None:
        table = self.query_one("#main-table", DataTable)
        if not self.rows:
            return None
        row = table.cursor_row
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None

    def _selected_worktree(self) -> WorktreeInfo | None:
        row = self._selected_row()
        if row and not row.is_project:
            return row.worktree
        return None

    def action_drill_down(self) -> None:
        row = self._selected_row()
        if not row:
            return
        if row.is_project and row.project_name:
            self.app.push_screen(ProjectWorktreeScreen(row.project_name))
        elif row.worktree:
            self.app.push_screen(SessionListScreen(row.worktree))

    def action_open_claude(self) -> None:
        wt = self._selected_worktree()
        if wt:
            ai_agent.open(wt.path)
            self.notify(f"Opened Claude Code in {wt.branch}")

    def action_open_ide(self) -> None:
        wt = self._selected_worktree()
        if wt:
            ide.open(wt.path)
            self.notify(f"Opened IDE in {wt.branch}")

    def action_open_git(self) -> None:
        wt = self._selected_worktree()
        if wt:
            vcs_client.open(wt.path)
            self.notify(f"Opened git client in {wt.branch}")

    def action_open_pr(self) -> None:
        wt = self._selected_worktree()
        if not wt:
            return
        pr = self.pr_cache.get(wt.branch)
        if pr:
            pr_viewer.open_in_browser(wt.branch)
            self.notify(f"Opened PR #{pr.number} in browser")
        else:
            self.app.push_screen(CreatePRScreen(wt))

    def action_close_worktree(self) -> None:
        wt = self._selected_worktree()
        if not wt:
            return
        row = self._selected_row()
        try:
            # Remove from project if assigned
            if row and row.project_name:
                remove_worktree_from_project(row.project_name, str(wt.path))
            remove_worktree(wt.path)
            self.notify(f"Removed worktree {wt.branch}")
            self.load_data()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

    def action_new_worktree(self) -> None:
        self.app.push_screen(NewWorktreeScreen())

    def action_new_project(self) -> None:
        self.app.push_screen(NewProjectScreen())

    def action_delete_project(self) -> None:
        row = self._selected_row()
        if row and row.is_project and row.project_name:
            delete_project(row.project_name)
            self.notify(f"Deleted project {row.project_name}")
            self.load_data()

    def action_assign_to_project(self) -> None:
        wt = self._selected_worktree()
        if wt:
            self.app.push_screen(AssignToProjectScreen(wt))

    def action_refresh(self) -> None:
        self.load_data()

    def action_quit(self) -> None:
        self.app.exit()


class ProjectWorktreeScreen(Screen):
    """Drill-down into a project: shows its worktrees with full actions."""

    BINDINGS = [
        Binding("enter", "view_sessions", "Sessions"),
        Binding("c", "open_claude", "Claude"),
        Binding("i", "open_ide", "IDE"),
        Binding("g", "open_git", "Git"),
        Binding("p", "open_pr", "PR"),
        Binding("n", "new_worktree", "New WT"),
        Binding("x", "close_worktree", "Close WT"),
        Binding("escape", "go_back", "Back"),
        Binding("backspace", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, project_name: str) -> None:
        super().__init__()
        self.project_name = project_name
        self.worktrees: list[WorktreeInfo] = []
        self.pr_cache: dict[str, PR] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(f" Project: {self.project_name}", id="project-header")
        yield DataTable(id="project-wt-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#project-wt-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Branch", "Repo", "Status", "Claude", "PR", "Last Commit")
        self.load_data()
        self.set_interval(5, self.load_data)

    @work(thread=True)
    def load_data(self) -> None:
        repos = load_repos()
        all_worktrees = list_all_worktrees(repos)
        project = None
        for p in load_projects():
            if p.name == self.project_name:
                project = p
                break

        if not project:
            self.worktrees = []
        else:
            wt_paths = {pw.worktree_path for pw in project.worktrees}
            self.worktrees = [wt for wt in all_worktrees if str(wt.path) in wt_paths]

        try:
            self.pr_cache = pr_viewer.list_prs()
        except Exception:
            self.pr_cache = {}

        self.app.call_from_thread(self._update_table)

    def _update_table(self) -> None:
        table = self.query_one("#project-wt-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()

        for wt in self.worktrees:
            git_status = get_git_status(wt.path)
            claude_active = ai_agent.is_active(wt.path)
            claude_col = "● active" if claude_active else "○ idle"
            pr = self.pr_cache.get(wt.branch)
            pr_col = f"#{pr.number}" if pr else "—"
            last_commit = get_last_commit_time(wt.path)
            repo_name = get_repo_name(wt.repo)
            table.add_row(wt.branch, repo_name, git_status, claude_col, pr_col, last_commit)

        if self.worktrees and cursor_row < len(self.worktrees):
            table.move_cursor(row=cursor_row)

    def _selected_worktree(self) -> WorktreeInfo | None:
        table = self.query_one("#project-wt-table", DataTable)
        if not self.worktrees:
            return None
        row = table.cursor_row
        if 0 <= row < len(self.worktrees):
            return self.worktrees[row]
        return None

    def action_view_sessions(self) -> None:
        wt = self._selected_worktree()
        if wt:
            self.app.push_screen(SessionListScreen(wt))

    def action_open_claude(self) -> None:
        wt = self._selected_worktree()
        if wt:
            ai_agent.open(wt.path)
            self.notify(f"Opened Claude Code in {wt.branch}")

    def action_open_ide(self) -> None:
        wt = self._selected_worktree()
        if wt:
            ide.open(wt.path)
            self.notify(f"Opened IDE in {wt.branch}")

    def action_open_git(self) -> None:
        wt = self._selected_worktree()
        if wt:
            vcs_client.open(wt.path)
            self.notify(f"Opened git client in {wt.branch}")

    def action_open_pr(self) -> None:
        wt = self._selected_worktree()
        if not wt:
            return
        pr = self.pr_cache.get(wt.branch)
        if pr:
            pr_viewer.open_in_browser(wt.branch)
            self.notify(f"Opened PR #{pr.number} in browser")
        else:
            self.app.push_screen(CreatePRScreen(wt))

    def action_new_worktree(self) -> None:
        self.app.push_screen(NewWorktreeScreen(project_name=self.project_name))

    def action_close_worktree(self) -> None:
        wt = self._selected_worktree()
        if not wt:
            return
        try:
            remove_worktree_from_project(self.project_name, str(wt.path))
            remove_worktree(wt.path)
            self.notify(f"Removed worktree {wt.branch}")
            self.load_data()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

    def action_refresh(self) -> None:
        self.load_data()

    def action_go_back(self) -> None:
        self.app.pop_screen()


class SessionListScreen(Screen):
    BINDINGS = [
        Binding("r", "resume_session", "Resume"),
        Binding("f", "fork_session", "Fork"),
        Binding("c", "new_session", "New"),
        Binding("escape", "go_back", "Back"),
        Binding("backspace", "go_back", "Back"),
    ]

    def __init__(self, worktree: WorktreeInfo) -> None:
        super().__init__()
        self.worktree = worktree
        self.sessions = ai_agent.list_sessions(worktree.path)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(f" Sessions for {self.worktree.branch}", id="session-header")
        yield DataTable(id="session-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Session", "Status", "Last Active")

        for s in self.sessions:
            status = "● active" if s.is_active else "○ idle"
            table.add_row(s.label, status, s.last_active)

        if not self.sessions:
            self.notify("No sessions found for this worktree")

    def _selected_session_id(self) -> str | None:
        table = self.query_one("#session-table", DataTable)
        if not self.sessions:
            return None
        row = table.cursor_row
        if 0 <= row < len(self.sessions):
            return self.sessions[row].session_id
        return None

    def action_resume_session(self) -> None:
        sid = self._selected_session_id()
        if sid:
            ai_agent.resume(self.worktree.path, sid)
            self.notify(f"Resumed session {sid[:20]}...")

    def action_fork_session(self) -> None:
        sid = self._selected_session_id()
        if sid:
            ai_agent.resume(self.worktree.path, sid)
            self.notify(f"Forked session {sid[:20]}... (diverge from here)")

    def action_new_session(self) -> None:
        ai_agent.open(self.worktree.path)
        self.notify(f"Started new Claude session in {self.worktree.branch}")

    def action_go_back(self) -> None:
        self.app.pop_screen()


class NewWorktreeScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, project_name: str | None = None) -> None:
        super().__init__()
        self.project_name = project_name

    def compose(self) -> ComposeResult:
        repos = load_repos()
        repo_options = [(Path(r).name, r) for r in repos]

        yield Vertical(
            Label("New worktree"),
            Label("Repo:"),
            Select(repo_options, id="repo-select", prompt="Select a repo"),
            Label("Branch name:"),
            Input(id="branch-input", placeholder="feature/my-branch"),
            id="new-wt-form",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        branch = event.value.strip()
        if not branch:
            self.notify("Branch name cannot be empty", severity="error")
            return

        select = self.query_one("#repo-select", Select)
        if select.value is Select.BLANK:
            self.notify("Select a repo first", severity="error")
            return

        repo_path = Path(str(select.value))
        try:
            wt = create_worktree(repo_path, branch)
            if self.project_name:
                add_worktree_to_project(self.project_name, str(repo_path), branch, str(wt.path))
            self.notify(f"Created worktree for {branch}")
            self.app.pop_screen()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

    def action_cancel(self) -> None:
        self.app.pop_screen()


class NewProjectScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("New project — enter name:"),
            Input(id="project-name-input", placeholder="payments-redesign"),
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not name:
            self.notify("Project name cannot be empty", severity="error")
            return
        try:
            create_project(name)
            self.notify(f"Created project '{name}'")
            self.app.pop_screen()
        except ValueError as e:
            self.notify(str(e), severity="error")

    def action_cancel(self) -> None:
        self.app.pop_screen()


class AssignToProjectScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, worktree: WorktreeInfo) -> None:
        super().__init__()
        self.worktree = worktree

    def compose(self) -> ComposeResult:
        projects = load_projects()
        options = [(p.name, p.name) for p in projects]

        yield Vertical(
            Label(f"Assign {self.worktree.branch} to project:"),
            Select(options, id="project-select", prompt="Select a project"),
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            project_name = str(event.value)
            # Remove from current project if assigned
            current = find_project_for_worktree(str(self.worktree.path))
            if current:
                remove_worktree_from_project(current, str(self.worktree.path))
            add_worktree_to_project(
                project_name,
                str(self.worktree.repo),
                self.worktree.branch,
                str(self.worktree.path),
            )
            self.notify(f"Assigned {self.worktree.branch} to {project_name}")
            self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.pop_screen()


class CreatePRScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, worktree: WorktreeInfo) -> None:
        super().__init__()
        self.worktree = worktree

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"Create PR for {self.worktree.branch} — enter base branch:"),
            Input(id="base-input", placeholder="main", value="main"),
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        base = event.value.strip() or "main"
        try:
            pr = pr_viewer.create_pr(self.worktree.branch, base)
            self.notify(f"Created PR #{pr.number}")
            self.app.pop_screen()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

    def action_cancel(self) -> None:
        self.app.pop_screen()


class WorkbenchApp(App):
    TITLE = "workbench"
    CSS = """
    #main-table {
        height: 1fr;
    }
    #project-wt-table {
        height: 1fr;
    }
    #session-table {
        height: 1fr;
    }
    #session-header, #project-header {
        padding: 1;
        text-style: bold;
    }
    #status-bar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #new-wt-form {
        padding: 1 2;
    }
    """

    def on_mount(self) -> None:
        # Auto-register current repo if we're in one
        try:
            from workbench.worktree import get_repo_root
            repo = get_repo_root()
            add_repo(str(repo))
        except RuntimeError:
            pass
        self.push_screen(MainScreen())
