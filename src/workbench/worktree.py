from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    head: str  # commit sha
    repo: Path  # root of the git repo this worktree belongs to
    is_bare: bool = False


def get_repo_root(cwd: Path | None = None) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError("Not inside a git repository")
    return Path(result.stdout.strip())


def get_repo_name(repo_path: Path) -> str:
    """Get a short display name for a repo (last component of path)."""
    return repo_path.name


def worktrees_dir(repo_path: Path) -> Path:
    return repo_path / ".worktrees"


def list_worktrees_for_repo(repo_path: Path) -> list[WorktreeInfo]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        return []

    worktrees: list[WorktreeInfo] = []
    current: dict[str, str] = {}

    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                worktrees.append(_parse_entry(current, repo_path))
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
        worktrees.append(_parse_entry(current, repo_path))

    return worktrees


def list_all_worktrees(repo_paths: list[str], hidden: set[str] | None = None) -> list[WorktreeInfo]:
    """List worktrees across all known repos, excluding hidden ones."""
    all_wts: list[WorktreeInfo] = []
    for repo in repo_paths:
        repo_path = Path(repo)
        if repo_path.exists():
            all_wts.extend(list_worktrees_for_repo(repo_path))
    result = [wt for wt in all_wts if not wt.is_bare]
    if hidden:
        result = [wt for wt in result if str(wt.path) not in hidden]
    return result


def is_main_worktree(wt: WorktreeInfo) -> bool:
    """Check if this is the repo's main worktree (not removable by git)."""
    return wt.path.resolve() == wt.repo.resolve()


def create_worktree(repo_path: Path, branch_name: str, base: str = "HEAD") -> WorktreeInfo:
    wt_dir = worktrees_dir(repo_path)
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / branch_name

    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch_name, base],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        # Branch might already exist, try without -b
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch_name],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {result.stderr.strip()}")

    for wt in list_worktrees_for_repo(repo_path):
        if wt.path == wt_path:
            return wt
    return WorktreeInfo(path=wt_path, branch=branch_name, head="unknown", repo=repo_path)


def remove_worktree(worktree_path: Path) -> None:
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree_path), "--force"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to remove worktree: {result.stderr.strip()}")


def _parse_entry(entry: dict[str, str], repo: Path) -> WorktreeInfo:
    branch_ref = entry.get("branch", "")
    branch = branch_ref.removeprefix("refs/heads/") if branch_ref else "(detached)"
    return WorktreeInfo(
        path=Path(entry.get("path", "")),
        branch=branch,
        head=entry.get("head", ""),
        repo=repo,
        is_bare="bare" in entry,
    )
