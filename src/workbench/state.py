from __future__ import annotations

import json
from pathlib import Path

STATE_DIR = Path.home() / ".workbench"
STATE_FILE = STATE_DIR / "state.json"


def load() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2) + "\n")
