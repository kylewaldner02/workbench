# Workbench

CLI worktree manager with integrated launchers for Claude Code, IntelliJ, and Emacs Magit.

## Prerequisites

- Python 3.10+
- Git
- GitHub CLI (`gh`) — for PR integration

## Setup

```bash
git clone git@github.com:kylewaldner02/workbench.git
cd workbench
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

From inside any git repository:

```bash
workbench
```

### Keybindings

| Key | Action |
|-----|--------|
| `c` | Open Claude Code in selected worktree |
| `i` | Open IDE in selected worktree |
| `g` | Open git client in selected worktree |
| `p` | Open PR in browser, or create one |
| `n` | Create a new worktree |
| `x` | Remove selected worktree |
| `Enter` | View Claude Code sessions |
| `r` | Refresh |
| `q` | Quit |
