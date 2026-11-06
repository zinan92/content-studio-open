"""设置 · 开始用三步、设置页、Skills 清单、在哪找到我、检查更新、诊断包；页面一打开先读的 /api/state 也在这。"""
from __future__ import annotations

import json
import os
from typing import Any
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pathlib import Path
from ...accounts import add_account
from ... import copypack, edition, vault
from ...accounts import AccountError
from ...creator_metrics import CookieFileError, load_cookie_file
from ...paths import config_dir
from ...web import SettingsBody, SkillBody, _creator_rows, vault_status


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = ("cookie_path", "creator_db", "drafts_root", "feature_on", "ops", "places", "profile", "store")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    cookie_path = ctx.cookie_path
    creator_db = ctx.creator_db
    drafts_root = ctx.drafts_root
    ops = ctx.ops
    places = ctx.places
    profile = ctx.profile
    store = ctx.store
    video_root = places.video_root

    def _cookie_message(exc: Exception) -> str:
        """抖音登录信息哪里不对，说人话（原来直接把英文异常和文件路径打在横幅上）。"""
        text = str(exc)
        if "does not exist" in text:
            return "还没导入抖音登录信息"
        if "must be private" in text:
            return "登录信息文件的权限不对（得只有你能读）：在「开始用」里重新导入一次就好"
        if "not valid JSON" in text:
            return "登录信息文件不是合法的 JSON：重新导出、再导入"
        if "no usable cookies" in text:
            return "登录信息文件里没有可用的 cookies：重新导出、再导入"
        return text
    def _setup_state() -> dict[str, Any]:
        from ... import profile as profile_mod

        # 启动时没有 profile 的，「开始用」第一步会在用户配置目录新建一份：每次都看一眼文件，不用重启
        own = config_dir() / "profile.yaml"
        data = profile if profile is not None else (profile_mod.load(own) if own.is_file() else {})
        if not data:
            return {"present": False, "ok": False, "missing_required": [], "missing_optional": [],
                    "hint": "还没填：你是谁、抖音主页链接、素材在哪"}
        out = profile_mod.summary(profile_mod.check(data))
        out["present"] = True
        out["path"] = data.get("_path")
        return out
    @app.post("/api/setup/profile")
    def setup_profile(body: dict[str, Any]) -> dict[str, Any]:
        """第一步：你是谁。写进 profile.yaml（启动时没有的，新建在用户配置目录），抖音主页顺手登记成自己的号。"""
        from ... import conf
        from ... import profile as profile_mod

        changes: dict[str, Any] = {}
        name = str(body.get("name") or "").strip()
        brand_name = str(body.get("brand") or "").strip()
        douyin = str(body.get("douyin") or "").strip()
        editor = str(body.get("editor") or "").strip()[:20]
        boss = str(body.get("boss") or "").strip()[:20]
        if name:
            changes.setdefault("me", {})["name"] = name[:40]
        if douyin:
            if not profile_mod.DOUYIN_USER.search(douyin):
                raise ValueError("抖音主页链接形如 https://www.douyin.com/user/MS4wLjAB…（抖音 App 里「分享主页 → 复制链接」）")
            changes.setdefault("me", {})["douyin"] = douyin
        if brand_name:
            changes.setdefault("brand", {})["name"] = brand_name[:24]
        if editor:
            changes.setdefault("brand", {})["editor"] = editor
        if boss:
            changes.setdefault("brand", {})["boss"] = boss
        if not changes:
            raise ValueError("先填一项")
        changes.setdefault("ai", {}).setdefault("backend", "claude-cli")  # 目前只有这一种，替他填上
        target = profile_mod.setup_path() if profile is not None else config_dir() / "profile.yaml"
        path = profile_mod.save(changes, target)
        if profile is not None:
            fresh = profile_mod.load(path)
            profile.clear()
            profile.update(fresh)
        if douyin and store.self_account() is None:
            try:
                add_account(store, douyin, is_self=True)
            except AccountError as exc:
                raise ValueError(f"抖音主页没登记上：{exc}") from exc
        store.log_event("setup", "开始用：填了你是谁")
        return {"ok": True, "path": str(path), "setup": _setup_state(), "brand": conf.brand(profile)}
    @app.post("/api/setup/cookies")
    def setup_cookies(body: dict[str, Any]) -> dict[str, Any]:
        """第二步：连上抖音。浏览器扩展导出的 cookies（JSON）贴进来，工作台存成它要的文件、权限设好。"""
        text = str(body.get("text") or "").strip()
        if not text:
            raise ValueError("选一下导出的 cookies 文件")
        try:
            raw = json.loads(text)
        except ValueError:
            raise ValueError("这不是 JSON 文件：用 Cookie-Editor 这类扩展导出 JSON 格式") from None
        if isinstance(raw, list):
            keep = [{"name": str(i.get("name")).strip(), "value": str(i.get("value")).strip(), "domain": str(i.get("domain") or ".douyin.com")}
                    for i in raw if isinstance(i, dict) and i.get("name") and i.get("value")]
        elif isinstance(raw, dict):
            keep = [{"name": str(k).strip(), "value": str(v).strip(), "domain": ".douyin.com"} for k, v in raw.items() if k and v]
        else:
            keep = []
        if not keep:
            raise ValueError("文件里没有 cookies：确认是在登录了 douyin.com 的浏览器里导出的")
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cookie_path.with_name(f".{cookie_path.name}.{os.getpid()}")
        tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, cookie_path)
        try:
            load_cookie_file(cookie_path)
        except CookieFileError as exc:
            raise ValueError(_cookie_message(exc)) from exc
        store.log_event("setup", f"导入了抖音登录信息（{len(keep)} 条）")
        return {"ok": True, "count": len(keep)}
    # ---- 10/20 作者：抖音连不上了，在工作台里提示他重新连。点一下开一个工作台自己的 Chrome 窗口（不碰他平时用的那个），
    # 他扫码登好，这里把 douyin.com 的登录信息存成和「导入」一样的文件。不绕验证码：扫码、过验证都是他自己在窗口里做。
    import threading
    import time

    douyin_login: dict[str, Any] = {"state": "idle", "message": ""}
    douyin_login_lock = threading.Lock()

    def _save_douyin_cookies(items: list[dict[str, Any]]) -> int:
        keep = [{"name": str(c["name"]), "value": str(c["value"]), "domain": str(c.get("domain") or ".douyin.com")}
                for c in items if c.get("name") and c.get("value") and "douyin.com" in str(c.get("domain") or "")]
        if not keep:
            raise ValueError("窗口里没拿到抖音的登录信息")
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cookie_path.with_name(f".{cookie_path.name}.{os.getpid()}")
        tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, cookie_path)
        return len(keep)

    def _douyin_login_run() -> None:
        from ... import douyin_browser as db

        def say(state: str, message: str) -> None:
            with douyin_login_lock:
                douyin_login.update(state=state, message=message)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            say("failed", f"这台电脑没装登录用的浏览器组件：{db.INSTALL_HINT}")
            return
        try:
            with db._LOCK, sync_playwright() as pw:  # 和后台读作品用同一个 Chrome 配置：一次只开一个
                args = {**db.LAUNCH_ARGS, "headless": False}
                try:
                    ctx_ = pw.chromium.launch_persistent_context(str(config_dir() / db.PROFILE_DIRNAME), channel="chrome", **args)
                except Exception:  # noqa: BLE001 — 没装 Google Chrome 就用自带 Chromium
                    ctx_ = pw.chromium.launch_persistent_context(str(config_dir() / db.CHROMIUM_PROFILE_DIRNAME), **args)
                page = ctx_.pages[0] if ctx_.pages else ctx_.new_page()
                page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
                say("running", "窗口开了：在里面用抖音 App 扫码登录，登好了这里会自己接上")
                deadline = time.time() + 300
                while time.time() < deadline:
                    try:
                        items = ctx_.cookies(["https://www.douyin.com", "https://creator.douyin.com"])
                    except Exception:  # noqa: BLE001 — 他把窗口关了
                        say("failed", "登录窗口关了，还没登上。再点一次「重新登录抖音」")
                        return
                    names = {c.get("name") for c in items}
                    if names & {"sessionid", "sessionid_ss"}:
                        time.sleep(3)  # 登上以后页面还会补几条 cookie
                        n = _save_douyin_cookies(ctx_.cookies(["https://www.douyin.com", "https://creator.douyin.com"]))
                        ctx_.close()
                        store.log_event("setup", f"在工作台里重新登录了抖音（{n} 条登录信息）")
                        say("ok", "抖音登好了，正在重新读你的作品")
                        return
                    time.sleep(2)
                ctx_.close()
                say("failed", "5 分钟没登好，窗口关了。再点一次「重新登录抖音」")
        except Exception as exc:  # noqa: BLE001
            say("failed", f"登录窗口没打开：{str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__}")

    @app.post("/api/douyin/login")
    def douyin_login_start() -> dict[str, Any]:
        with douyin_login_lock:
            if douyin_login["state"] == "running":
                return dict(douyin_login)
            douyin_login.update(state="running", message="正在打开登录窗口…")
        threading.Thread(target=_douyin_login_run, name="douyin-login", daemon=True).start()
        return dict(douyin_login)

    @app.get("/api/douyin/login")
    def douyin_login_state() -> dict[str, Any]:
        with douyin_login_lock:
            return dict(douyin_login)

    @app.get("/api/update")
    def get_update(fetch: bool = True) -> dict[str, Any]:
        from ... import updater

        try:
            return updater.status(fetch=fetch)
        except updater.UpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    @app.post("/api/update")
    def post_update() -> dict[str, Any]:
        from ... import updater

        try:
            return updater.apply()
        except updater.UpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    @app.post("/api/diagnostics")
    def post_diagnostics(request: Request) -> Response:
        from ...diagnostics import build_bundle

        filename, data = build_bundle(port=(request.scope.get("server") or ("localhost", 8780))[1])
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store",
        })
    @app.get("/api/brand/logo")
    def brand_logo() -> Response:
        """profile.yaml 里 brand.logo 指的 SVG；没配就 404，前端保留对勾。"""
        from ... import conf

        logo = conf.brand()["logo"]
        path = Path(logo).expanduser() if logo else None
        if not path or not path.is_file() or path.suffix.lower() != ".svg":
            raise HTTPException(status_code=404, detail="没有配置 logo")
        return FileResponse(path, media_type="image/svg+xml")
    @app.get("/api/state")
    def state() -> dict[str, Any]:
        try:
            load_cookie_file(cookie_path)
            cookies = {"ok": True, "message": None}
        except CookieFileError as exc:
            cookies = {"ok": False, "message": _cookie_message(exc)}
        jobs = store.jobs(500)
        from ... import conf

        b = conf.brand(profile)
        return {
            "brand": {**b, "logo": "/api/brand/logo" if b["logo"] else ""},
            # 试用版砍了哪些、用户在「设置 · 流程」里关了哪些（edition.py）：前端照这个藏入口
            "edition": edition.view(profile, store.settings().get("components_off") or []),
            "settings": store.settings(),
            # 设置 ·「各平台常用话题」一行一个平台（10/8：只在设置里改，平台页、打包页只显示）
            "tag_platforms": [{"key": k, "label": copypack.PLATFORMS[k]["label"], "cap": copypack.PLATFORMS[k]["tags"]}
                              for k in copypack.TAG_PLATFORMS],
            "self_account": store.self_account(),
            "my_accounts": [
                {k: a[k] for k in ("id", "platform", "nickname", "profile_url", "follower_count")} for a in store.my_accounts()
            ],
            "setup": _setup_state(),
            # 进项的日报 tab 跟 profile.yaml 的 dailies 走：拿掉一份日报只改配置，不改页面
            "daily_sources": [{"key": s.key, "label": s.label} for s in vault.DAILY_SOURCES] if ctx.feature_on("dailies") else [],
            # 页面上提到「存进哪个文件夹」用这个名字，不写死 作者 的目录名
            "vault_folders": {s.key: s.folder for s in vault.INBOX_SOURCES},
            "vault": vault_status(store.settings()["obsidian_vault"]),
            "cookies": cookies,
            "creator_metrics_available": bool(_creator_rows(creator_db)),
            "full_sync_running": ops.full_sync_running,
            "benchmarks_running": ops.benchmarks_running,
            "last_full_sync": ops.last_full_sync,
            "active_jobs": sum(1 for j in jobs if j["stage"] not in ("done", "failed")),
            "account_count": len(store.accounts()),
            "benchmark_count": len(store.followed_accounts()),
        }
    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        if patch.get("writer_skill"):
            from ... import skills

            names = {s["name"] for s in skills.load_skills(user=skills.user_path())["skills"] if s.get("stage") == "write"}
            if patch["writer_skill"] not in names:
                raise HTTPException(status_code=400, detail="只能选「写文」那一步里的 skill，或者不用")
        if patch.get("video_projects_root"):
            from ... import icloud

            # 存之前拦：存进去以后每个剪辑页都会报错，不如当场说清楚。
            icloud.refuse_synced_root(Path(patch["video_projects_root"]).expanduser())
        return store.update_settings(patch)
    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        from ... import skills

        data = skills.load_skills(user=skills.user_path())
        try:
            vroot: Path | None = video_root()
        except Exception:  # 没设视频盘也照样画流程，只是动效那一步不计数
            vroot = None
        # 流程图和「在不在流程中」：接线从代码读，用量数近两周草稿和视频项目里留下的东西
        return data | skills.flow_view(data["skills"], data["stages"], writer_skill=store.settings()["writer_skill"] or "",
                                       drafts=drafts_root, video_root=vroot)
    @app.put("/api/skills")
    def put_skill(body: SkillBody) -> dict[str, Any]:
        """加一个或改一个。第一次改的时候把仓库里的种子复制成 作者自己的清单。"""
        from ... import skills

        entry = skills.upsert(body.model_dump(exclude={"previous"}), user=skills.user_path(), previous=body.previous)
        return {"skill": entry}
    @app.delete("/api/skills/{name}")
    def delete_skill(name: str) -> dict[str, Any]:
        from ... import skills

        if not skills.remove(name, user=skills.user_path()):
            raise ValueError("这个 skill 已经不在清单里了")
        return {"ok": True}
    @app.get("/api/skills/{name}/doc")
    def skill_doc(name: str) -> dict[str, Any]:
        from ... import skills

        return skills.read_doc(name, user=skills.user_path())
    def _me_links() -> dict[str, Any]:
        from ... import conf
        from ... import profile as profile_mod

        data = profile if profile is not None else profile_mod.load()
        douyin = str(((data.get("me") or {}) if isinstance(data.get("me"), dict) else {}).get("douyin") or "").strip()
        return {**conf.me_links(), "douyin": douyin}
    @app.get("/api/me/links")
    def get_me_links() -> dict[str, Any]:
        return _me_links()
    @app.put("/api/me/links")
    def put_me_links(body: dict[str, Any]) -> dict[str, Any]:
        """写进 profile.yaml 的 me.github / me.site（只存这一处），当场生效，X 页的素材也跟着换。"""
        from ... import conf
        from ... import profile as profile_mod

        raw_gh = str(body.get("github") or "").strip()
        raw_site = str(body.get("site") or "").strip()
        login = conf.github_login(raw_gh)
        site = conf.site_url(raw_site)
        if raw_gh and not login:
            raise ValueError("GitHub 填用户名或主页链接，形如 zinan92 或 https://github.com/zinan92")
        if raw_site and not site:
            raise ValueError("网站填网址，形如 https://example.com")
        target = profile_mod.setup_path() if profile is not None else config_dir() / "profile.yaml"
        current = profile_mod.load(target) if target.is_file() else {}
        changes: dict[str, Any] = {"me": {"github": login, "site": site}}
        # 老地方（x_line.*）还写着的，一起清掉：不然清空以后重启又从那里冒回来
        legacy = current.get("x_line") if isinstance(current.get("x_line"), dict) else {}
        if legacy.get("github_user") or legacy.get("site"):
            changes["x_line"] = {"github_user": "", "site": ""}
        path = profile_mod.save(changes, target)
        if profile is not None:
            fresh = profile_mod.load(path)
            profile.clear()
            profile.update(fresh)
        for key, value in (("me.github", login), ("me.site", site)):
            env = conf.ENV_MAP[key][0]
            if value:
                os.environ[env] = value
            else:
                os.environ.pop(env, None)
        store.log_event("profile", "在哪找到我：改了 GitHub 和网站")
        return _me_links()
