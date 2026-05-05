from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    head: str  # commit sha
    is_bare: bool = False


def get_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository")
    return Path(result.stdout.strip())


def worktrees_dir() -> Path:
    return get_repo_root() / ".worktrees"


def list_worktrees() -> list[WorktreeInfo]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    worktrees: list[WorktreeInfo] = []
    current: dict[str, str] = {}

    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                worktrees.append(_parse_entry(current))
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["detached"] = "true"

    if current:
        worktrees.append(_parse_entry(current))

    return worktrees


def create_worktree(branch_name: str, base: str = "HEAD") -> WorktreeInfo:
    wt_dir = worktrees_dir()
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / branch_name

    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch_name, base],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Branch might already exist, try without -b
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch_name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {result.stderr.strip()}")

    # Find the new worktree in the list
    for wt in list_worktrees():
        if wt.path == wt_path:
            return wt
    return WorktreeInfo(path=wt_path, branch=branch_name, head="unknown")


def remove_worktree(worktree_path: Path) -> None:
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree_path), "--force"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to remove worktree: {result.stderr.strip()}")


def _parse_entry(entry: dict[str, str]) -> WorktreeInfo:
    branch_ref = entry.get("branch", "")
    branch = branch_ref.removeprefix("refs/heads/") if branch_ref else "(detached)"
    return WorktreeInfo(
        path=Path(entry.get("path", "")),
        branch=branch,
        head=entry.get("head", ""),
        is_bare="bare" in entry,
    )
