# Workbench — CLI Worktree Manager

A Python + shell CLI tool for managing git worktrees with integrated launchers for Claude Code, IntelliJ, and Emacs Magit.

## Background

**Problem:** Claude Conductor uses git worktrees to run multiple Claude Code agents in parallel on the same repo — each agent gets its own worktree so they don't conflict. But there's no standalone CLI to manage worktrees with integrated tooling launchers.

**Goal:** Build a CLI alternative that gives a live dashboard of all worktrees, with shortcuts to open Claude Code, IntelliJ, or Emacs Magit in any of them.

**Decisions made:**
- **Python + shell over Go/Rust** — no compilation step, fast iteration, already known. Go (bubbletea) and Rust (ratatui) were considered but rejected for simplicity.
- **textual over tmux** — tmux is a terminal multiplexer that could host each worktree session in its own pane/window, but it constrains the UI to tmux layout primitives and forces a tmux dependency. textual (Python TUI framework) gives a rich interactive dashboard with custom keybindings, tables, and colors — all in a single terminal, no tmux required.

## Tech Stack

- **Python** (textual for TUI, click/typer for CLI)
- **Shell** (git worktree commands, process detection)

## UX

One command (`workbench`) pulls up a status dashboard showing all open worktrees with shortcuts to act on them:

```
┌──────────────────────────────────────────────────────────────────┐
│  workbench                                         3 worktrees   │
├──┬──────────────┬────────┬──────────┬─────────┬─────────────────┤
│  │ Branch       │ Status │ Claude   │ PR      │ Last Commit     │
├──┼──────────────┼────────┼──────────┼─────────┼─────────────────┤
│▶ │ fix/billing  │ 3M 1A  │ ● active │ #142    │ 2m ago          │
│  │ feat/dag     │ clean  │ ○ idle   │ —       │ 15m ago         │
│  │ refactor/api │ 1M     │ ● active │ #138    │ 8m ago          │
├──┴──────────────┴────────┴──────────┴─────────┴─────────────────┤
│ [c]laude  [i]de  [g]it  [p]r  [x]close  [n]ew  [Enter]sessions │
└──────────────────────────────────────────────────────────────────┘
```

### Interactions — Worktree List (main view)

- Arrow keys to select a worktree
- `Enter` — drill into Claude Code sessions for this worktree
- `c` — open a new Claude Code session in selected worktree
- `i` — open IDE in selected worktree
- `g` — open git client (version control) in selected worktree
- `p` — open PR in browser, or create one if none exists
- `x` — close/remove selected worktree
- `n` — create a new worktree (prompts for branch name)

### Interactions — Session List (drill-down view)

Pressing `Enter` on a worktree shows all Claude Code conversations associated with it:

```
┌─────────────────────────────────────────────────────────────┐
│  workbench > fix/billing                       2 sessions   │
├──┬──────────────────────────┬──────────┬────────────────────┤
│  │ Session                  │ Status   │ Last Active        │
├──┼──────────────────────────┼──────────┼────────────────────┤
│▶ │ debug proration logic    │ ● active │ now                │
│  │ add billing retry tests  │ ○ idle   │ 22m ago            │
├──┴──────────────────────────┴──────────┴────────────────────┤
│ [r]esume  [f]ork  [c]new  [backspace]back                   │
└─────────────────────────────────────────────────────────────┘
```

- `r` — resume the selected session (`claude --resume <session-id>`)
- `f` — fork the selected session (resume then diverge)
- `c` — start a brand new Claude Code session in this worktree
- `Backspace` — back to worktree list

### Status Columns

- **Branch**: branch name
- **Status**: `git status --porcelain` summary (e.g. `3M 1A`, `clean`)
- **Claude**: whether a `claude` process is running in that worktree's cwd
- **PR**: PR number if one exists for the branch (`#142`), or `—` if none
- **Last Commit**: relative time of last commit on the branch

## Architecture

```
workbench/
├── cli.py              # click/typer entry point
├── worktree.py         # git worktree add/remove/list (subprocess calls)
├── status.py           # git status + process detection per worktree
├── sessions.py         # discover/parse Claude Code sessions per worktree
├── github.py           # GitHub CLI integration (PR lookup, creation, open in browser)
├── tools/
│   ├── __init__.py
│   ├── base.py         # abstract tool provider interfaces (Protocol classes)
│   ├── ai_agent.py     # AIAgent protocol + ClaudeCodeAgent implementation
│   ├── ide.py          # IDE protocol + IntelliJIDE implementation
│   ├── vcs_client.py   # VCSClient protocol + EmacsMagit implementation
│   └── pr_viewer.py    # PRViewer protocol + GitHubCLI implementation
├── tui.py              # textual app (the status dashboard)
└── state.py            # ~/.workbench/state.json tracking
```

## Core Components

### worktree.py — Git Worktree Management

Wraps `git worktree` commands via `subprocess.run`:

