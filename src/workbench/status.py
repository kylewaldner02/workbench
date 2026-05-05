from __future__ import annotations

import subprocess
from collections import Counter
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
        return "clean"

    counts: Counter[str] = Counter()
    for line in lines:
        if len(line) < 2:
            continue
        xy = line[:2]
        if xy[0] == "?" or xy[1] == "?":
            counts["U"] += 1  # untracked
        elif xy[0] in ("M", " ") or xy[1] == "M":
            counts["M"] += 1
        elif xy[0] == "A" or xy[1] == "A":
            counts["A"] += 1
        elif xy[0] == "D" or xy[1] == "D":
            counts["D"] += 1
        else:
            counts["?"] += 1

    parts = []
    for key in ("M", "A", "D", "U"):
        if counts[key]:
            parts.append(f"{counts[key]}{key}")
    return " ".join(parts) if parts else "clean"


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
