from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class IntelliJIDE:
    """IntelliJ IDEA IDE launcher."""

    def open(self, worktree_path: Path) -> None:
        if not shutil.which("idea"):
            raise RuntimeError("idea not found — install IntelliJ or configure a different IDE")
        subprocess.Popen(["idea", str(worktree_path)])
