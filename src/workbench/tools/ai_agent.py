from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from workbench.tools.base import Session


class ClaudeCodeAgent:
    """Claude Code AI agent backed by the `claude` CLI."""

    CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

    def open_cmd(self, worktree_path: Path) -> list[str]:
        return ["caffeinate", "-i", "claude"]

    def resume_cmd(self, worktree_path: Path, session_id: str) -> list[str]:
        return ["caffeinate", "-i", "claude", "--resume", session_id]

    def list_sessions(self, worktree_path: Path) -> list[Session]:
        project_dir = self._find_project_dir(worktree_path)
        if project_dir is None or not project_dir.exists():
            return []

        sessions: list[Session] = []
        for f in sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            session = self._parse_session(f, worktree_path)
            if session:
                sessions.append(session)
        return sessions

    def _find_project_dir(self, worktree_path: Path) -> Path | None:
        resolved = str(worktree_path.resolve())
        # Claude Code encodes paths by replacing / with -
        encoded = resolved.lstrip("/").replace("/", "-")
        candidate = self.CLAUDE_PROJECTS_DIR / encoded
        if candidate.exists():
            return candidate

        # Scan for a match
        if not self.CLAUDE_PROJECTS_DIR.exists():
            return None
        for d in self.CLAUDE_PROJECTS_DIR.iterdir():
            if d.is_dir() and resolved.replace("/", "-").endswith(d.name):
                return d
        return None

    def _parse_session(self, path: Path, worktree_path: Path) -> Session | None:
        try:
            label = path.stem
            last_ts: datetime | None = None
            first_user_msg: str | None = None

            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if first_user_msg is None and entry.get("role") == "human":
                        content = entry.get("content", "")
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    first_user_msg = block["text"][:80]
                                    break
                        elif isinstance(content, str):
                            first_user_msg = content[:80]
                    if "timestamp" in entry:
                        try:
                            last_ts = datetime.fromisoformat(entry["timestamp"])
                        except (ValueError, TypeError):
                            pass

            if first_user_msg:
                label = first_user_msg

            last_active = _relative_time(last_ts) if last_ts else "unknown"
            is_active = self.is_active(worktree_path)

            return Session(
                session_id=path.stem,
                label=label,
                is_active=is_active,
                last_active=last_active,
            )
        except OSError:
            return None


def _relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"
