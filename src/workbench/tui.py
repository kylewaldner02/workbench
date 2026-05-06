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
from textual.events import Key
from textual.widgets.tree import TreeNode

from workbench.state import (
    add_repo,
    add_worktree_to_project,
    archive_project,
    create_project,
    delete_project,
    find_project_for_worktree,
    hide_worktree,
    load_archived_projects,
    load_fold_state,
    load_hidden_worktrees,
    load_projects,
    load_repos,
    remove_worktree_from_project,
    save_fold_state,
    unhide_worktree,
    unarchive_project,
)
from workbench.status import get_git_status, get_last_commit_time, has_unpushed_changes
from workbench.tools import create_tools
from workbench.tools.base import PR
from workbench.worktree import (
    WorktreeInfo,
    create_worktree,
    get_repo_name,
    is_main_worktree,
    list_all_worktrees,
    remove_worktree,
)

# Tool instances — initialized from config in WorkbenchApp.on_mount
ai_agent = None
ide = None
vcs_client = None
pr_viewer = None
terminal = None

# Column widths for consistent alignment in tree labels
COL_BRANCH = 24
COL_REPO = 16
COL_STATUS = 12
COL_SESSIONS = 14
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


@dataclass
class SessionNodeData:
    """Data attached to a session tree node."""
    session_id: str
    worktree: WorktreeInfo


@dataclass
class SessionHeaderData:
    """Non-interactive header row for session columns."""
    pass


@dataclass
class WorktreeExtra:
    """Pre-computed expensive data for a worktree, gathered in background thread."""
    git_status: str
    sessions: list  # list of session objects from ai_agent
    last_commit: str


def _format_worktree_label(
    wt: WorktreeInfo,
    extra: WorktreeExtra,
    pr_cache: dict[str, PR],
) -> Text:
    session_count = len(extra.sessions)
    if session_count == 0:
        session_col = "no sessions"
    elif session_count == 1:
        session_col = "1 session"
    else:
        session_col = f"{session_count} sessions"
    pr = pr_cache.get(wt.branch)
    pr_col = f"#{pr.number}" if pr else "—"
    repo_name = get_repo_name(wt.repo)

    label = Text()
    label.append(f"{wt.branch:<{COL_BRANCH}}", style="bold")
    label.append(f"{repo_name:<{COL_REPO}}", style="dim")
    label.append(f"{extra.git_status:<{COL_STATUS}}")
    if session_count > 0:
        label.append(f"{session_col:<{COL_SESSIONS}}", style="green")
    else:
        label.append(f"{session_col:<{COL_SESSIONS}}", style="dim")
    label.append(f"{pr_col:<{COL_PR}}", style="cyan" if pr else "dim")
    label.append(extra.last_commit, style="dim")
    return label


def _format_header_label() -> Text:
    """Column header for reference."""
    label = Text()
    label.append(f"{'Branch':<{COL_BRANCH}}", style="bold dim")
    label.append(f"{'Repo':<{COL_REPO}}", style="bold dim")
    label.append(f"{'Status':<{COL_STATUS}}", style="bold dim")
    label.append(f"{'Sessions':<{COL_SESSIONS}}", style="bold dim")
    label.append(f"{'PR':<{COL_PR}}", style="bold dim")
    label.append("Last Commit", style="bold dim")
    return label


COL_SESSION_ACTIVE_WIDTH = 14


def _format_session_header(width: int) -> Text:
    label_width = max(width - COL_SESSION_ACTIVE_WIDTH, 20)
    label = Text()
    label.append(f"{'Session':<{label_width}}", style="bold dim")
    label.append("Last Active", style="bold dim")
    return label


def _format_session_label(session, width: int) -> Text:
    label_width = max(width - COL_SESSION_ACTIVE_WIDTH, 20)
    max_len = label_width - 2
    truncated = session.label[:max_len]
    if len(session.label) > max_len:
        truncated = truncated[:max_len - 2] + ".."
    label = Text()
    label.append(f"{truncated:<{label_width}}")
    label.append(session.last_active, style="dim")
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
        screen = self.screen
        if isinstance(screen, MainScreen) and screen._jumper_phase > 0:
            self._rebuild_jumper(screen._jumper_phase)
            return

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

    def _rebuild_jumper(self, phase: int) -> None:
        result = Text()
        if phase == 1:
            result.append("JUMP ", style="bold cyan")
            result.append("type first char of target line  ")
            result.append("esc", style="bold cyan")
            result.append(" cancel")
        elif phase == 2:
            result.append("JUMP ", style="bold cyan")
            result.append("type hint letter to jump  ")
            result.append("esc", style="bold cyan")
            result.append(" cancel")
        self.update(result)


