from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = Path.home() / ".workbench"
LOCAL_STATE_DIR = STATE_DIR / "local-state"
PROJECTS_FILE = LOCAL_STATE_DIR / "projects.json"
REPOS_FILE = LOCAL_STATE_DIR / "repos.json"
FOLD_STATE_FILE = LOCAL_STATE_DIR / "fold_state.json"
HIDDEN_WORKTREES_FILE = LOCAL_STATE_DIR / "hidden_worktrees.json"
CONFIG_FILE = STATE_DIR / "config.json"

DEFAULT_CONFIG = {
    "ide": "intellij",
    "vcs_client": "emacs-open",
    "ai_agent": "claude-code",
    "pr_viewer": "github",
    "terminal": "terminal-app",
}


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
    archived: bool = False

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "worktrees": [w.to_dict() for w in self.worktrees]}
        if self.archived:
            d["archived"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(
            name=d["name"],
            worktrees=[ProjectWorktree.from_dict(w) for w in d.get("worktrees", [])],
            archived=d.get("archived", False),
        )


def _ensure_dir() -> None:
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)


# --- Projects ---


def _load_all_projects() -> list[Project]:
    if not PROJECTS_FILE.exists():
        return []
    try:
        data = json.loads(PROJECTS_FILE.read_text())
        return [Project.from_dict(p) for p in data.get("projects", [])]
    except (json.JSONDecodeError, OSError):
        return []


def load_projects() -> list[Project]:
    return [p for p in _load_all_projects() if not p.archived]


def load_archived_projects() -> list[Project]:
    return [p for p in _load_all_projects() if p.archived]


def save_projects(projects: list[Project]) -> None:
    """Save a full list of projects (active + archived)."""
    _ensure_dir()
    data = {"projects": [p.to_dict() for p in projects]}
    PROJECTS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _save_update(updater) -> None:
    """Load all projects, apply updater function, save back."""
    all_projects = _load_all_projects()
    updater(all_projects)
    save_projects(all_projects)


def get_project(name: str) -> Project | None:
    for p in load_projects():
        if p.name == name:
            return p
    return None


def create_project(name: str) -> Project:
    all_projects = _load_all_projects()
    for p in all_projects:
        if p.name == name:
            raise ValueError(f"Project '{name}' already exists")
    project = Project(name=name)
    all_projects.append(project)
    save_projects(all_projects)
    return project


def delete_project(name: str) -> None:
    all_projects = _load_all_projects()
    all_projects = [p for p in all_projects if p.name != name]
    save_projects(all_projects)


def add_worktree_to_project(project_name: str, repo: str, branch: str, worktree_path: str) -> None:
    all_projects = _load_all_projects()
    for p in all_projects:
        if p.name == project_name:
            for w in p.worktrees:
                if w.worktree_path == worktree_path:
                    return
            p.worktrees.append(ProjectWorktree(repo=repo, branch=branch, worktree_path=worktree_path))
            save_projects(all_projects)
            return
    raise ValueError(f"Project '{project_name}' not found")


def remove_worktree_from_project(project_name: str, worktree_path: str) -> None:
    all_projects = _load_all_projects()
    for p in all_projects:
        if p.name == project_name:
            p.worktrees = [w for w in p.worktrees if w.worktree_path != worktree_path]
            save_projects(all_projects)
            return


def find_project_for_worktree(worktree_path: str) -> str | None:
    """Return the project name a worktree belongs to, or None if unassigned."""
    for p in load_projects():
        for w in p.worktrees:
            if w.worktree_path == worktree_path:
                return p.name
    return None


def archive_project(name: str) -> None:
    def _update(projects: list[Project]) -> None:
        for p in projects:
            if p.name == name:
                p.archived = True
                return
    _save_update(_update)


def unarchive_project(name: str) -> None:
    def _update(projects: list[Project]) -> None:
        for p in projects:
            if p.name == name:
                p.archived = False
                return
    _save_update(_update)


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


# --- Fold State ---


def load_fold_state() -> dict[str, bool]:
    """Load fold state. Keys are node identifiers, values are True=expanded."""
    if not FOLD_STATE_FILE.exists():
        return {}
    try:
        return json.loads(FOLD_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_fold_state(state: dict[str, bool]) -> None:
    _ensure_dir()
    FOLD_STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


# --- Hidden Worktrees ---


def load_hidden_worktrees() -> set[str]:
    if not HIDDEN_WORKTREES_FILE.exists():
        return set()
    try:
        data = json.loads(HIDDEN_WORKTREES_FILE.read_text())
        return set(data.get("hidden", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_hidden_worktrees(hidden: set[str]) -> None:
    _ensure_dir()
    data = {"hidden": sorted(hidden)}
    HIDDEN_WORKTREES_FILE.write_text(json.dumps(data, indent=2) + "\n")


def hide_worktree(worktree_path: str) -> None:
    hidden = load_hidden_worktrees()
    hidden.add(worktree_path)
    save_hidden_worktrees(hidden)


def unhide_worktree(worktree_path: str) -> None:
    hidden = load_hidden_worktrees()
    hidden.discard(worktree_path)
    save_hidden_worktrees(hidden)


# --- Config ---


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text())
            config.update(user)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def ensure_config() -> dict:
    """Load config, creating the file with defaults if it doesn't exist."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
    return load_config()
