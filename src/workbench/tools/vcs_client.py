from __future__ import annotations

import subprocess
from pathlib import Path


class EmacsMagit:
    """Emacs Magit version control client via Emacs.app."""

    def open(self, worktree_path: Path) -> None:
        subprocess.Popen([
            "open", "-a", "Emacs", "--args", str(worktree_path),
        ])
