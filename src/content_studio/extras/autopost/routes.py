"""机器发布、自动排队、登录后补发。Trial 构建时整个模块不交付。"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any
from pathlib import Path
from ...store import StoreError, now_iso
from ...web import PublishJobBody, logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = (
    "LOGIN_RECHECK_SECONDS", "LOGIN_TIMEOUT_SECONDS", "OTHERS_TICK_SECONDS", "PLATFORM_MODES", "_bw_pick",
    "_bw_snapshot", "_bw_start", "_login_view", "_pp_action", "_pp_label", "_pp_pending", "_release_for",
    "_traffic", "bw_lock", "bw_run", "draft_exists_fn", "drafts_root", "feature_on", "get_backfill", "hooks", "others_auto",
    "places", "platform_logins", "pp_mod", "publisher_specs", "reach", "startup", "stop_auto",
    "store",
)
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    LOGIN_RECHECK_SECONDS = ctx.LOGIN_RECHECK_SECONDS
    LOGIN_TIMEOUT_SECONDS = ctx.LOGIN_TIMEOUT_SECONDS
    OTHERS_TICK_SECONDS = ctx.OTHERS_TICK_SECONDS
    PLATFORM_MODES = ctx.PLATFORM_MODES
    _bw_pick = ctx._bw_pick
    _bw_snapshot = ctx._bw_snapshot
    _bw_start = ctx._bw_start
    _login_view = ctx._login_view
    _media_base = places.media_base
    _pp_action = ctx._pp_action
    _pp_label = ctx._pp_label
    _pp_pending = ctx._pp_pending
    _release_for = ctx._release_for
    _traffic = ctx._traffic

    def _product_for(topic_id: int) -> dict[str, Any] | None:
        fn = ctx.hooks.get("product_for_topic")  # 这条带的产品（#590）：描述末尾加它的私信关键词或落地页
        return fn(topic_id) if fn and ctx.feature_on("products") else None
    bw_lock = ctx.bw_lock
    bw_run = ctx.bw_run
    draft_exists_fn = ctx.draft_exists_fn
    drafts_root = ctx.drafts_root
    final_video_path = places.final_video_path
    get_backfill = ctx.get_backfill
    others_auto = ctx.others_auto
    platform_logins = ctx.platform_logins
    pp_mod = ctx.pp_mod
    publisher_specs = ctx.publisher_specs
    reach = ctx.reach
    stop_auto = ctx.stop_auto
    store = ctx.store

    @app.post("/api/topics/{topic_id}/platform/{key}/send")
    def platform_send(topic_id: int, key: str, body: dict[str, Any]) -> dict[str, Any]:
        """机器能发的（X 文字、B 站、YouTube、公众号草稿）：点一下就发，发完形式级记一笔。要你自己传的这里不接。
        B 站、YouTube、公众号 10/8 起做好了自己发（_others_auto_tick），这里只剩「再发一次」。"""
        form = str(body.get("form") or "")
        action = _pp_action(key, form)
        if action not in ("auto", "draft") or key not in PLATFORM_MODES:
            raise ValueError("这一种要你自己传：复制文案，传完点「发了」")
        spec = publisher_specs().get(key) or {}
        if spec.get("login_argv") and _login_ok(key, spec) is False:
            return {"state": "login", "message": f"{_pp_label(key)}要先登录"}
        return _pp_send(topic_id, key, form)
    def _pp_send(topic_id: int, key: str, form: str, *, by: str = "") -> dict[str, Any]:
        from ... import publisher

        topic = store.topic(topic_id)
        job = prepare_publish(topic_id, PublishJobBody(platform=key, mode=PLATFORM_MODES[key], auto=True))["job"]
        store.update_publish_job(job["id"], state="running", confirmed_at=now_iso())

        def run() -> None:
            _run_publish(job["id"])
            done = store.publish_job(job["id"])
            if done["state"] == "done" and (done.get("result") or {}).get("published") is not False:
                try:
                    store.set_publish_post(topic_id, key, form, published=True, url=publisher.result_url(done.get("result") or {}))
                except StoreError:
                    pass

        threading.Thread(target=run, name=f"platform-send-{topic_id}-{key}", daemon=True).start()
        store.log_event("publish", f"《{topic['title'][:24]}》→ {_pp_label(key)}（{reach.FORM_LABEL.get(form, form)}），{by}机器在发", topic_id)
        return {"state": "running", "job": job["id"]}
    def _others_login_ok(key: str) -> bool:
        """登着没有。真探测要起一个进程，所以过期了以后十分钟才再探一次；他刚在页面上登好了就马上再探。"""
        spec = publisher_specs().get(key) or {}
        if not spec.get("login_argv"):
            return True
        flagged = others_auto["login"].get(key)
        just_logged_in = (platform_logins.get(key) or {}).get("state") == "ok"
        if flagged and not just_logged_in and time.monotonic() - flagged < LOGIN_RECHECK_SECONDS:
            return False
        if _login_ok(key, spec) is False:
            others_auto["login"][key] = time.monotonic()
            return False
        others_auto["login"].pop(key, None)
        return True
    def _wechat_check_drafts(items: list[dict[str, Any]]) -> None:
        """公众号：在草稿箱等群发的，半小时去看一次草稿还在不在。不在了 = 他群发了，记一笔「发了」。"""
        from . import wechat_publish

        for it in items:
            for r in it["rows"]:
                if r["plan"] != "draft":
                    continue
                job = store.publish_job(r["job"]["id"])
                media_id = str((job.get("result") or {}).get("media_id") or "")
                last = others_auto["draft_checked"].get(media_id)
                if not media_id or (last and time.monotonic() - last < pp_mod.DRAFT_CHECK_MINUTES * 60):
                    continue
                others_auto["draft_checked"][media_id] = time.monotonic()
                try:
                    there = draft_exists_fn(media_id) if draft_exists_fn else wechat_publish.draft_exists(media_id)
                except Exception as exc:  # noqa: BLE001 - 看不了就下次再看，不能当成发了
                    logger.warning("wechat draft check %s: %s", media_id, exc)
                    continue
                if there:
                    continue
                store.set_publish_post(it["topic_id"], "wechat_mp", r["form"], published=True, url=None)
                store.set_publish_record(it["topic_id"], "wechat_mp", published=True, url=None, form=r["form"])
                store.log_event("publish", f"《{it['title'][:24]}》公众号草稿箱里没了：算你群发了", it["topic_id"])
    def _others_auto_tick() -> list[tuple[int, str, str]]:
        """一轮：每个开着的平台，做好了没发的挑最早那条发出去。返回这一轮开始发的 (选题, 平台, 形式)。"""
        if not ctx.feature_on("autopost"):  # 用户在「设置 · 流程」里关了机器代发（10/9）
            return []
        accounts = store.settings()["platform_accounts"] or {}
        started = []
        for key in pp_mod.AUTO_KEYS:
            if not (accounts.get(key) or {}).get("on"):
                continue
            items = _pp_pending(key)
            if key == "wechat_mp":
                _wechat_check_drafts(items)
                items = _pp_pending(key)
            cells = [(it, r) for it in items for r in it["rows"]]
            if any(r["plan"] == "running" for _it, r in cells):
                continue  # 一个平台一次只发一条：B 站、YouTube 一条就是几百 MB
            due = [(it, r) for it, r in cells if r["plan"] == "due"]
            if not due or not _others_login_ok(key):
                continue
            it, r = due[-1]  # 待发是新的在前：先发最早做好的那条
            _pp_send(it["topic_id"], key, r["form"], by="做好了自动发，")
            started.append((it["topic_id"], key, r["form"]))
        return started
    def _others_auto_loop() -> None:
        stop_auto.wait(30)  # 刚起来先让别的恢复跑完
        while not stop_auto.is_set():
            try:
                _others_auto_tick()
            except Exception as exc:  # noqa: BLE001 - 下一轮再来
                logger.warning("others auto tick: %s", exc)
            stop_auto.wait(OTHERS_TICK_SECONDS)
    @app.get("/api/topics/{topic_id}/publish-jobs")
    def list_publish_jobs(topic_id: int) -> dict[str, Any]:
        from ... import copypack, publisher

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        copy = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms")
        return {
            "platforms": publisher.readiness(publisher_specs()),
            "video": {"path": str(video), "mb": round(video.stat().st_size / 1_048_576, 1)} if video else None,
            "has_copy": bool(copy),
            "jobs": store.publish_jobs(topic_id),
        }
    @app.post("/api/topics/{topic_id}/publish-jobs")
    def prepare_publish(topic_id: int, body: PublishJobBody) -> dict[str, Any]:
        from ... import copypack, publisher

        topic = store.topic(topic_id)
        video = final_video_path(topic)
        text_only = bool(publisher_specs().get(body.platform, {}).get("no_video"))
        if video is None and not text_only:
            raise publisher.PublishError("这个选题还没有成片：先关联视频项目并完成剪辑")
        copy = (copypack.read_copy(drafts_root, topic_id) or {}).get("platforms")
        article = Path(topic["article_path"]) if topic.get("article_path") else None
        release_info = _release_for(topic) or {}
        covers = release_info.get("covers") or {}
        # 公众号要 2.35:1：有专门出的公众号封面就用它，没有就用横版（发的时候垫宽）。
        # YouTube、B 站是 16:9 的框：有 16:9 那张就用它，没有退回 4:3 横版。
        chosen = ((covers.get("wechat") if body.platform == "wechat_mp" else None)
                  or (covers.get("wide") if body.platform in ("youtube", "bilibili") else None)
                  or covers.get("landscape"))
        cover = _media_base(topic) / chosen if chosen else None
        # 抖音的封面框横竖各一张
        portrait = _media_base(topic) / covers["portrait"] if covers.get("portrait") else None
        payload = publisher.build_payload(body.platform, body.mode, video=video, copy=copy, publishers=publisher_specs(), traffic=_traffic(), product=_product_for(topic_id),
                                          article=article, cover=cover, cover_portrait=portrait)
        if body.auto:
            payload["auto"] = True
        return {"job": store.create_publish_job(topic_id, payload)}
    def _open_in_browser(url: str | None) -> None:
        """发完就在 作者 的默认浏览器里打开那一页（他登录着的那个）。测试里关掉。"""
        if not url or os.environ.get("CONTENT_STUDIO_NO_OPEN") or sys.platform != "darwin":
            return
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    def _run_publish(job_id: int) -> None:
        from ... import publisher

        job = store.publish_job(job_id)
        copy_platform = publisher_specs()[job["platform"]]["copy_key"]

        try:
            result = publisher.run(job["payload"], publishers=publisher_specs())
        except Exception as exc:  # noqa: BLE001 - shown on the job
            result = {"ok": False, "status": "error", "message": str(exc)}
        ok = bool(result.get("ok"))
        if result.get("status") == "window_closed":
            # 窗口关了、没点发布：这次就算没发生，瓦片回到原样，不挂「上次失败」
            store.update_publish_job(job_id, state="cancelled", result=result, message=publisher.explain(result), finished_at=now_iso())
            return
        store.update_publish_job(job_id, state="done" if ok else "failed", result=result, message=None if ok else publisher.explain(result), finished_at=now_iso())
        if ok and not (job.get("payload") or {}).get("auto"):
            _open_in_browser(publisher.confirm_url(job["platform"], result))
        # 存草稿不算发出去：X / 公众号 / 研习室的脚本在草稿时返回 published=false。
        # 9/24 X 只存了草稿，发布台就标「已发到 X」，按钮也跟着没了。
        if ok and result.get("published") is not False:
            try:
                store.set_publish_record(job["topic_id"], copy_platform, published=True, url=publisher.result_url(result))
            except StoreError:
                pass
    @app.post("/api/publish-jobs/{job_id}/confirm")
    def confirm_publish(job_id: int) -> dict[str, Any]:
        from ... import publisher

        job = store.publish_job(job_id)
        publisher.confirmable(job)
        job = store.update_publish_job(job_id, state="running", confirmed_at=now_iso())
        threading.Thread(target=_run_publish, args=(job_id,), name=f"publish-{job_id}", daemon=True).start()
        return {"job": job, "message": f"已确认，开始发布到{job['payload']['platform_label']}"}
    @app.delete("/api/publish-jobs/{job_id}")
    def cancel_publish(job_id: int) -> dict[str, Any]:
        job = store.publish_job(job_id)
        if job["state"] != "awaiting_confirm":
            raise ValueError("只能取消还没确认的发布")
        return {"job": store.update_publish_job(job_id, state="cancelled", finished_at=now_iso())}
    def _login_ok(key: str, spec: dict[str, Any]) -> bool | None:
        """现在登着没有（真跑一次探测，不看缓存）。没有探测命令的返回 None。"""
        from ... import channel_probe
        from ...paths import config_dir

        checked = channel_probe.probe(key, spec, force=True, cache_path=config_dir() / "channel-probes.json")
        return None if checked is None else checked.get("ok")
    def _bw_resend(key: str) -> None:
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            # 看「今天在发的」那张表本身（库里排的格子 + 上次的结果），不只看内存：服务重启过的话内存里是空的
            # （10/3 登好了 YouTube 却没再发——10:57 刚自动部署重启过）
            items = _bw_snapshot(get_backfill())["items"]
            with bw_lock:
                busy = bw_run["running"]
            cells = [{"video_id": it["video_id"], "platform": it["platform"]} for it in items
                     if it["platform"] == key and not it["sent"] and it["state"] in ("failed", "login")]
            if not cells:
                return
            if not busy:
                try:
                    _bw_start(_bw_pick(cells, get_backfill(), again=True))
                except Exception as exc:  # noqa: BLE001 - shown on the login status
                    with bw_lock:
                        platform_logins[key].update(message=f"登好了，但没能再发：{exc}")
                return
            time.sleep(2)
    def _login_watch(key: str, proc: subprocess.Popen, spec: dict[str, Any]) -> None:
        try:
            proc.wait(timeout=LOGIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            with bw_lock:
                platform_logins[key].update(state="failed", message=f"{LOGIN_TIMEOUT_SECONDS // 60} 分钟没登好，停了。再点一次登录")
            return
        ok = _login_ok(key, spec)
        with bw_lock:
            if ok is False:
                platform_logins[key].update(state="failed", message="登录窗口关了，但还没登上。再点一次登录")
                return
            platform_logins[key].update(state="ok", message="登好了，正在把没发出去的再发一遍")
        _bw_resend(key)
    @app.post("/api/platforms/{key}/login")
    def platform_login(key: str) -> dict[str, Any]:
        from ... import publisher
        from ...paths import config_dir

        spec = publisher_specs().get(key) or {}
        argv = list(spec.get("login_argv") or [])
        if not argv:
            raise ValueError("这个平台没法在工作台里登录")
        with bw_lock:
            if (platform_logins.get(key) or {}).get("state") == "running":
                return _login_view_unlocked(key)
        if argv[0] == "python3":
            argv[0] = publisher.python_with(tuple(spec.get("needs") or ()))
        log = config_dir() / f"login-{key}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        cwd = spec.get("login_cwd") or (str(publisher.CONTENT_OPS) if publisher.CONTENT_OPS.is_dir() else None)
        with log.open("w", encoding="utf-8") as out:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=cwd)
        with bw_lock:
            platform_logins[key] = {"state": "running", "message": "等你在弹出的窗口里登录…", "proc": proc}
        store.log_event("publish", f"打开 {spec.get('label', key)} 登录")
        threading.Thread(target=_login_watch, args=(key, proc, spec), name=f"login-{key}", daemon=True).start()
        return _login_view(key)
    def _login_view_unlocked(key: str) -> dict[str, Any]:
        cur = dict(platform_logins.get(key) or {"state": "idle", "message": ""})
        cur.pop("proc", None)
        return cur
    @app.get("/api/platforms/{key}/login")
    def platform_login_state(key: str) -> dict[str, Any]:
        return _login_view(key)


    ctx.hooks.update(prepare_publish=prepare_publish, run_publish=_run_publish, login_ok=_login_ok)
    app.state.others_auto_tick = _others_auto_tick
    ctx.startup.append(lambda: threading.Thread(target=_others_auto_loop, name="others-auto", daemon=True).start())
