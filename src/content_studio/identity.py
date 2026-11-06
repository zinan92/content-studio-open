"""Who the workbench is working for, as the prompts need it.

Read once from profile.yaml (`me.name`, `me.platforms`). Prompts say「作者是 ___」and
「他的号是「___」」with these; with an empty profile they fall back to neutral wording
instead of a stranger's name.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class Author:
    name: str
    channel: str

    @property
    def channel_phrase(self) -> str:
        return f"他的号是「{self.channel}」，" if self.channel else ""


@lru_cache(maxsize=1)
def author() -> Author:
    from . import profile

    try:
        data: dict[str, Any] = profile.load()
    except Exception:
        data = {}
    me = data.get("me") or {}
    name = str(me.get("name") or "").strip() or "作者"
    platforms = me.get("platforms") or {}
    channel = ""
    if isinstance(platforms, dict):
        channel = next((str(v).strip() for v in platforms.values() if str(v or "").strip()), "")
    return Author(name=name, channel=channel)


def reset() -> None:
    """For tests and for `serve` after profile.yaml changes."""
    author.cache_clear()
