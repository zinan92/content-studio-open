"""门户：GitHub 和个人网站每天截一次图、判断一次（10/6）。试用版没有这一块。"""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from fastapi.responses import FileResponse


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ()
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    # ---------------- 门户（10/6 作者：GitHub 和网站是常驻的触达面，要经常看一眼它现在长什么样、能不能当好门户） ----------------
    @app.get("/api/portal/{key}")
    def get_portal(key: str, day: str | None = None) -> dict[str, Any]:
        """每天第一次打开时在后台截一次、判断一次；这次先回上一回的，前端看到 running 就过一会儿再问。"""
        from . import portal

        if key not in portal.KEYS:
            raise HTTPException(status_code=404, detail="没有这个门户")
        if day is None:
            portal.start(key)
        return portal.view(key, day)

    @app.post("/api/portal/{key}/refresh")
    def refresh_portal(key: str) -> dict[str, Any]:
        from . import portal

        if key not in portal.KEYS:
            raise HTTPException(status_code=404, detail="没有这个门户")
        if not portal.url_for(key):
            raise ValueError(f"还没填{portal.KEYS[key]}链接：设置 · 通用 · 在哪找到我")
        portal.start(key, force=True)
        return portal.view(key)

    @app.get("/api/portal/{key}/shot/{day}/{variant}.png")
    def portal_shot(key: str, day: str, variant: str) -> FileResponse:
        from . import portal

        path = portal.shot_path(key, day, variant)
        if path is None:
            raise HTTPException(status_code=404, detail="没有这张截图")
        return FileResponse(path, media_type="image/png")
