# Edit Workbench Config

You are editing the configuration for Workbench, a CLI worktree manager.

## Config Location

`~/.workbench/config.json`

## How Config Works

1. Config is loaded by `src/workbench/state.py` (`load_config()`, `save_config()`, `ensure_config()`)
2. Each config key maps to a tool category in the `REGISTRY` dict in `src/workbench/tools/__init__.py`
3. The registry maps string values to concrete classes implementing protocols from `src/workbench/tools/base.py`
4. Tools are instantiated once at startup via `create_tools(config)`

## Current Config Options

Read `~/.workbench/config.json` first to see current values, then refer to this reference:

| Key | Available Values | Implementation |
|-----|-----------------|----------------|
| `ide` | `intellij`, `vscode` | `tools/ide.py` |
| `vcs_client` | `emacs-open`, `emacs-magit`, `lazygit` | `tools/vcs_client.py` |
| `ai_agent` | `claude-code` | `tools/ai_agent.py` |
| `pr_viewer` | `github` | `tools/pr_viewer.py` |

## IMPORTANT: Discovering Current Options

The table above may be stale. **Always verify by reading these two files:**

1. `src/workbench/tools/__init__.py` - the `REGISTRY` dict is the source of truth for all available config values
2. `src/workbench/tools/base.py` - the Protocol definitions show what methods each tool type must implement

## Adding a New Tool

To add a new tool implementation:

1. Read the relevant Protocol in `tools/base.py` to understand the required interface
2. Add the implementation class to the appropriate file in `tools/` (or create a new file)
3. Import and register it in `tools/__init__.py` under the correct category in `REGISTRY`
4. Update `~/.workbench/config.json` to use it

## What to Do

1. Read `~/.workbench/config.json` to show current config
2. Read `src/workbench/tools/__init__.py` to show available options from `REGISTRY`
3. Ask the user what they want to change
4. Make the changes (edit config JSON and/or add new tool implementations)