class WorkbenchTree(Tree):
    """Tree that redirects space to jumper mode instead of toggle."""

    def action_toggle_node(self) -> None:
        screen = self.screen
        if isinstance(screen, MainScreen):
            screen.action_enter_jumper_mode()
        else:
            super().action_toggle_node()


class MainScreen(Screen):
    BINDINGS = [
        Binding("enter", "drill_down", "Expand"),
        Binding("tab", "drill_down", "Expand", show=False),
        Binding("space", "enter_jumper_mode", "Jump"),
        Binding("c", "open_claude_new_window", "Claude"),
        Binding("C", "open_claude", "Claude (same term)"),
        Binding("o", "new_session_new_window", "New Session"),
        Binding("O", "new_session", "New Session (same term)"),
        Binding("i", "open_ide", "IDE"),
        Binding("g", "open_git", "Git"),
        Binding("t", "open_terminal", "Terminal"),
        Binding("p", "open_pr", "PR"),
        Binding("s", "resume_session", "Resume"),
        Binding("S", "resume_session_same_term", "Resume (same term)"),
        Binding("f", "fork_session", "Fork"),
        Binding("F", "fork_session_same_term", "Fork (same term)"),
        Binding("x", "close_worktree", "Close WT"),
        Binding("n", "new_worktree", "New WT"),
        Binding("P", "new_project", "New Project"),
        Binding("R", "add_repo", "Add Repo"),
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

    JUMPER_KEYS = "asdfghjkl"

    pr_cache: dict[str, PR] = {}
    _last_cursor_line: int = 0
    _rebuilding: bool = False
    _fold_cache: dict[str, bool] | None = None
    _fold_dirty: bool = False
    _fold_flush_timer = None
    _jumper_phase: int = 0  # 0=off, 1=waiting for char, 2=showing hints
    _jumper_candidates: list[TreeNode] = []
    _jumper_saved_labels: list[tuple[TreeNode, Text | str]] = []

    def _on_tree_cursor_changed(self) -> None:
        """Re-evaluate binding states when cursor moves."""
        self.refresh_bindings()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        # Skip session header nodes — they're display-only
        node = event.node
        if isinstance(node.data, SessionHeaderData):
            tree = self.query_one("#main-tree", Tree)
            going_down = tree.cursor_line >= self._last_cursor_line
            if going_down and node.next_sibling:
                tree.select_node(node.next_sibling)
            else:
                # Move up past the header — go to the line above it
                header_line = tree.cursor_line
                if header_line > 0:
                    tree.move_cursor_to_line(header_line - 1)
            self._last_cursor_line = tree.cursor_line
            return

        self._last_cursor_line = self.query_one("#main-tree", Tree).cursor_line
        self._on_tree_cursor_changed()
        try:
            self.query_one(WrappingFooter)._rebuild()
        except Exception:
            pass

    def _get_fold_cache(self) -> dict[str, bool]:
        if self._fold_cache is None:
            self._fold_cache = load_fold_state()
        return self._fold_cache

    def _schedule_fold_flush(self) -> None:
        if self._fold_flush_timer is not None:
            self._fold_flush_timer.stop()
        self._fold_flush_timer = self.set_timer(2.0, self._flush_fold_state)

    def _flush_fold_state(self) -> None:
        if self._fold_dirty and self._fold_cache is not None:
            save_fold_state(self._fold_cache)
            self._fold_dirty = False

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if not self._rebuilding:
            self._save_fold_state()

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        if not self._rebuilding:
            self._save_fold_state()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if self._jumper_phase > 0:
            return False
        node = self._selected_node()
        on_session = node is not None and isinstance(node.data, SessionNodeData)
        on_project = node is not None and isinstance(node.data, ProjectNodeData)
        on_worktree = node is not None and isinstance(node.data, WorktreeNodeData)

        worktree_actions = {
            "open_claude", "open_claude_new_window",
            "new_session", "new_session_new_window",
            "open_ide", "open_git", "open_terminal",
            "open_pr", "close_worktree", "assign_to_project",
        }
        project_actions = {"archive_project"}
        session_actions = {
            "resume_session", "resume_session_same_term",
            "fork_session", "fork_session_same_term",
        }

        if action in session_actions:
            return on_session
        if action in worktree_actions:
            return on_worktree
        if action in project_actions:
            return on_project and node.data.project_name is not None
        if action == "new_worktree":
            return not on_session
        if action == "new_project":
            return not on_session
        return True

    def compose(self) -> ComposeResult:
        yield Static(_format_header_label(), id="col-header")
        tree: WorkbenchTree[WorktreeNodeData | ProjectNodeData] = WorkbenchTree("workbench", id="main-tree")
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
        if self._jumper_phase > 0:
            return
        repos = load_repos()
        hidden = load_hidden_worktrees()
        all_worktrees = list_all_worktrees(repos, hidden)
        projects = load_projects()

        try:
            self.pr_cache = pr_viewer.list_prs()
        except Exception:
            self.pr_cache = {}

        # Pre-compute expensive I/O (git, sessions) in this background thread
        extras: dict[str, WorktreeExtra] = {}
        for wt in all_worktrees:
            extras[str(wt.path)] = WorktreeExtra(
                git_status=get_git_status(wt.path),
                sessions=ai_agent.list_sessions(wt.path),
                last_commit=get_last_commit_time(wt.path),
            )

        self.app.call_from_thread(self._rebuild_tree, all_worktrees, projects, extras)

    def _rebuild_tree(self, all_worktrees: list[WorktreeInfo], projects: list, extras: dict[str, WorktreeExtra]) -> None:
        self._rebuilding = True
        self._do_rebuild_tree(all_worktrees, projects, extras)
        # Defer clearing the flag so queued expand/collapse events are still suppressed
        self.set_timer(0.1, self._end_rebuild)

    def _end_rebuild(self) -> None:
        self._rebuilding = False

    def _do_rebuild_tree(self, all_worktrees: list[WorktreeInfo], projects: list, extras: dict[str, WorktreeExtra]) -> None:
        tree = self.query_one("#main-tree", Tree)
        fold = self._get_fold_cache()
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
                    self._add_worktree_node(project_node, wt, project.name, fold, extras)

            key = f"project:{project.name}"
            if fold.get(key, True):  # default expanded
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
                self._add_worktree_node(unassigned_node, wt, None, fold, extras)

            key = "project:None"
            if fold.get(key, True):  # default expanded
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

        # Update status bar (skip during jumper mode)
        if self._jumper_phase == 0:
            status = self.query_one("#status-bar", Static)
            status.update(f" {len(projects)} projects · {len(all_worktrees)} worktrees")

    def _add_worktree_node(
        self,
        parent_node: TreeNode,
        wt: WorktreeInfo,
        project_name: str | None,
        fold: dict[str, bool],
        extras: dict[str, WorktreeExtra],
    ) -> None:
        extra = extras.get(str(wt.path), WorktreeExtra(git_status="?", sessions=[], last_commit="?"))
        label = _format_worktree_label(wt, extra, self.pr_cache)
        wt_node = parent_node.add(
            label,
            data=WorktreeNodeData(worktree=wt, project_name=project_name),
        )

        # Add session children
        sessions = extra.sessions
        if sessions:
            # Estimate available width: tree width minus indent for session depth
            try:
                tree_width = self.query_one("#main-tree", Tree).size.width
            except Exception:
                tree_width = 80
            session_indent = 12  # guide chars for depth 2
            avail = tree_width - session_indent
            wt_node.add_leaf(_format_session_header(avail), data=SessionHeaderData())
            for s in sessions:
                wt_node.add_leaf(
                    _format_session_label(s, avail),
                    data=SessionNodeData(session_id=s.session_id, worktree=wt),
                )

        # Restore expand state — collapsed by default
        key = f"worktree:{wt.path}"
        if fold.get(key, False):
            wt_node.expand()
        else:
            wt_node.collapse()

    def _selected_node(self) -> TreeNode | None:
        tree = self.query_one("#main-tree", Tree)
        return tree.cursor_node

    def _selected_worktree_data(self) -> WorktreeNodeData | None:
        node = self._selected_node()
        if node and isinstance(node.data, WorktreeNodeData):
            return node.data
        # If on a session node, return the parent worktree
        if node and isinstance(node.data, (SessionNodeData, SessionHeaderData)):
            parent = node.parent
            if parent and isinstance(parent.data, WorktreeNodeData):
                return parent.data
        return None

    def _selected_project_data(self) -> ProjectNodeData | None:
        node = self._selected_node()
        if node and isinstance(node.data, ProjectNodeData):
            return node.data
        return None

    def _save_fold_state(self) -> None:
        """Update in-memory fold state and schedule a debounced disk write."""
        tree = self.query_one("#main-tree", Tree)
        fold = self._get_fold_cache()
        for proj_node in tree.root.children:
            if isinstance(proj_node.data, ProjectNodeData):
                fold[f"project:{proj_node.data.project_name}"] = proj_node.is_expanded
            for wt_node in proj_node.children:
                if isinstance(wt_node.data, WorktreeNodeData):
                    fold[f"worktree:{wt_node.data.worktree.path}"] = wt_node.is_expanded
        self._fold_dirty = True
        self._schedule_fold_flush()

    def action_drill_down(self) -> None:
        node = self._selected_node()
        if not node:
            return
        if isinstance(node.data, WorktreeNodeData):
            node.toggle()
        elif isinstance(node.data, ProjectNodeData):
            node.toggle()
        elif isinstance(node.data, SessionNodeData):
            # Leaf: navigate to parent worktree
            if node.parent:
                tree = self.query_one("#main-tree", Tree)
                node.parent.collapse()
                tree.select_node(node.parent)

    def action_resume_session(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, SessionNodeData):
            wt = node.data.worktree
            cmd = ai_agent.resume_cmd(wt.path, node.data.session_id)
            terminal.run_cmd(cmd, str(wt.path))
            self.notify(f"Resumed session in new window for {wt.branch}")

    def action_resume_session_same_term(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, SessionNodeData):
            wt = node.data.worktree
            cmd = ai_agent.resume_cmd(wt.path, node.data.session_id)
            self.app.launch_agent(cmd, str(wt.path))

    def action_fork_session(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, SessionNodeData):
            wt = node.data.worktree
            cmd = ai_agent.resume_cmd(wt.path, node.data.session_id)
            terminal.run_cmd(cmd, str(wt.path))
            self.notify(f"Forked session in new window for {wt.branch}")

    def action_fork_session_same_term(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, SessionNodeData):
            wt = node.data.worktree
            cmd = ai_agent.resume_cmd(wt.path, node.data.session_id)
            self.app.launch_agent(cmd, str(wt.path))

    def action_open_claude(self) -> None:
        wt_data = self._selected_worktree_data()
        if not wt_data:
            return
        wt = wt_data.worktree
        sessions = ai_agent.list_sessions(wt.path)
        if sessions:
            cmd = ai_agent.resume_cmd(wt.path, sessions[0].session_id)
        else:
            cmd = ai_agent.open_cmd(wt.path)
        self.app.launch_agent(cmd, str(wt.path))

    def action_open_claude_new_window(self) -> None:
        wt_data = self._selected_worktree_data()
        if not wt_data:
            return
        wt = wt_data.worktree
        sessions = ai_agent.list_sessions(wt.path)
        if sessions:
            cmd = ai_agent.resume_cmd(wt.path, sessions[0].session_id)
        else:
            cmd = ai_agent.open_cmd(wt.path)
        terminal.run_cmd(cmd, str(wt.path))
        self.notify(f"Opened Claude in new window for {wt.branch}")

    def action_new_session_new_window(self) -> None:
        wt_data = self._selected_worktree_data()
        if not wt_data:
            return
        wt = wt_data.worktree
        cmd = ai_agent.open_cmd(wt.path)
        terminal.run_cmd(cmd, str(wt.path))
        self.notify(f"New session in new window for {wt.branch}")

    def action_new_session(self) -> None:
        wt_data = self._selected_worktree_data()
        if not wt_data:
            return
        wt = wt_data.worktree
        cmd = ai_agent.open_cmd(wt.path)
        self.app.launch_agent(cmd, str(wt.path))

    def action_open_ide(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            try:
                ide.open(wt_data.worktree.path)
                self.notify(f"Opened IDE in {wt_data.worktree.branch}")
            except RuntimeError as e:
                self.notify(str(e), severity="error")

    def action_open_git(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            try:
                vcs_client.open(wt_data.worktree.path)
                self.notify(f"Opened git client in {wt_data.worktree.branch}")
            except RuntimeError as e:
                self.notify(str(e), severity="error")

    def action_open_terminal(self) -> None:
        wt_data = self._selected_worktree_data()
        if wt_data:
            try:
                terminal.open(wt_data.worktree.path)
                self.notify(f"Opened terminal in {wt_data.worktree.branch}")
            except RuntimeError as e:
                self.notify(str(e), severity="error")

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
        if has_unpushed_changes(wt.path, wt.branch):
            self.app.push_screen(ConfirmCloseWorktreeScreen(wt_data))
        else:
            self._do_close_worktree(wt_data)

    def _do_close_worktree(self, wt_data: WorktreeNodeData) -> None:
        wt = wt_data.worktree
        try:
            if is_main_worktree(wt):
                # Can't remove main worktree — hide it instead
                hide_worktree(str(wt.path))
                if wt_data.project_name:
                    remove_worktree_from_project(wt_data.project_name, str(wt.path))
                self.notify(f"Hidden worktree {wt.branch}")
            else:
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

    def action_add_repo(self) -> None:
        self.app.push_screen(AddRepoScreen())

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
        if node and isinstance(node.data, (ProjectNodeData, WorktreeNodeData)):
            node.expand()

    def action_cursor_collapse(self) -> None:
        node = self._selected_node()
        if node and isinstance(node.data, (ProjectNodeData, WorktreeNodeData)):
            node.collapse()

    def action_refresh(self) -> None:
        self.load_data()

    # ── Jumper mode ──────────────────────────────────────────────
    def _visible_nodes(self) -> list[TreeNode]:
        """Return expanded, non-root tree nodes in display order."""
        nodes: list[TreeNode] = []
        tree = self.query_one("#main-tree", Tree)

        def walk(node: TreeNode) -> None:
            for child in node.children:
                if isinstance(child.data, SessionHeaderData):
                    continue
                nodes.append(child)
                if child.is_expanded:
                    walk(child)

        walk(tree.root)
        return nodes

    def action_enter_jumper_mode(self) -> None:
        self._jumper_phase = 1
        self._rebuild_footer()

    def _jumper_show_hints(self, candidates: list[TreeNode]) -> None:
        """Replace labels on candidate nodes with hint keys."""
        self._jumper_saved_labels = []
        self._jumper_candidates = []
        keys = self.JUMPER_KEYS
        for i, node in enumerate(candidates[: len(keys)]):
            self._jumper_saved_labels.append((node, node.label))
            hint_char = keys[i]
            original_text = node.label.plain if isinstance(node.label, Text) else str(node.label)
            label = Text()
            label.append(hint_char, style="bold reverse cyan")
            label.append(" ")
            label.append(original_text)
            node.set_label(label)
            self._jumper_candidates.append(node)
        self._jumper_phase = 2

    def _jumper_restore_labels(self) -> None:
        """Restore original labels on all hinted nodes."""
        for node, original_label in self._jumper_saved_labels:
            node.set_label(original_label)
        self._jumper_saved_labels = []
        self._jumper_candidates = []

    def _rebuild_footer(self) -> None:
        try:
            self.query_one(WrappingFooter)._rebuild()
        except Exception:
            pass

    def _jumper_cancel(self) -> None:
        self._jumper_restore_labels()
        self._jumper_phase = 0
        self._rebuild_footer()

    def on_key(self, event: Key) -> None:
        if self._jumper_phase > 0:
            event.prevent_default()
            event.stop()
            self._handle_jumper_key(event)

    def _handle_jumper_key(self, event: Key) -> None:
        if event.key == "escape":
            self._jumper_cancel()
            return

        if self._jumper_phase == 1:
            # Phase 1: user types a character to filter visible nodes
            char = event.character
            if not char or not char.isprintable():
                self._jumper_cancel()
                return

            visible = self._visible_nodes()
            matches = []
            for node in visible:
                label_text = node.label.plain if isinstance(node.label, Text) else str(node.label)
                # Match against first non-whitespace character
                stripped = label_text.lstrip()
                if stripped and stripped[0].lower() == char.lower():
                    matches.append(node)

            if not matches:
                self.notify(f"No lines starting with '{char}'", severity="warning")
                self._jumper_cancel()
                return

            if len(matches) == 1:
                # Only one match — jump directly
                tree = self.query_one("#main-tree", Tree)
                tree.move_cursor(matches[0])
                self._jumper_phase = 0
                self._rebuild_footer()
                return

            self._jumper_show_hints(matches)
            self._rebuild_footer()
            return

        if self._jumper_phase == 2:
            # Phase 2: user types a hint key to select
            char = event.character
            if not char:
                self._jumper_cancel()
                return

            keys = self.JUMPER_KEYS
            if char.lower() in keys:
                idx = keys.index(char.lower())
                if idx < len(self._jumper_candidates):
                    target = self._jumper_candidates[idx]
                    self._jumper_restore_labels()
                    tree = self.query_one("#main-tree", Tree)
                    tree.move_cursor(target)
                    self._jumper_phase = 0
                    self._rebuild_footer()
                    return

            # Invalid hint key
            self._jumper_cancel()

    def action_quit(self) -> None:
        self._flush_fold_state()
        self.app.exit()



class NewWorktreeScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+n", "focus_next", show=False),
        Binding("ctrl+p", "focus_previous", show=False),
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


class AddRepoScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+n", "focus_next", show=False),
        Binding("ctrl+p", "focus_previous", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Add repo — enter path:"),
            Input(id="repo-path-input", placeholder="/path/to/repo"),
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = event.value.strip()
        if not path:
            self.notify("Path cannot be empty", severity="error")
            return
        resolved = Path(path).expanduser().resolve()
        if not (resolved / ".git").exists():
            self.notify(f"Not a git repo: {resolved}", severity="error")
            return
        add_repo(str(resolved))
        self.notify(f"Added repo: {resolved}")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.pop_screen()


class NewProjectScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+n", "focus_next", show=False),
        Binding("ctrl+p", "focus_previous", show=False),
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
        Binding("ctrl+n", "focus_next", show=False),
        Binding("ctrl+p", "focus_previous", show=False),
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


class ConfirmCloseWorktreeScreen(Screen):
    BINDINGS = [
        Binding("y", "confirm", "Yes, close"),
        Binding("n", "cancel", "No, keep"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, wt_data: WorktreeNodeData) -> None:
        super().__init__()
        self.wt_data = wt_data

    def compose(self) -> ComposeResult:
        wt = self.wt_data.worktree
        yield Vertical(
            Label(f"Branch '{wt.branch}' has unpushed changes."),
            Label("Close worktree anyway? (y/n)"),
        )
        yield WrappingFooter()

    def action_confirm(self) -> None:
        self.app.pop_screen()
        main_screen = self.app.screen
        main_screen._do_close_worktree(self.wt_data)

    def action_cancel(self) -> None:
        self.app.pop_screen()


class CreatePRScreen(Screen):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+n", "focus_next", show=False),
        Binding("ctrl+p", "focus_previous", show=False),
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
        Binding("ctrl+n", "focus_next", show=False),
        Binding("ctrl+p", "focus_previous", show=False),
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
    TITLE = "workbench-tui"
    CSS = """
    #main-tree {
        height: 1fr;
    }
    #col-header {
        height: 1;
        padding: 0 0 0 6;
        background: $surface;
        color: $text-muted;
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

    exec_cmd: list[str] | None = None
    exec_cwd: str | None = None

    def on_mount(self) -> None:
        global ai_agent, ide, vcs_client, pr_viewer, terminal
        from workbench.state import ensure_config
        config = ensure_config()
        tools = create_tools(config)
        ai_agent = tools["ai_agent"]
        ide = tools["ide"]
        vcs_client = tools["vcs_client"]
        pr_viewer = tools["pr_viewer"]
        terminal = tools["terminal"]

        try:
            from workbench.worktree import get_repo_root
            repo = get_repo_root()
            # Don't auto-add home dir, root, or shallow system paths
            home = Path.home()
            skip = {Path("/"), home, home / "Desktop", home / "Documents", home / "src"}
            if repo not in skip and len(repo.parts) > 2:
                add_repo(str(repo))
        except RuntimeError:
            pass
        self.push_screen(MainScreen())

    def launch_agent(self, cmd: list[str], cwd: str) -> None:
        """Store command and exit — CLI will exec into it."""
        self.exec_cmd = cmd
        self.exec_cwd = cwd
        self.exit()
