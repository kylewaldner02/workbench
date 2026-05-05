from __future__ import annotations

import typer

app = typer.Typer(help="CLI worktree manager with integrated tool launchers")


@app.command()
def main() -> None:
    """Launch the workbench TUI dashboard."""
    from workbench.tui import WorkbenchApp

    wb = WorkbenchApp()
    wb.run()


if __name__ == "__main__":
    app()
