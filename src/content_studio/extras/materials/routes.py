"""素材 Agent（10/17）：贴链接或本机文件夹 → 后台学、拆成素材卡 → 作者 挑「留下」→ 推到选题工作台 / 进知识树。
10/20 起它是素材页（/sucai）的「学一个新的」一栏，/materials 跳过去；出图也在素材页，后台用单点功能那条队列。
试用版没有这一块。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse

HERE = Path(__file__).resolve().parent

NEEDS: tuple[str, ...] = ("startup", "places")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    from . import agent as ag

    def vault() -> Path | None:
        try:
            raw = ctx.places.vault_path()
        except Exception:  # noqa: BLE001 —— 没配 vault 就当没有
            return None
        return Path(raw).expanduser() if raw else None

    bot = ag.Agent(vault=vault)
    app.state.material_agent = bot  # 测试换文件夹、换假模型用
    ctx.startup.append(lambda: app.state.material_agent.recover())

    def _call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ag.MaterialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    def a() -> ag.Agent:
        return app.state.material_agent

    @app.get("/materials")
    def materials_page() -> RedirectResponse:
        # 10/20 并进素材页的「学一个新的」；老书签照样能到
        return RedirectResponse("/sucai#learn", status_code=307)

    @app.get("/materials/{name}")
    def materials_asset(name: str) -> FileResponse:
        if name not in ("page.js", "page.css"):
            raise HTTPException(status_code=404)
        return FileResponse(HERE / name, headers={"Cache-Control": "no-cache"})

    @app.get("/materials/media/{sid}/{name}")
    def materials_media(sid: str, name: str) -> FileResponse:
        try:
            path = a().media(sid, name)
        except ag.MaterialError:
            raise HTTPException(status_code=404) from None
        return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/api/material-agent")
    def overview() -> dict[str, Any]:
        return {"jobs": a().jobs()[:20], "sources": a().decks()}

    @app.post("/api/material-agent/learn")
    def learn(body: dict[str, Any]) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            job = a().submit(str(body.get("input") or ""), str(body.get("text") or ""))
            a().start()
            return job
        return _call(go)

    @app.post("/api/material-agent/jobs/{job_id}/retry")
    def retry(job_id: str) -> dict[str, Any]:
        return _call(lambda: a().retry(job_id))

    @app.get("/api/material-agent/sources/{sid}")
    def deck(sid: str) -> dict[str, Any]:
        return _call(lambda: a().deck(sid))

    @app.post("/api/material-agent/sources/{sid}/cards/{name}")
    def mark(sid: str, name: str, body: dict[str, Any]) -> dict[str, Any]:
        return _call(lambda: a().mark(sid, name, str(body.get("status") or "")))

    @app.post("/api/material-agent/sources/{sid}/push")
    def push(sid: str) -> dict[str, Any]:
        return _call(lambda: a().push(sid))

    @app.post("/api/material-agent/sources/{sid}/internalize")
    def internalize(sid: str) -> dict[str, Any]:
        return _call(lambda: a().internalize(sid))

    # -- 素材页（10/18，照选题工作台的「素材」）：素材卡、爆款视频、好网站放一处看，看中了加入选题 ------------
    from . import sucai

    @app.get("/sucai")
    def sucai_page() -> FileResponse:
        return FileResponse(HERE / "sucai.html", headers={"Cache-Control": "no-store"})

    @app.get("/sucai/{name}")
    def sucai_asset(name: str) -> FileResponse:
        if name not in ("sucai.js", "sucai.css", "make.js"):
            raise HTTPException(status_code=404)
        return FileResponse(HERE / name, headers={"Cache-Control": "no-cache"})

    @app.get("/api/sucai")
    def sucai_list(kind: str = "all") -> dict[str, Any]:
        if kind not in ("all", "card", "video", "site"):
            raise HTTPException(status_code=400, detail="没有这一类")
        decks = []
        for d in a().decks():
            try:
                decks.append(a().deck(d["source"]["id"]))
            except ag.MaterialError:
                continue
        return sucai.listing(kind, decks=decks, vault=vault(), site_fetch=app.state.sucai_fetch)

    app.state.sucai_fetch = sucai._fetch  # 测试换成假的，不联网
