from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import DataTable, Header, Input, Label, Select, Static, Tree
from textual.widgets.tree import TreeNode

from workbench.state import (
    add_repo,
    add_worktree_to_project,
    archive_project,
    create_project,
    delete_project,
    find_project_for_worktree,
    load_archived_projects,
    load_projects,
    load_repos,
    remove_worktree_from_project,
    unarchive_project,
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

# Column widths for consistent alignment in tree labels
COL_BRANCH = 24
COL_REPO = 16
COL_STATUS = 10
COL_CLAUDE = 10
COL_PR = 8
COL_COMMIT = 14


@dataclass
class WorktreeNodeData:
    """Data attached to a worktree tree node."""
    worktree: WorktreeInfo
    project_name: str | None = None


@dataclass
class ProjectNodeData:
    """Data attached to a project tree node."""
    project_name: str | None  # None = No Project


def _format_worktree_label(
    wt: WorktreeInfo,
    pr_cache: dict[str, PR],
) -> Text:
    git_status = get_git_status(wt.path)
    claude_active = ai_agent.is_active(wt.path)
    pr = pr_cache.get(wt.branch)
    pr_col = f"#{pr.number}" if pr else "—"
    last_commit = get_last_commit_time(wt.path)
    repo_name = get_repo_name(wt.repo)

    label = Text()
    label.append(f"{wt.branch:<{COL_BRANCH}}", style="bold")
    label.append(f"{repo_name:<{COL_REPO}}", style="dim")
    label.append(f"{git_status:<{COL_STATUS}}")
    if claude_active:
        label.append(f"{'● active':<{COL_CLAUDE}}", style="green")
    else:
        label.append(f"{'○ idle':<{COL_CLAUDE}}", style="dim")
    label.append(f"{pr_col:<{COL_PR}}", style="cyan" if pr else "dim")
    label.append(last_commit, style="dim")
    return label


def _format_header_label() -> Text:
    """Column header for reference."""
    label = Text()
    label.append(f"{'Branch':<{COL_BRANCH}}", style="bold dim")
    label.append(f"{'Repo':<{COL_REPO}}", style="bold dim")
    label.append(f"{'Status':<{COL_STATUS}}", style="bold dim")
    label.append(f"{'Claude':<{COL_CLAUDE}}", style="bold dim")
    label.append(f"{'PR':<{COL_PR}}", style="bold dim")
    label.append("Last Commit", style="bold dim")
    return label


class WrappingFooter(Static):
    """A footer that wraps keybindings onto multiple lines."""

    DEFAULT_CSS = """
    WrappingFooter {
        dock: bottom;
        background: $surface;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            active = self.app.active_bindings
        except Exception:
            return

        entries: list[tuple[str, str, bool]] = []
        seen: set[str] = set()
        for key, active_binding in active.items():
            binding = active_binding.binding
            if not binding.show:
                continue
            if binding.description in seen:
                continue
            seen.add(binding.description)
            entries.append((binding.key, binding.description, active_binding.enabled))

        width = self.size.width or 80
        gap = 2
        lines: list[Text] = []
        current = Text()
        col = 0

        for key, desc, enabled in entries:
            hint_len = len(key) + 1 + len(desc)  # "k desc"
            needed = (gap if col > 0 else 0) + hint_len

            if col > 0 and col + needed > width:
                lines.append(current)
                current = Text()
                col = 0

            if col > 0:
                current.append("  ")
                col += gap

            if enabled:
                current.append(key, style="bold cyan")
                current.append(f" {desc}")
            else:
                current.append(key, style="dim")
                current.append(f" {desc}", style="dim")
            col += hint_len

        if current.plain:
            lines.append(current)

        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append("\n")
            result.append_text(line)

        self.update(result)


class MainScreen(Screen):
    BINDINGS = [
        Binding("enter", "drill_down", "Sessions"),
        Binding("tab", "drill_down", "Sessions", show=False),
        Binding("c", "open_claude", "Claude"),
        Binding("i", "open_ide", "IDE"),
        Binding("g", "open_git", "Git"),
        Binding("p", "open_pr", "PR"),
        Binding("x", "close_worktree", "Close WT"),
        Binding("n", "new_worktree", "New WT"),
        Binding("P", "new_project", "New Project"),
        Binding("X", "delete_project", "Del Project"),
        Binding("A", "archive_project", "Archive"),
        Binding("a", "assign_to_project", "Assign"),
        Binding("d", "view_archived", "Archived"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
        # Emacs navigation
        Binding("ctrl+n", "cursor_down", "Down", show=False),
        Binding("ctrl+p", "cursor_up", "Up", show=False),
        Binding("ctrl+f", "cursor_expand", "Expand", show=False),
        Binding("ctrl+b", "cursor_collapse", "Collapse", show=False),
    ]

    pr_cache: dict[str, PR] = {}

    def _on_tree_cursor_changed(self) -> None:
        """Re-evaluate binding states when cursor moves."""
        self.refresh_bindings()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self._on_tree_cursor_changed()
        try:
            self.query_one(WrappingFooter)._rebuild()
        except Exception:
            pass

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable worktree-only actions when a project node is selected."""
        worktree_actions = {
            "open_claude", "open_ide", "open_git", "open_pr",
            "close_worktree", "assign_to_project",
        }
        project_actions = {"delete_project", "archive_project"}

        if action in worktree_actions:
            return self._selected_worktree_data() is not None
        if action in project_actions:
            proj = self._selected_project_data()
            return proj is not None and proj.project_name is not None
        return True

    def compose(self) -> ComposeResult:
        yield Static(_format_header_label(), id="col-header")
        tree: Tree[WorktreeNodeData | ProjectNodeData] = Tree("workbench", id="main-tree")
        tree.show_root = False
        tree.guide_depth = 3
        yield tree
        yield Static("", id="status-bar")
        yield WrappingFooter()

    def on_mount(self) -> None:
        self.load_data()
        self.set_interval(5, self.load_data)

    def on_screen_resume(self) -> None:
        self.load_data()
        try:
            self.query_one(WrappingFooter)._rebuild()
        except Exception:
            pass

    @work(thread=True)
    def load_data(self) -> None:
        repos = load_repos()
        all_worktrees = list_all_worktrees(repos)
        projects = load_projects()

        try:
            self.pr_cache = pr_viewer.list_prs()
        except Exception:
            self.pr_cache = {}

        self.app.call_from_thread(self._rebuild_tree, all_worktrees, projects)

    def _rebuild_tree(self, all_worktrees: list[WorktreeInfo], projects: list) -> None:
        tree = self.query_one("#main-tree", Tree)

        # Remember which projects were expanded
        expanded: set[str | None] = set()
        for node in tree.root.children:
            if node.is_expanded and hasattr(node, "data") and isinstance(node.data, ProjectNodeData):
                expanded.add(node.data.project_name)

        tree.root.remove_children()

        assigned_paths: set[str] = set()

        for project in projects:
            wt_count = len(project.worktrees)
            project_label = Text(f"{project.name} ({wt_count} worktree{'s' if wt_count != 1 else ''})", style="bold")
            project_node = tree.root.add(
                project_label,
                data=ProjectNodeData(project_name=project.name),
            )

            for pw in project.worktrees:
                assigned_paths.add(pw.worktree_path)
                matching = [wt for wt in all_worktrees if str(wt.path) == pw.worktree_path]
                if matching:
                    wt = matching[0]
                    label = _format_worktree_label(wt, self.pr_cache)
                    project_node.add_leaf(
                        label,
                        data=WorktreeNodeData(worktree=wt, project_name=project.name),
                    )

            # Restore expand state, default to expanded
            if project.name in expanded or project.name not in expanded and not expanded:
                project_node.expand()
            else:
                project_node.collapse()

        # No Project worktrees
        unassigned = [wt for wt in all_worktrees if str(wt.path) not in assigned_paths]
        if unassigned:
            wt_count = len(unassigned)
            unassigned_label = Text(f"No Project ({wt_count} worktree{'s' if wt_count != 1 else ''})", style="bold italic")
            unassigned_node = tree.root.add(
                unassigned_label,
                data=ProjectNodeData(project_name=None),
            )
            for wt in unassigned:
                label = _format_worktree_label(wt, self.pr_cache)
                unassigned_node.add_leaf(
                    label,
                    data=WorktreeNodeData(worktree=wt, project_name=None),
                )

            if None in expanded or not expanded:
                unassigned_node.expand()
            else:
                unassigned_node.collapse()

        # Move cursor to first worktree node if nothing selected
        if tree.cursor_node is None or tree.cursor_node is tree.root:
            for node in tree.root.children:
                if node.children:
                    tree.select_node(node.children[0])
                    break
                else:
                    tree.select_node(node)
                    break

        # Update status bar
        status = self.query_one("#status-bar", Static)
        status.update(f" {len(projects)} projects · {len(all_worktrees)} worktrees")

    def _selected_node(self) -> TreeNode | None:
        tree = self.query_one("#main-tree", Tree)
        return tree.cursor_node

    def _selected_worktree_data(self) -> WorktreeNodeData | None:
        node = self._selected_node()
        if node and isinstance(node.data, WorktreeNodeData):
            return node.data
        return None

    def _selected_project_data(self) -> ProjectNodeData | None:
        node = self._selected_node()
        if node and isinstance(node.data, ProjectNodeData):
            return node.data
        return None

    def action_drill_down(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            self.app.push_screen(SessionListScreen(wt_data.worktree))
            return
        # If on a project node, toggle expand/collapse
        node = self._selected_node()
        if node and isinstance(node.data, ProjectNodeData):
            node.toggle()

    def action_open_claude(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            ai_agent.open(wt_data.worktree.path)
            self.notify(f"Opened Claude Code in {wt_data.worktree.branch}")

    def action_open_ide(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            ide.open(wt_data.worktree.path)
            self.notify(f"Opened IDE in {wt_data.worktree.branch}")

    def action_open_git(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            vcs_client.open(wt_data.worktree.path)
            self.notify(f"Opened git client in {wt_data.worktree.branch}")

    def action_open_pr(self) -> None:
        wt_data = self._selected_worktree_data()
        if not wt_data:
            return
        wt = wt_data.worktree
        pr = self.pr_cache.get(wt.branch)
        if pr:
            pr_viewer.open_in_browser(wt.branch)
            self.notify(f"Opened PR #{pr.number} in browser")
        else:
            self.app.push_screen(CreatePRScreen(wt))

    def action_close_worktree(self) -> None:
        wt_data = self._selected_worktree_data()
        if not wt_data:
            return
        wt = wt_data.worktree
        try:
            if wt_data.project_name:
                remove_worktree_from_project(wt_data.project_name, str(wt.path))
            remove_worktree(wt.path)
            self.notify(f"Removed worktree {wt.branch}")
            self.load_data()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

    def action_new_worktree(self) -> None:
        # If cursor is on a project, pre-select that project
        project_name = None
        wt_data = self._selected_worktree_data()
        proj_data = self._selected_project_data()
        if wt_data:
            project_name = wt_data.project_name
        elif proj_data:
            project_name = proj_data.project_name
        self.app.push_screen(NewWorktreeScreen(project_name=project_name))

    def action_new_project(self) -> None:
        self.app.push_screen(NewProjectScreen())

    def action_delete_project(self) -> None:
        proj_data = self._selected_project_data()
        if proj_data and proj_data.project_name:
            delete_project(proj_data.project_name)
            self.notify(f"Deleted project {proj_data.project_name}")
            self.load_data()

    def action_archive_project(self) -> None:
        proj_data = self._selected_project_data()
        if proj_data and proj_data.project_name:
            archive_project(proj_data.project_name)
            self.notify(f"Archived project {proj_data.project_name}")
            self.load_data()

    def action_view_archived(self) -> None:
        self.app.push_screen(ArchivedProjectsScreen())

    def action_assign_to_project(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            self.app.push_screen(AssignToProjectScreen(wt_data.worktree))

    def action_cursor_down(self) -> None:
        tree = self.query_one("#main-tree", Tree)
        tree.action_cursor_down()

    def action_cursor_up(self) -> None:
        tree = self.query_one("#main-tree", Tree)
        tree.action_cursor_up()

    def action_cursor_expand(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, ProjectNodeData):
            node.expand()

    def action_cursor_collapse(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, ProjectNodeData):
            node.collapse()

    def action_refresh(self) -> None:
        self.load_data()

    def action_quit(self) -> None:
        self.app.exit()


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
        yield WrappingFooter()

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Session", "Status", "Last Active")
        try:
            self.query_one(WrappingFooter)._rebuild()
        except Exception:
            pass

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

        projects = load_projects()
        project_options: list[tuple[str, str]] = [("(no project)", "__none__")]
        project_options.extend((p.name, p.name) for p in projects)
        default_project = self.project_name if self.project_name else "__none__"

        yield Vertical(
            Label("New worktree"),
            Label("Project:"),
            Select(project_options, id="project-select", value=default_project),
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

        project_select = self.query_one("#project-select", Select)
        project_name = None
        if project_select.value not in (Select.BLANK, "__none__"):
            project_name = str(project_select.value)

        repo_path = Path(str(select.value))
        try:
            wt = create_worktree(repo_path, branch)
            if project_name:
                add_worktree_to_project(project_name, str(repo_path), branch, str(wt.path))
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


class ArchivedProjectsScreen(Screen):
    BINDINGS = [
        Binding("u", "unarchive", "Unarchive"),
        Binding("X", "delete_project", "Delete"),
        Binding("escape", "go_back", "Back"),
        Binding("backspace", "go_back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(" Archived Projects", id="archived-header")
        yield DataTable(id="archived-table")
        yield WrappingFooter()

    def on_mount(self) -> None:
        table = self.query_one("#archived-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Project", "Worktrees")
        self._load()
        self._refresh_footer()

    def on_screen_resume(self) -> None:
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        try:
            self.query_one(WrappingFooter)._rebuild()
        except Exception:
            pass

    def _load(self) -> None:
        table = self.query_one("#archived-table", DataTable)
        table.clear()
        self.archived = load_archived_projects()
        for p in self.archived:
            table.add_row(p.name, str(len(p.worktrees)))
        if not self.archived:
            self.notify("No archived projects")

    def _selected_project(self) -> str | None:
        table = self.query_one("#archived-table", DataTable)
        if not self.archived:
            return None
        row = table.cursor_row
        if 0 <= row < len(self.archived):
            return self.archived[row].name
        return None

    def action_unarchive(self) -> None:
        name = self._selected_project()
        if name:
            unarchive_project(name)
            self.notify(f"Restored project {name}")
            self._load()

    def action_delete_project(self) -> None:
        name = self._selected_project()
        if name:
            delete_project(name)
            self.notify(f"Deleted project {name}")
            self._load()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class WorkbenchApp(App):
    COMMANDS = set()
    ENABLE_COMMAND_PALETTE = False
    TITLE = "workbench"
    CSS = """
    #main-tree {
        height: 1fr;
    }
    #col-header {
        height: 1;
        padding: 0 0 0 7;
        background: $surface;
        color: $text-muted;
    }
    #session-table {
        height: 1fr;
    }
    #session-header {
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
    #archived-header {
        padding: 1;
        text-style: bold;
    }
    ToastRack {
        margin-bottom: 3;
    }
    """

    def on_mount(self) -> None:
        try:
            from workbench.worktree import get_repo_root
            repo = get_repo_root()
            add_repo(str(repo))
        except RuntimeError:
            pass
        self.push_screen(MainScreen())
