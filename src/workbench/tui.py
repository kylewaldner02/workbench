from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from workbench.status import get_git_status, get_last_commit_time
from workbench.tools.ai_agent import ClaudeCodeAgent
from workbench.tools.base import PR
from workbench.tools.ide import IntelliJIDE
from workbench.tools.pr_viewer import GitHubCLIPR
from workbench.tools.vcs_client import EmacsMagit
from workbench.worktree import (
    WorktreeInfo,
    create_worktree,
    list_worktrees,
    remove_worktree,
)

# Tool instances (swap these for different implementations)
ai_agent = ClaudeCodeAgent()
ide = IntelliJIDE()
vcs_client = EmacsMagit()
pr_viewer = GitHubCLIPR()


class WorktreeListScreen(Screen):
    BINDINGS = [
        Binding("c", "open_claude", "Claude"),
        Binding("i", "open_ide", "IDE"),
        Binding("g", "open_git", "Git"),
        Binding("p", "open_pr", "PR"),
        Binding("x", "close_worktree", "Close"),
        Binding("n", "new_worktree", "New"),
        Binding("enter", "view_sessions", "Sessions"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    worktrees: list[WorktreeInfo] = []
    pr_cache: dict[str, PR] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="worktree-table")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#worktree-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Branch", "Status", "Claude", "PR", "Last Commit")
        self.load_data()
        self.set_interval(5, self.load_data)

    @work(thread=True)
    def load_data(self) -> None:
        self.worktrees = [wt for wt in list_worktrees() if not wt.is_bare]
        try:
            self.pr_cache = pr_viewer.list_prs()
        except Exception:
            self.pr_cache = {}
        self.app.call_from_thread(self._update_table)

    def _update_table(self) -> None:
        table = self.query_one("#worktree-table", DataTable)
        cursor_row = table.cursor_row
        table.clear()

        for wt in self.worktrees:
            git_status = get_git_status(wt.path)
            claude_active = ai_agent.is_active(wt.path)
            claude_col = "● active" if claude_active else "○ idle"
            pr = self.pr_cache.get(wt.branch)
            pr_col = f"#{pr.number}" if pr else "—"
            last_commit = get_last_commit_time(wt.path)
            table.add_row(wt.branch, git_status, claude_col, pr_col, last_commit)

        if self.worktrees and cursor_row < len(self.worktrees):
            table.move_cursor(row=cursor_row)

        count = len(self.worktrees)
        status = self.query_one("#status-bar", Static)
        status.update(f" {count} worktree{'s' if count != 1 else ''}")

    def _selected_worktree(self) -> WorktreeInfo | None:
        table = self.query_one("#worktree-table", DataTable)
        if not self.worktrees:
            return None
        row = table.cursor_row
        if 0 <= row < len(self.worktrees):
            return self.worktrees[row]
        return None

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
        try:
            remove_worktree(wt.path)
            self.notify(f"Removed worktree {wt.branch}")
            self.load_data()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

    def action_new_worktree(self) -> None:
        self.app.push_screen(NewWorktreeScreen())

    def action_view_sessions(self) -> None:
        wt = self._selected_worktree()
        if wt:
            self.app.push_screen(SessionListScreen(wt))

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

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("New worktree — enter branch name:"),
            Input(id="branch-input", placeholder="feature/my-branch"),
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        branch = event.value.strip()
        if not branch:
            self.notify("Branch name cannot be empty", severity="error")
            return
        try:
            create_worktree(branch)
            self.notify(f"Created worktree for {branch}")
            self.app.pop_screen()
        except RuntimeError as e:
            self.notify(str(e), severity="error")

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
    #worktree-table {
        height: 1fr;
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
    """

    def on_mount(self) -> None:
        self.push_screen(WorktreeListScreen())
