from __future__ import annotations

import subprocess
from pathlib import Path


def get_git_status(worktree_path: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=worktree_path,
    )
    if result.returncode != 0:
        return "error"
    lines = result.stdout.strip().splitlines()
    if not lines:
        return "✓ clean"

    total = len(lines)
    if total == 1:
        return "1 change"
    return f"{total} changes"


def get_last_commit_time(worktree_path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cr"],
        capture_output=True,
        text=True,
        cwd=worktree_path,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return "no commits"
    return result.stdout.strip()
