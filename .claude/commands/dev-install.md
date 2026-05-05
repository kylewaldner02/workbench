Install and run workbench from a worktree in development mode with live reloading.

Tell the user to run these commands in a separate terminal:

```
cd <worktree-path>
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/workbench
```

Notes:
- Requires Python 3.10+ (use `python3.12` from Homebrew if system Python is too old)
- Editable install (`-e .`) means code changes take effect immediately without reinstalling
- The `.venv` directory is gitignored
- If pip complains about editable mode, upgrade pip first: `.venv/bin/pip install --upgrade pip`
