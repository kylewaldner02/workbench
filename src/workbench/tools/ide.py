from __future__ import annotations

import subprocess
from pathlib import Path


class IntelliJIDE:
    """IntelliJ IDEA IDE launcher."""

    def open(self, worktree_path: Path) -> None:
        subprocess.Popen(["idea", str(worktree_path)])
