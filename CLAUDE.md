# Workbench

A CLI worktree manager with integrated tool launchers for Claude Code, IDEs, and VCS clients. Built with Python 3.10+, Textual (TUI), and Typer (CLI).

## Project Structure

```
src/workbench/
  cli.py          - CLI entry point (Typer)
  tui.py          - Main TUI app (Textual)
  state.py        - State & config management (~/.workbench/)
  status.py       - Git status helpers
  worktree.py     - Git worktree operations
  tools/
    __init__.py   - Tool registry (REGISTRY dict) & create_tools()
    base.py       - Protocol definitions (AIAgent, IDE, VCSClient, PRViewer)
    ai_agent.py   - ClaudeCodeAgent
    ide.py        - IntelliJIDE, VSCodeIDE
    vcs_client.py - EmacsOpen, EmacsMagit, LazyGit
    pr_viewer.py  - GitHubCLIPR
```

## Config

Config lives at `~/.workbench/config.json`. Tool selection is config-driven via `REGISTRY` in `tools/__init__.py`. The registry maps config keys to concrete tool classes implementing the protocols in `tools/base.py`.

## Skills

- `/edit-config` - Edit workbench config (tool selection, adding new tools)
