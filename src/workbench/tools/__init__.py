from __future__ import annotations

from workbench.tools.ai_agent import ClaudeCodeAgent
from workbench.tools.ide import IntelliJIDE, VSCodeIDE
from workbench.tools.pr_viewer import GitHubCLIPR
from workbench.tools.terminal import ITerm2, MacTerminal
from workbench.tools.vcs_client import EmacsMagit, EmacsOpen, LazyGit

REGISTRY = {
    "ai_agent": {
        "claude-code": ClaudeCodeAgent,
    },
    "ide": {
        "intellij": IntelliJIDE,
        "vscode": VSCodeIDE,
    },
    "vcs_client": {
        "emacs-open": EmacsOpen,
        "emacs-magit": EmacsMagit,
        "lazygit": LazyGit,
    },
    "pr_viewer": {
        "github": GitHubCLIPR,
    },
    "terminal": {
        "terminal-app": MacTerminal,
        "iterm2": ITerm2,
    },
}


def create_tools(config: dict) -> dict:
    """Instantiate tools based on config. Returns dict with ai_agent, ide, vcs_client, pr_viewer."""
    tools = {}
    for tool_type, implementations in REGISTRY.items():
        name = config.get(tool_type, "")
        if name not in implementations:
            available = ", ".join(implementations.keys())
            raise ValueError(f"Unknown {tool_type}: '{name}'. Available: {available}")
        tools[tool_type] = implementations[name]()
    return tools
