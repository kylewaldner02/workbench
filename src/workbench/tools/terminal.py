from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path


class MacTerminal:
    """Opens new Terminal.app windows."""

    def open(self, worktree_path: Path) -> None:
        subprocess.Popen(["open", "-a", "Terminal", str(worktree_path)])

    def run_cmd(self, cmd: list[str], cwd: str) -> None:
        shell_cmd = " ".join(shlex.quote(c) for c in cmd)
        fd, script_path = tempfile.mkstemp(suffix=".command")
        with os.fdopen(fd, "w") as f:
            f.write("#!/bin/bash\n")
            f.write(f"cd {shlex.quote(cwd)}\n")
            f.write(f"exec {shell_cmd}\n")
        os.chmod(script_path, 0o755)
        subprocess.Popen(["open", script_path])


class ITerm2:
    """Opens new iTerm2 windows."""

    def open(self, worktree_path: Path) -> None:
        subprocess.Popen(["open", "-a", "iTerm", str(worktree_path)])

    def run_cmd(self, cmd: list[str], cwd: str) -> None:
        shell_cmd = " ".join(shlex.quote(c) for c in cmd)
        full_cmd = f"cd {shlex.quote(cwd)} && exec {shell_cmd}"
        script = (
            'tell application "iTerm"\n'
            "  create window with default profile\n"
            "  tell current session of current window\n"
            f'    write text {shlex.quote(full_cmd)}\n'
            "  end tell\n"
            "end tell"
        )
        subprocess.Popen(["osascript", "-e", script])
