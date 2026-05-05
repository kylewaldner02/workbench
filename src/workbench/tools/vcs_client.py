from __future__ import annotations

import subprocess
from pathlib import Path


class EmacsMagit:
    """Emacs Magit version control client."""

    def open(self, worktree_path: Path) -> None:
        subprocess.Popen([
            "emacsclient",
            "-e",
            f'(magit-status "{worktree_path}")',
        ])
