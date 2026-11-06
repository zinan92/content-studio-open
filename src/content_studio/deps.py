from __future__ import annotations

import os
from pathlib import Path
import sys


CONTENT_DOWNLOADER_ENV = "CONTENT_DOWNLOADER_PATH"
DEFAULT_CONTENT_DOWNLOADER_PATH = Path("~/work/content-downloader")


def content_downloader_path() -> Path | None:
    """Local checkout of content-downloader, used when it is not pip-installed."""
    raw = os.environ.get(CONTENT_DOWNLOADER_ENV)
    path = Path(raw).expanduser() if raw else DEFAULT_CONTENT_DOWNLOADER_PATH.expanduser()
    return path if (path / "content_downloader").is_dir() else None


def ensure_content_downloader() -> None:
    """Make `import content_downloader` work from a sibling checkout if needed."""
    try:
        import content_downloader  # noqa: F401
        return
    except ImportError:
        pass
    path = content_downloader_path()
    if path is not None and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    path = content_downloader_path()
    if path is not None:
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(path), env.get("PYTHONPATH", "")]))
    return env
