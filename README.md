# Workbench

A worktree manager with integrated tool launchers for Claude Code, IDEs, and VCS clients.

## Emacs Plugin (Recommended)

The Emacs plugin (`elisp/workbench.el`) is the full-featured version of Workbench. It provides:

- **Project organization** — group worktrees into projects, archive/unarchive projects
- **Claude Code session management** — list, resume, fork, and create new sessions per worktree
- **Multi-repo support** — manage worktrees across multiple repositories
- **Tool launchers** — open Claude Code, IDE (IntelliJ/VS Code), git client (Magit/LazyGit), terminal, and PRs
- **Reordering** — reorder projects, worktrees, and sessions with `[` / `]`
- **Async refresh** — non-blocking background data fetching with incremental session loading
- **PR integration** — view and create PRs via GitHub CLI
- **Transient menu** — `?` for a discoverable command menu
- **Fully customizable** — override any launcher function, strip branch prefixes, configure refresh interval

### Install

Requires Emacs 28.1+ and `transient`. With [straight.el](https://github.com/raxod502/straight.el):

```elisp
(use-package workbench
  :straight (:host github :repo "kylewaldner02/workbench"
             :files ("elisp/workbench.el")))
```

Then run `M-x workbench`.

### Keybindings

| Key | Action |
|-----|--------|
| `c` | Open Claude Code |
| `o` | New Claude session |
| `s` | Resume Claude session |
| `f` | Fork Claude session |
| `i` | Open IDE |
| `g` | Open git client |
| `t` | Open terminal |
| `p` | Open/create PR |
| `n` | New worktree |
| `x` | Remove worktree |
| `P` | New project |
| `R` | Add repo |
| `a` | Assign worktree to project |
| `A` | Archive project |
| `d` | View archived projects |
| `[`/`]` | Reorder items |
| `RET`/`TAB` | Toggle fold |
| `r` | Refresh |
| `?` | Command menu |
| `q` | Quit |

## Python CLI (Prototype)

The Python CLI (`workbench` command) was the original prototype. It provides basic worktree management and tool launching via a Textual TUI, but is no longer the primary interface.

### Prerequisites

- Python 3.10+
- Git
- GitHub CLI (`gh`) — for PR integration

### Install

```bash
git clone git@github.com:kylewaldner02/workbench.git
cd workbench
pipx install .
```

### Usage

```bash
workbench
```

### Development

For local development with live code reloading:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```
