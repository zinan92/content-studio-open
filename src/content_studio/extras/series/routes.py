"""系列：起名 + 一行一集标题，建在 Obsidian 原始输出下的新文件夹里（10/5）。系列的同步留在主线（排期要认已有的系列）；试用版只是不能新建。"""
from __future__ import annotations

import re
from typing import Any


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ("_sync_series", "places", "store")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    _raw_root = places.raw_root
    _sync_series = ctx._sync_series
    store = ctx.store

    @app.post("/api/series")
    def create_series(body: dict[str, Any]) -> dict[str, Any]:
        """建系列：起名 + 一行一集标题。写进 Obsidian 003 下的新文件夹，每集进选题池。"""
        from . import series as series_mod

        raw = body.get("titles")
        titles = raw.splitlines() if isinstance(raw, str) else [str(t) for t in (raw or [])]
        titles = [re.sub(r"^\s*(?:\d+\s*[.、)）]|[-*])\s*", "", t) for t in titles]
        try:
            made = series_mod.create(_raw_root(), str(body.get("name") or ""), titles)
        except series_mod.SeriesError as exc:
            raise ValueError(str(exc)) from exc
        store.log_event("pool", f"建了{made['folder']}：{len(made['episodes'])} 集")
        _sync_series()
        return {"series": made}
