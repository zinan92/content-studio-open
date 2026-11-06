"""定位：我是谁 · 找到谁 · 卖什么（positioning.md 的待拍板）、对外简介（国内版 / X 版，能推到 X 主页）、我的形象图库。试用版没有这一块。"""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from ... import vault
from ...store import now_iso
from ...web import ProfileBody, StandardBody


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ("places", "store", "x_profile_read_fn", "x_profile_update_fn")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    store = ctx.store
    vault_path = places.vault_path
    x_profile_read_fn = ctx.x_profile_read_fn
    x_profile_update_fn = ctx.x_profile_update_fn

    @app.get("/api/persona")
    def get_persona() -> dict[str, Any]:
        """设置 · 个人形象：定稿形象和配图里存下来的每一张（10/7）。"""
        from . import persona

        return persona.state()

    @app.get("/api/persona/file")
    def persona_file(path: str, thumb: bool = False, v: str = "") -> Response:
        """thumb=1 给页面上的小图；带 v（图的版本）的地址内容不会变，浏览器缓存一年，不带的每次问一下。"""
        from . import persona

        found = persona.thumb(path) if thumb else persona.file(path)
        if found is None:
            raise HTTPException(status_code=404, detail="找不到这张图")
        cache = "private, max-age=31536000, immutable" if v else "no-cache"
        return FileResponse(found, headers={"Cache-Control": cache})

    # -- 定位：我是谁 / 怎么找到客户 / 卖什么 -------------------------------------

    # -- 对外简介：一个文件两段（国内版 / X 版），正本在 Obsidian（profiles.py） --------

    def _profile_view() -> dict[str, Any]:
        from . import profiles
        from ... import reach

        prof = profiles.read(vault.vault_root(vault_path()))
        accounts = store.settings()["platform_accounts"] or {}
        on = {key: (bool((accounts.get(key) or {}).get("on")) if key in accounts else False) for key, *_ in profiles.PLATFORMS}
        on["douyin"] = True
        applied = {k: v for k, v in (store.settings().get("profiles") or {}).items() if isinstance(v, dict) and v.get("at")}
        return {"profile": prof, "platforms": profiles.platforms(prof, applied, on, reach.CORE),
                "variants": [{"key": k, "label": label, "limits": profiles.LIMITS[k]} for k, label in profiles.VARIANTS]}

    def _mark_applied(platform: str) -> None:
        from . import profiles

        spec = next((p for p in profiles.PLATFORMS if p[0] == platform), None)
        if spec is None:
            raise ValueError("没有这个平台")
        now = profiles.read(vault.vault_root(vault_path()))["variants"][spec[2]]
        if not now["name"] and not now["bio"]:
            raise ValueError("这一版还是空的")
        saved = dict(store.settings().get("profiles") or {})
        saved[platform] = {"name": now["name"], "bio": now["bio"], "at": now_iso()}
        store.update_settings({"profiles": saved})

    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        return _profile_view()

    @app.put("/api/profile/{variant}")
    def put_profile(variant: str, body: ProfileBody) -> dict[str, Any]:
        from . import profiles

        try:
            profiles.write(vault.vault_root(vault_path()), variant, name=body.name or "", bio=body.bio or "", mtime=body.mtime)
        except profiles.ProfileError as exc:
            raise ValueError(str(exc)) from None
        store.log_event("profile", f"对外简介（{dict(profiles.VARIANTS)[variant]}）改了")
        return _profile_view()

    @app.post("/api/profile/applied/{platform}")
    def profile_applied(platform: str) -> dict[str, Any]:
        """他已经把这一版贴到这个平台上了：记下哪天、哪一版。"""
        _mark_applied(platform)
        return _profile_view()

    @app.get("/api/profile/x/live")
    def x_profile_live() -> dict[str, Any]:
        """X 上现在的名字和简介（只读）。"""
        from . import x_profile
        from ...x_post import XError

        try:
            return {"live": (x_profile_read_fn or x_profile.read)()}
        except XError as exc:
            raise ValueError(str(exc)) from None

    @app.post("/api/profile/x/push")
    def x_profile_push() -> dict[str, Any]:
        """把 X 版改到 X 上。改的是他公开的主页：只有他点了按钮（点两次）才调。"""
        from . import profiles, x_profile
        from ...x_post import XError

        now = profiles.read(vault.vault_root(vault_path()))["variants"]["x"]
        if not now["name"] and not now["bio"]:
            raise ValueError("X 版还是空的")
        try:
            live = (x_profile_update_fn or x_profile.update)(name=now["name"], bio=now["bio"])
        except XError as exc:
            raise ValueError(str(exc)) from None
        _mark_applied("x")
        store.log_event("profile", "X 的主页改好了：" + now["bio"][:60])
        return {**_profile_view(), "live": live}

    @app.get("/api/positioning")
    def get_positioning() -> dict[str, Any]:
        from . import positioning

        return positioning.read()

    @app.post("/api/positioning")
    def post_positioning(body: StandardBody) -> dict[str, Any]:
        """Append one proposal to 「待拍板」. Anna wrote the sentence; 作者 clicked the
        button that shows it. His own text above the block is never touched."""
        from . import positioning

        item = positioning.add_proposal(body.text, source=body.source)
        return {"proposal": item, "proposals": positioning.proposals()}

    @app.delete("/api/positioning/{proposal_id}")
    def delete_positioning(proposal_id: str) -> dict[str, Any]:
        from . import positioning

        if not positioning.remove_proposal(proposal_id):
            raise ValueError("这一条已经不在待拍板里了")
        return {"proposals": positioning.proposals()}
