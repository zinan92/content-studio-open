"""朋友圈（10/18）：/moments 一页——他 X 最新发的，点「复刻到其他平台」原样搬到小红书小号、抖音小号、公众号贴图。
试用版没有这一块。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent

NEEDS: tuple[str, ...] = ()
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    from . import moments as mo

    app.state.moments = mo.Moments()  # 测试换文件夹、换假的 opener 用

    def _call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except mo.MomentsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def m() -> mo.Moments:
        return app.state.moments

    @app.get("/moments")
    def moments_page() -> FileResponse:
        return FileResponse(HERE / "page.html", headers={"Cache-Control": "no-store"})

    @app.get("/moments/{name}")
    def moments_asset(name: str) -> FileResponse:
        if name not in ("page.js", "page.css"):
            raise HTTPException(status_code=404)
        return FileResponse(HERE / name, headers={"Cache-Control": "no-cache"})

    @app.get("/api/moments")
    def moments_view() -> dict:
        return m().view()

    @app.post("/api/moments/check")
    def moments_check() -> dict:
        return m().check()

    @app.post("/api/moments/add")
    def moments_add(body: dict) -> dict:
        return _call(lambda: m().add(str(body.get("url") or "")))

    @app.post("/api/moments/{pid}/replicate")
    def moments_replicate(pid: str) -> dict:
        return _call(lambda: m().replicate(pid))

    @app.get("/api/moments/{pid}/pack")
    def moments_pack(pid: str) -> dict:
        return _call(lambda: m().pack(pid))

    @app.post("/api/moments/{pid}/wechat")
    def moments_wechat(pid: str) -> dict:
        return _call(lambda: m().wechat_draft(pid))

    @app.get("/api/moments/{pid}/img/{name}")
    def moments_image(pid: str, name: str) -> FileResponse:
        match = next((p for p in m().images(pid) if p.name == name), None)
        if match is None:
            raise HTTPException(status_code=404)
        return FileResponse(match, headers={"Cache-Control": "max-age=86400"})
