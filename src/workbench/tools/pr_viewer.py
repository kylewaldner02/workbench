from __future__ import annotations

import json
import subprocess

from workbench.tools.base import PR


class GitHubCLIPR:
    """GitHub CLI (gh) backed PR viewer."""

    def get_pr(self, branch: str) -> PR | None:
        result = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "number,url,state,title"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return PR(
                number=data["number"],
                url=data["url"],
                state=data["state"],
                title=data["title"],
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def create_pr(self, branch: str, base: str) -> PR:
        result = subprocess.run(
            ["gh", "pr", "create", "--head", branch, "--base", base, "--fill"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create PR: {result.stderr.strip()}")
        # gh pr create outputs the URL on success
        url = result.stdout.strip()
        # Fetch the created PR info
        pr = self.get_pr(branch)
        if pr:
            return pr
        return PR(number=0, url=url, state="OPEN", title=branch)

    def open_in_browser(self, branch: str) -> None:
        subprocess.run(
            ["gh", "pr", "view", branch, "--web"],
            capture_output=True,
        )

    def list_prs(self) -> dict[str, PR]:
        """Return a mapping of branch name -> PR for all open PRs."""
        result = subprocess.run(
            ["gh", "pr", "list", "--json", "number,url,state,title,headRefName", "--limit", "100"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {}
        try:
            data = json.loads(result.stdout)
            return {
                item["headRefName"]: PR(
                    number=item["number"],
                    url=item["url"],
                    state=item["state"],
                    title=item["title"],
                )
                for item in data
            }
        except (json.JSONDecodeError, KeyError):
            return {}
