"""Where the workbench keeps its own files on this machine.

Everything lives under one directory (SQLite, reports, drafts, cookies, run logs) so a
person can back it up, wipe it, or point a second checkout somewhere else with one
environment variable. Nothing here goes into the repository.
"""
from __future__ import annotations

import os
from pathlib import Path

HOME_ENV = "CONTENT_STUDIO_HOME"
DEFAULT_HOME = "~/.config/content-studio"


def config_dir() -> Path:
    """`$CONTENT_STUDIO_HOME`, else `~/.config/content-studio`. Expanded, not created."""
    return Path(os.environ.get(HOME_ENV) or DEFAULT_HOME).expanduser()
