from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = Path.home() / ".workbench"
PROJECTS_FILE = STATE_DIR / "projects.json"
REPOS_FILE = STATE_DIR / "repos.json"


@dataclass
class ProjectWorktree:
    repo: str  # absolute path to repo root
    branch: str
    worktree_path: str  # absolute path to worktree directory

    def to_dict(self) -> dict:
        return {"repo": self.repo, "branch": self.branch, "worktree_path": self.worktree_path}

    @classmethod
    def from_dict(cls, d: dict) -> ProjectWorktree:
        return cls(repo=d["repo"], branch=d["branch"], worktree_path=d["worktree_path"])


@dataclass
class Project:
    name: str
    worktrees: list[ProjectWorktree] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "worktrees": [w.to_dict() for w in self.worktrees]}

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(
            name=d["name"],
            worktrees=[ProjectWorktree.from_dict(w) for w in d.get("worktrees", [])],
        )


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


# --- Projects ---


def load_projects() -> list[Project]:
    if not PROJECTS_FILE.exists():
        return []
    try:
        data = json.loads(PROJECTS_FILE.read_text())
        return [Project.from_dict(p) for p in data.get("projects", [])]
    except (json.JSONDecodeError, OSError):
        return []


def save_projects(projects: list[Project]) -> None:
    _ensure_dir()
    data = {"projects": [p.to_dict() for p in projects]}
    PROJECTS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def get_project(name: str) -> Project | None:
    for p in load_projects():
        if p.name == name:
            return p
    return None


def create_project(name: str) -> Project:
    projects = load_projects()
    for p in projects:
        if p.name == name:
            raise ValueError(f"Project '{name}' already exists")
    project = Project(name=name)
    projects.append(project)
    save_projects(projects)
    return project


def delete_project(name: str) -> None:
    projects = load_projects()
    projects = [p for p in projects if p.name != name]
    save_projects(projects)


def add_worktree_to_project(project_name: str, repo: str, branch: str, worktree_path: str) -> None:
    projects = load_projects()
    for p in projects:
        if p.name == project_name:
            # Don't add duplicates
            for w in p.worktrees:
                if w.worktree_path == worktree_path:
                    return
            p.worktrees.append(ProjectWorktree(repo=repo, branch=branch, worktree_path=worktree_path))
            save_projects(projects)
            return
    raise ValueError(f"Project '{project_name}' not found")


def remove_worktree_from_project(project_name: str, worktree_path: str) -> None:
    projects = load_projects()
    for p in projects:
        if p.name == project_name:
            p.worktrees = [w for w in p.worktrees if w.worktree_path != worktree_path]
            save_projects(projects)
            return


def find_project_for_worktree(worktree_path: str) -> str | None:
    """Return the project name a worktree belongs to, or None if unassigned."""
    for p in load_projects():
        for w in p.worktrees:
            if w.worktree_path == worktree_path:
                return p.name
    return None


# --- Known Repos ---


def load_repos() -> list[str]:
    if not REPOS_FILE.exists():
        return []
    try:
        data = json.loads(REPOS_FILE.read_text())
        return data.get("repos", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_repos(repos: list[str]) -> None:
    _ensure_dir()
    data = {"repos": sorted(set(repos))}
    REPOS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def add_repo(repo_path: str) -> None:
    repos = load_repos()
    resolved = str(Path(repo_path).resolve())
    if resolved not in repos:
        repos.append(resolved)
        save_repos(repos)


def remove_repo(repo_path: str) -> None:
    repos = load_repos()
    resolved = str(Path(repo_path).resolve())
    repos = [r for r in repos if r != resolved]
    save_repos(repos)
