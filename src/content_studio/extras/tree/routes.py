"""知识树（10/18）：/tree 一页——上面「内化」（贴 X / GitHub / 网页链接或粘正文），下面是 ~/work/park-knowledge 这棵树本身。
试用版没有这一块。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent

NEEDS: tuple[str, ...] = ("startup",)
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    from . import tree as tr

    app.state.tree_jobs = tr.Jobs()  # 测试换文件夹、换假的 runner 用
    ctx.startup.append(lambda: app.state.tree_jobs.recover())

    def _call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except tr.TreeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def jobs() -> tr.Jobs:
        return app.state.tree_jobs

    @app.get("/tree")
    def tree_page() -> FileResponse:
        return FileResponse(HERE / "page.html", headers={"Cache-Control": "no-store"})

    @app.get("/tree/{name}")
    def tree_asset(name: str) -> FileResponse:
        if name not in ("page.js", "page.css"):
            raise HTTPException(status_code=404)
        return FileResponse(HERE / name, headers={"Cache-Control": "no-cache"})

    @app.get("/api/tree")
    def tree_view() -> dict:
        out = tr.tree(jobs().knowledge())
        out["jobs"] = [{k: v for k, v in j.items() if k != "text"} for j in jobs().list()[:12]]
        return out

    @app.post("/api/tree/internalize")
    def tree_internalize(body: dict) -> dict:
        return _call(lambda: jobs().submit(str(body.get("input") or ""), str(body.get("text") or "")))

    @app.post("/api/tree/jobs/{jid}/retry")
    def tree_retry(jid: str) -> dict:
        return _call(lambda: jobs().retry(jid))
