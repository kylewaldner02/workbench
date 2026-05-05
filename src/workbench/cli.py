from __future__ import annotations

import os
from pathlib import Path

import typer

app = typer.Typer(help="CLI worktree manager with integrated tool launchers")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch the workbench TUI dashboard."""
    if ctx.invoked_subcommand is None:
        from workbench.tui import WorkbenchApp

        wb = WorkbenchApp()
        wb.run()

        # If the TUI set a command to exec into, do it
        if wb.exec_cmd:
            os.chdir(wb.exec_cwd or ".")
            os.execvp(wb.exec_cmd[0], wb.exec_cmd)


@app.command("add-repo")
def add_repo(path: str = typer.Argument(".", help="Path to git repo")) -> None:
    """Register a git repo with workbench."""
    from workbench.state import add_repo as _add_repo

    resolved = str(Path(path).resolve())
    _add_repo(resolved)
    typer.echo(f"Added repo: {resolved}")


@app.command()
def repos() -> None:
    """List known repos."""
    from workbench.state import load_repos

    for repo in load_repos():
        typer.echo(repo)


@app.command()
def projects() -> None:
    """List projects."""
    from workbench.state import load_projects

    for p in load_projects():
        wt_count = len(p.worktrees)
        typer.echo(f"{p.name} ({wt_count} worktrees)")


if __name__ == "__main__":
    app()
