from __future__ import annotations

from workbench.tools.base import PR
from workbench.tools.pr_viewer import GitHubCLIPR

_gh = GitHubCLIPR()


def get_pr_for_branch(branch: str) -> PR | None:
    return _gh.get_pr(branch)


def create_pr(branch: str, base: str = "main") -> PR:
    return _gh.create_pr(branch, base)


def open_pr_in_browser(branch: str) -> None:
    _gh.open_in_browser(branch)


def list_prs() -> dict[str, PR]:
    return _gh.list_prs()
