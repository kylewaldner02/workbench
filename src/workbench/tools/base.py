from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Session:
    session_id: str
    label: str
    is_active: bool
    last_active: str  # relative time string like "2m ago"


@dataclass
class PR:
    number: int
    url: str
    state: str  # "OPEN", "CLOSED", "MERGED"
    title: str


class AIAgent(Protocol):
    """An AI coding agent (Claude Code, Cursor, Aider, etc.)"""

    def open_cmd(self, worktree_path: Path) -> list[str]: ...

    def resume_cmd(self, worktree_path: Path, session_id: str) -> list[str]: ...

    def list_sessions(self, worktree_path: Path) -> list[Session]: ...


class IDE(Protocol):
    """An IDE or editor (IntelliJ, VS Code, Neovim, etc.)"""

    def open(self, worktree_path: Path) -> None: ...


class VCSClient(Protocol):
    """A git UI client (Emacs Magit, lazygit, GitKraken, etc.)"""

    def open(self, worktree_path: Path) -> None: ...


class PRViewer(Protocol):
    """PR management (GitHub CLI, GitLab CLI, etc.)"""

    def get_pr(self, branch: str) -> PR | None: ...

    def create_pr(self, branch: str, base: str) -> PR: ...

    def open_in_browser(self, branch: str) -> None: ...
