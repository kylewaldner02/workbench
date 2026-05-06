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

## Textual TUI Gotchas

### Key Event Flow
- Events go: focused widget → bubble up to Screen. Screen `on_key` fires AFTER widget bindings.
- You CANNOT intercept widget-level keys from a Screen `on_key` handler — the widget processes them first.
- `priority=True` on Screen bindings does NOT reliably prevent widget bindings from also firing.
- To intercept a widget's built-in binding: subclass the widget and override its `action_*` method.
- Overriding `_on_key` (private message handler) on widget subclasses DOES NOT WORK — Textual private handlers don't follow normal MRO.

### Tree Widget
- `tree.select_node(node)` posts `NodeSelected` (same as pressing Enter) — triggers `action_drill_down` which toggles expand/collapse. Use `tree.move_cursor(node)` for cursor-only moves.
- `WorkbenchTree(Tree)` subclass overrides `action_toggle_node` to intercept space — this is the correct pattern for replacing built-in bindings.

### Modal States (e.g., Jumper Mode)
- `check_action()` returning `False` prevents action execution AND greys out footer — use this to disable all Screen bindings during modal states.
- `WrappingFooter` is the visible bottom bar showing keybindings. `#status-bar` is a separate widget above it.
- Override `WrappingFooter._rebuild()` to check screen state and render different content during modal states. Call `_rebuild_footer()` on every state transition.
- `load_data()` runs every 5s and overwrites `#status-bar` — guard with phase checks if using status bar for modal messages.

## Emacs Plugin

The Emacs version lives at `elisp/workbench.el`. Single-file package, installable via straight.el with `:files ("elisp/workbench.el")`. Shares state with the CLI via `~/.workbench/local-state/`. Config is via `defcustom`, not JSON.

## Skills

- `/emacs-engineer` - Emacs Lisp patterns, gotchas, and async patterns for this project. **Use when modifying elisp/workbench.el.**
- `/edit-config` - Edit workbench config (tool selection, adding new tools)
