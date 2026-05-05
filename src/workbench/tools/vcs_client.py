from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class EmacsOpen:
    """Open directory in Emacs.app directly."""

    def open(self, worktree_path: Path) -> None:
        subprocess.Popen([
            "open", "-a", "Emacs", "--args", str(worktree_path),
        ])


class EmacsMagit:
    """Emacs Magit via emacsclient (requires Emacs server running)."""

    def open(self, worktree_path: Path) -> None:
        if not shutil.which("emacsclient"):
            raise RuntimeError("emacsclient not found — add it to PATH or switch to 'emacs-open' in config")
        elisp = (
            f'(progn'
            f'  (magit-status "{worktree_path}")'
            f'  (select-frame-set-input-focus (selected-frame)))'
        )
        subprocess.Popen(["emacsclient", "-e", elisp])
        subprocess.Popen(["open", "-a", "Emacs"])


class LazyGit:
    """lazygit terminal UI."""

    def open(self, worktree_path: Path) -> None:
        if not shutil.which("lazygit"):
            raise RuntimeError("lazygit not found — install it or switch VCS client in config")
        subprocess.Popen(["lazygit"], cwd=worktree_path)