- `create_worktree(branch_name)` — `git worktree add .worktrees/<branch> -b <branch>`
- `remove_worktree(branch_name)` — `git worktree remove .worktrees/<branch>`
- `list_worktrees()` — `git worktree list --porcelain`, parsed into structured data

### status.py — Status Detection

- `get_git_status(worktree_path)` — runs `git status --porcelain` in the worktree, summarizes changes
- `is_claude_active(worktree_path)` — checks for a `claude` process with cwd matching the worktree
- `get_last_commit_time(worktree_path)` — `git log -1 --format=%cr` in the worktree

### tools/ — Tool Provider Abstraction

External tools are accessed through Python `Protocol` classes. The TUI and CLI only depend on the protocol — concrete implementations are swappable.

#### base.py — Protocol Definitions

```python
class AIAgent(Protocol):
    """An AI coding agent (Claude Code, Cursor, Aider, etc.)"""
    def open(self, worktree_path: Path) -> None: ...
    def resume(self, worktree_path: Path, session_id: str) -> None: ...
    def is_active(self, worktree_path: Path) -> bool: ...
    def list_sessions(self, worktree_path: Path) -> list[Session]: ...

class IDE(Protocol):
    """An IDE or editor (IntelliJ, VS Code, Neovim, etc.)"""
    def open(self, worktree_path: Path) -> None: ...

class VCSClient(Protocol):
    """A git UI client (Emacs Magit, lazygit, GitKraken, etc.)"""
    def open(self, worktree_path: Path) -> None: ...

class PRViewer(Protocol):
    """PR management (GitHub CLI, GitLab CLI, etc.)"""
    def get_pr(self, branch: str) -> PR | None: ...
    def create_pr(self, branch: str, base: str) -> PR: ...
    def open_in_browser(self, branch: str) -> None: ...
```

#### v1 Implementations

| Protocol | v1 Implementation | Backed by |
|---|---|---|
| `AIAgent` | `ClaudeCodeAgent` | `claude` CLI + `~/.claude/projects/` session files |
| `IDE` | `IntelliJIDE` | `idea` CLI launcher |
| `VCSClient` | `EmacsMagit` | `emacsclient -e (magit-status ...)` |
| `PRViewer` | `GitHubCLIPR` | `gh pr view`, `gh pr create`, `gh pr view --web` |

To swap tools, provide a different implementation — e.g. `VSCodeIDE`, `LazyGitVCS`, `CursorAgent`. The TUI doesn't change.

### github.py — GitHub CLI Integration

Wraps `gh` (GitHub CLI) commands:

- `get_pr_for_branch(branch)` — `gh pr view <branch> --json number,url,state` → returns PR info or `None`
- `create_pr(branch, base="main")` — `gh pr create --head <branch> --base <base>` (interactive, opens editor for title/body)
- `open_pr_in_browser(branch)` — `gh pr view <branch> --web`
- `list_prs()` — `gh pr list --json number,headRefName` → used to batch-populate the PR column on startup

### sessions.py — Claude Code Session Discovery

Claude Code stores conversation state in `~/.claude/projects/<project-path>/` as JSONL files. This module maps sessions to worktrees:

- `list_sessions(worktree_path)` — scan `~/.claude/projects/` for session files matching the worktree's absolute path, return structured session metadata
- `get_session_label(session_path)` — extract the first user message from the JSONL as a human-readable session name
- `get_session_status(session_id)` — check if a `claude --resume <id>` process is currently running
- `get_last_active(session_path)` — timestamp of the last entry in the JSONL

### tui.py — Textual Dashboard

Two screens:

1. **Worktree list** (main) — `DataTable` showing worktree info with keybinding handlers
2. **Session list** (drill-down) — `DataTable` showing Claude Code sessions for a selected worktree, with resume/fork/new keybindings

- Timer-based refresh (poll every few seconds)

### state.py — Persistent State

- `~/.workbench/state.json` — tracks created worktrees, preferences
- Survives across sessions

## Why textual over tmux

| | textual | tmux |
|---|---|---|
| Single status view with shortcuts | Native — it's a widget | Hacky — script a status pane that redraws |
| Launch Claude/IntelliJ/magit | `subprocess.run` or `os.system` | Same, but from within tmux send-keys |
| Requires tmux | No | Yes |
| Custom keybindings | Built-in | Possible but fragile |
| Rich formatting | Tables, colors, borders | Limited to shell escape codes |

## Estimated Scope

~600-900 lines of Python for v1. The core is:
1. ~4 functions in `worktree.py` wrapping git commands
2. Protocol definitions + 4 concrete implementations in `tools/`
3. GitHub CLI wrapper in `github.py`
4. Session discovery in `sessions.py`
5. Two textual screens (worktree list + session drill-down) in `tui.py`

## Future Ideas

- Auto-detect existing worktrees on startup
- Claude session output streaming in a split pane
- Branch creation from Linear ticket
- Worktree templates (pre-configured with specific gradle modules)
- Session search/filter (find a past conversation by keyword)
- Session diff view (show what files a session changed)
