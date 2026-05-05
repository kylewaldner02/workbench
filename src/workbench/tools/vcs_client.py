from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class EmacsMagit:
    """Emacs Magit version control client."""

    def open(self, worktree_path: Path) -> None:
        if not shutil.which("emacsclient"):
            raise RuntimeError("emacsclient not found — install Emacs or configure a different VCS client")
        subprocess.Popen([
            "emacsclient",
            "-e",
            f'(magit-status "{worktree_path}")',
        ])
