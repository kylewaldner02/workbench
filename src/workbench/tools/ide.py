from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class IntelliJIDE:
    """IntelliJ IDEA IDE launcher."""

    def open(self, worktree_path: Path) -> None:
        if not shutil.which("idea"):
            raise RuntimeError("idea not found — install IntelliJ or switch IDE in config")
        subprocess.Popen(["idea", str(worktree_path)])


class VSCodeIDE:
    """Visual Studio Code launcher."""

    def open(self, worktree_path: Path) -> None:
        if not shutil.which("code"):
            raise RuntimeError("code not found — install VS Code or switch IDE in config")
        subprocess.Popen(["code", str(worktree_path)])
