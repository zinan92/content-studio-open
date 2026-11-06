"""进项 · 自己的账号和对标账号（同步、加号、新发）、爆款、拆解任务和报告、流量视频、Obsidian 笔记（只读）。"""
from __future__ import annotations

import json
import threading
from typing import Any
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
from datetime import datetime, timedelta, timezone
from ...accounts import add_account
from ... import vault
from ...accounts import AccountError, PENDING_NOTES, PLATFORM_DOUYIN
from ...store import StoreError
from ...worker import normalize_video_url
from ...web import AccountKindBody, FeedMarkBody, JobBody, REPORT_STALE_DAYS, SwipeBody, TriageBody, UrlBody, _start_screen_reach, logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = (
    "DEEP_SYNC_PAGES", "FEED_HOT", "_backfill_state", "_sync_and_queue", "board_mod", "cookie_path",
    "creator_db", "factory", "job_view", "ops", "places", "report_dirs", "start_archive", "store", "swipe_root",
    "sync_all_fn", "teardown_state", "worker",
)
PROVIDES: tuple[str, ...] = ("reports",)


def register(app: Any, ctx: Any) -> None:
    DEEP_SYNC_PAGES = ctx.DEEP_SYNC_PAGES
    FEED_HOT = ctx.FEED_HOT
    _backfill_state = ctx._backfill_state
    _sync_and_queue = ctx._sync_and_queue
    board_mod = ctx.board_mod
    cookie_path = ctx.cookie_path
    creator_db = ctx.creator_db
    factory = ctx.factory
    job_view = ctx.job_view
    ops = ctx.ops
    places = ctx.places
    report_dirs = ctx.report_dirs
    start_archive = ctx.start_archive
    store = ctx.store
    swipe_root = ctx.swipe_root
    sync_all_fn = ctx.sync_all_fn
    teardown_state = ctx.teardown_state
    worker = ctx.worker
    _raw_root = places.raw_root
    _speak_dir = places.topic_dir
    report_file = places.report_file
    vault_path = places.vault_path

    def full_sync() -> dict:
        if sync_all_fn is not None:
            result = sync_all_fn(store)
        else:
            from ...cli import sync_everything

            # 小红书读数要截 作者自己 Chrome 的窗口，只有「内容工作台读数」小 App 有录屏和控制 Chrome 的授权，
            # 所以这里只是叫它起来跑一趟（和每天 9:25 同一件事），结果一分钟左右后自己写进来。
            result = {"xiaohongshu": _start_screen_reach()}
            result.update(sync_everything(
                store,
                cookie_path=cookie_path,
                creator_db=creator_db or Path("/nonexistent"),
                benchmarks=False,
            ))
        worker.notify()
        if not result.get("stopped"):
            start_archive(limit=5)
        return result
    def benchmark_sync() -> dict:
        from ...cli import sync_benchmarks

        result = sync_benchmarks(store, cookie_path=cookie_path, factory=factory)
        store.log_event("sync", f"老师和对标同步完：{sum(1 for a in result['accounts'] if a['status'] == 'ok')} 个号")
        return result
    def account_view(account: dict[str, Any], threshold: float) -> dict[str, Any]:
        videos = store.videos(account["id"])
        median = store.account_median(account["id"])
        chronological = sorted(
            (v for v in videos if v["likes"] is not None and not v["is_image_post"]),
            key=lambda v: v["published_at"] or "",
        )
        return {
            **account,
            "pending_note": PENDING_NOTES.get(account["platform"]),
            "syncing": account["id"] in ops.syncing or (account["platform"] == PLATFORM_DOUYIN and (ops.full_sync_running if account["is_self"] else ops.benchmarks_running)),
            "video_count": len(videos),
            "latest_published_at": next((v["published_at"] for v in videos if v["published_at"]), None),
            "median_likes": median,
            "breakout_count": sum(1 for v in chronological if median and v["likes"] / median >= threshold),
            "spark": [v["likes"] for v in chronological][-60:],
        }
    @app.post("/api/sync")
    def sync_all() -> dict[str, Any]:
        """你自己的全部账号：抖音主号和后台、B站、X、YouTube、小红书。不碰对标。"""
        started = ops.run("all", full_sync)
        return {"started": started, "message": "开始同步你自己的全部账号" if started else "已经有一趟同步在跑，等它跑完"}
    @app.post("/api/sync/benchmarks")
    def sync_benchmarks_route() -> dict[str, Any]:
        """对标账号：每个号只看最新一页，只在对标雷达页点。"""
        started = ops.run("benchmarks", benchmark_sync)
        n = len(store.followed_accounts())
        return {"started": started, "message": f"开始同步 {n} 个对标账号，每个号只看最新一页" if started else "已经有一趟同步在跑，等它跑完"}
    @app.get("/api/accounts")
    def accounts() -> list[dict[str, Any]]:
        threshold = float(store.settings()["threshold"])
        return [account_view(a, threshold) for a in store.followed_accounts()]
    @app.get("/api/followed/posts")
    def followed_posts(days: int = 7) -> dict[str, Any]:
        """What the accounts 作者 follows posted lately — the 对标 tab in 进项."""
        posts = [{**v, **teardown_state(v["video_id"])} for v in store.followed_posts(days)]
        return {"posts": posts, "days": days, "account_count": len(store.followed_accounts())}
    @app.post("/api/accounts")
    def post_account(body: UrlBody) -> dict[str, Any]:
        needs_client = "douyin.com" in body.url and "/user/" not in body.url
        account = add_account(store, body.url, client_factory=factory if needs_client else None, is_self=body.is_self)
        syncing = False
        if account["platform"] == PLATFORM_DOUYIN:
            syncing = ops.run(account["id"], lambda: _sync_and_queue(account["id"], first=True))
        threshold = float(store.settings()["threshold"])
        return {"account": {**account_view(account, threshold), "syncing": syncing}}
    @app.post("/api/accounts/{account_id}/sync")
    def post_sync(account_id: int, deep: bool = False) -> dict[str, Any]:
        account = store.account(account_id)
        if account["platform"] != PLATFORM_DOUYIN:
            raise AccountError(PENDING_NOTES.get(account["platform"], "该平台抓取待接入"))
        started = ops.run(account_id, lambda: _sync_and_queue(account_id, deep=deep))
        if not started:
            return {"started": False, "message": "这个账号正在同步中"}
        return {"started": True, "message": f"开始往回翻，最多 {DEEP_SYNC_PAGES} 页（约 {DEEP_SYNC_PAGES * 20} 条），一两分钟" if deep else "开始同步"}
    @app.get("/api/accounts/{account_id}/videos")
    def account_videos(account_id: int) -> dict[str, Any]:
        """一个对标账号的全部作品（不只爆款），带中位倍数和拆解状态。"""
        account = store.account(account_id)
        median = store.account_median(account_id)
        rows = []
        for v in store.videos(account_id):
            multiple = round(v["likes"] / median, 1) if median and v["likes"] is not None else None
            rows.append({**v, "multiple": multiple, "account_nickname": account["nickname"], "account_median": median,
                         **teardown_state(v["video_id"])})
        return {"account_id": account_id, "nickname": account["nickname"], "median": median, "videos": rows}
    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: int) -> dict[str, Any]:
        store.delete_account(account_id)
        return {"ok": True}
    @app.patch("/api/accounts/{account_id}")
    def patch_account(account_id: int, body: AccountKindBody) -> dict[str, Any]:
        """老师 / 对标（9/30 作者：一个人只有一个身份，既是老师又是对标的算对标）。"""
        account = store.account(account_id)
        if account["is_self"]:
            raise ValueError("这是你自己的号")
        if body.kind not in ("teacher", "benchmark"):
            raise ValueError("只能是老师或对标")
        store.update_account(account_id, kind=body.kind)
        threshold = float(store.settings()["threshold"])
        return {"account": account_view(store.account(account_id), threshold)}
    @app.get("/api/feed")
    def get_feed(days: int = 7) -> dict[str, Any]:
        """老师和对标新发的视频：作者自己去看，看过了点一下。不下载、不拆，照样全列（9/30 作者：
        「他俩出了视频我都去看就好了」「视频可能刚跑了 6 个小时，你怎么知道最终结果怎么样」）。
        想拆、想复刻，他点了才做。10/4 起每条标上「是这个号平时的几倍」，1.5 倍以上的排最上面，其余照发布时间。"""
        days = min(max(days, 1), 30)
        marks = store.feed_marks()
        medians: dict[int, float | None] = {}
        swiped = {r["url"]: r["id"] for r in store.swipe_videos()}
        kinds = {a["id"]: a for a in store.followed_accounts()}
        out: dict[str, list[dict[str, Any]]] = {"teacher": [], "benchmark": []}
        for v in store.followed_posts(days):
            acct = kinds.get(v["account_id"]) or {}
            kind = "teacher" if acct.get("kind") == "teacher" else "benchmark"
            url = f"https://www.douyin.com/video/{v['video_id']}"
            mark = marks.get(v["video_id"]) or {}
            if v["account_id"] not in medians:
                medians[v["account_id"]] = store.account_median(v["account_id"])
            median = medians[v["account_id"]]
            multiple = round(v["likes"] / median, 1) if median and v.get("likes") is not None else None
            out[kind].append({
                "multiple": multiple, "hot": bool(multiple is not None and multiple >= FEED_HOT), "account_median": median,
                "video_id": v["video_id"], "url": url, "title": v.get("title") or "", "account": acct.get("nickname") or "", "account_id": v["account_id"],
                "published_at": v.get("published_at"), "duration_seconds": v.get("duration_seconds"), "likes": v.get("likes"), "is_image_post": bool(v.get("is_image_post")),
                "seen_at": mark.get("seen_at"), "opened_at": mark.get("opened_at"), "note": mark.get("note") or "", "swipe_id": swiped.get(url), **teardown_state(v["video_id"]),
            })
        for rows in out.values():
            # 稳定排序：爆的按倍数从高到低在前，其余保持发布时间从新到旧
            rows.sort(key=lambda r: (not r["hot"], -(r["multiple"] or 0) if r["hot"] else 0))
        counts = {k: {"total": len(rows), "unseen": sum(1 for r in rows if not r["seen_at"])} for k, rows in out.items()}
        accounts = {k: [a["nickname"] or "未同步" for a in kinds.values() if ("teacher" if a.get("kind") == "teacher" else "benchmark") == k] for k in out}
        return {"days": days, **out, "counts": counts, "accounts": accounts}
    @app.put("/api/feed/{video_id}")
    def put_feed_mark(video_id: str, body: FeedMarkBody) -> dict[str, Any]:
        if store.video(video_id) is None:
            raise ValueError("找不到这条视频")
        store.set_feed_mark(video_id, seen=body.seen, note=body.note, opened=body.opened)
        return {"ok": True}
    @app.get("/api/outliers")
    def outliers(threshold: float | None = None) -> list[dict[str, Any]]:
        value = threshold if threshold is not None else float(store.settings()["threshold"])
        return [{**video, **teardown_state(video["video_id"])} for video in store.outliers(value)]
    @app.get("/api/jobs")
    def jobs() -> list[dict[str, Any]]:
        results = []
        # 同一条视频失败了好几次，队列里只列最近一次，带上次数（9/29 以前一条失败了 37 次，把队列刷满了）
        all_jobs = store.jobs(limit=1000)
        fails: dict[str, int] = {}
        for job in all_jobs:
            if job["stage"] == "failed" and job["video_id"]:
                fails[job["video_id"]] = fails.get(job["video_id"], 0) + 1
        seen_failed: set[str] = set()
        shown = []
        for job in all_jobs:
            if job["stage"] == "failed" and job["video_id"]:
                if job["video_id"] in seen_failed:
                    continue
                seen_failed.add(job["video_id"])
            shown.append({**job, "attempts": fails.get(job["video_id"] or "", 0)})
        for job in shown[:200]:
            video = store.video(job["video_id"]) if job["video_id"] else None
            results.append(
                {
                    **job_view(job),
                    "title": video["title"] if video else None,
                    "has_report": bool(job["video_id"] and report_file(job["video_id"])),
                    "running": worker.current_job_id == job["id"],
                    "attempts": job.get("attempts", 0),
                }
            )
        return results
    @app.post("/api/jobs")
    def post_job(body: JobBody) -> dict[str, Any]:
        if body.video_id:
            if not body.video_id.isdigit():
                raise ValueError("视频编号无效")
            url, video_id = f"https://www.douyin.com/video/{body.video_id}", body.video_id
        else:
            url, video_id = normalize_video_url(body.url or "")
        job, created = store.enqueue(url=url, video_id=video_id, source=body.source or "手动添加", retry_failed=True)
        worker.notify()
        return {"job": job_view(job), "created": created, "message": "已加入拆解队列" if created else "这条视频已经在队列里或拆解过了"}
    @app.delete("/api/jobs/{job_id}")
    def cancel(job_id: int) -> dict[str, Any]:
        store.cancel_job(job_id)
        return {"ok": True}
    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: int) -> dict[str, Any]:
        job = store.retry_job(job_id)
        worker.notify()
        return {"job": job_view(job)}
    @app.get("/api/reports")
    def reports() -> list[dict[str, Any]]:
        archived = store.archived_reports()
        seen: dict[str, dict[str, Any]] = {}
        for base in report_dirs:
            for path in sorted((base / "reports").glob("*/report.json")):
                video_id = path.parent.name
                if video_id in seen:
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if data.get("schema_version", 1) < 2:
                    continue
                seen[video_id] = {
                    "video_id": video_id,
                    "title": data.get("title"),
                    "author": data.get("author"),
                    "generated_at": data.get("generated_at"),
                    "multiple": (data.get("facts") or {}).get("multiple_of_median"),
                    "is_self": bool((data.get("facts") or {}).get("creator_avg_view_second")),
                    "archived_at": archived.get(video_id),
                }
        # Benchmark reports nobody opened in 7 days are archived when the list is read, so the unread count stays meaningful.
        stale_before = (datetime.now(timezone.utc) - timedelta(days=REPORT_STALE_DAYS)).isoformat()
        for item in seen.values():
            if not item["archived_at"] and not item["is_self"] and (item["generated_at"] or "9") < stale_before:
                item["archived_at"] = store.archive_report(item["video_id"])
                item["auto_archived"] = True
        return sorted(seen.values(), key=lambda r: r.get("generated_at") or "", reverse=True)
    @app.get("/api/reports/{video_id}")
    def report(video_id: str) -> dict[str, Any]:
        path = report_file(video_id)
        if path is None:
            raise HTTPException(status_code=404, detail="这条视频还没有拆解报告")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version", 1) < 2:
            raise HTTPException(status_code=404, detail="这是旧版报告，请重新拆解这条视频")
        return data
    @app.get("/api/reports/{video_id}/pool")
    def report_pool_state(video_id: str) -> dict[str, Any]:
        found = _report_topic(video_id)
        return {"topic": found if found and not found.get("archived_at") else None}
    @app.post("/api/reports/{video_id}/archive")
    def archive_report(video_id: str) -> dict[str, Any]:
        if report_file(video_id) is None:
            raise HTTPException(status_code=404, detail="这条视频还没有拆解报告")
        return {"video_id": video_id, "archived_at": store.archive_report(video_id)}
    @app.delete("/api/reports/{video_id}/archive")
    def unarchive_report(video_id: str) -> dict[str, Any]:
        if report_file(video_id) is None:
            raise HTTPException(status_code=404, detail="这条视频还没有拆解报告")
        store.unarchive_report(video_id)
        return {"video_id": video_id, "archived_at": None}
    @app.get("/api/vault/inbox")
    def vault_inbox(days: int = 1, source: str | None = None) -> dict[str, Any]:
        since = vault.window_start(min(max(days, 1), 30))
        from ... import board

        triage = store.triage()
        items = vault.inbox(vault_path(), since=since, sources=(source,) if source else None)
        # A note that already became a video should not look like fresh material.
        used: dict[str, dict[str, Any]] = {}
        video_of: dict[int, str] = {}
        try:
            _, links, _ = _backfill_state()
            video_of = {tid: vid for vid, tid in links.items()}
        except Exception:  # noqa: BLE001 - the jump target is a nicety, never block 进项
            pass
        for topic in store.topics(include_archived=True):
            shipped = board.is_shipped(topic)
            dropped = bool(topic.get("archived_at")) and not shipped
            for path in topic["note_paths"]:
                row = {"topic_id": topic["id"], "title": topic["title"], "shipped": shipped, "dropped": dropped,
                       "video_id": topic.get("published_video_id") or video_of.get(topic["id"])}
                # 还在做的优先；标过「不做了」的，只在没别的选题占着这篇时才显示。
                if path not in used or (used[path]["dropped"] and not dropped):
                    used[path] = row
        from ... import hot

        rows = [{**item, "triage": (triage.get(item["path"]) or {}).get("status"), "used_by": used.get(item["path"])} for item in items]
        return {
            "since": since.isoformat(timespec="minutes"),
            "items": hot.mark_breakouts(rows, store.outliers(float(store.settings()["threshold"]))),
        }
    @app.put("/api/vault/triage")
    def put_triage(body: TriageBody) -> dict[str, Any]:
        root = vault.vault_root(vault_path())
        vault.safe_path(root, body.path)
        store.set_triage(body.path, body.status)
        topic = None
        if body.status == "topic":
            topic = store.topic_for_note(body.path)
            if topic is None:
                note = vault.read_note(vault_path(), body.path)
                me = store.self_account()
                topic = store.create_topic(note["title"], note_paths=[body.path], account_id=me["id"] if me else None)
                store.log_event("pool", f"《{topic['title'][:30]}》从选题页进了选题池", topic["id"])
            elif topic.get("archived_at"):
                # 以前标过「不做了」。再点一次「入选题池」就是改主意了，把它拿回看板——
                # 否则接口返回成功、选题却还在归档里，进项和加工中永远对不上。
                topic = store.update_topic(topic["id"], archived_at=None)
                store.log_event("pool", f"《{topic['title'][:30]}》又捡回来了", topic["id"])
            else:
                store.log_event("pool", f"《{topic['title'][:30]}》从选题页进了选题池", topic["id"])
        elif body.status:
            store.log_event("triage", f"进项里「{body.path.split('/')[-1][:30]}」标成了{ {'shot': '拍过了', 'ignored': '暂不拍', 'back': '捡回来'}.get(body.status, body.status) }")
        return {"path": body.path, "triage": body.status, "topic": topic}
    def _report_topic(video_id: str) -> dict[str, Any] | None:
        from ... import speak as speak_mod

        for topic in store.topics(include_archived=True):
            data = speak_mod.load(_speak_dir(topic["id"]))
            if data and data.get("video_id") == video_id:
                return topic
        return None
    @app.post("/api/reports/{video_id}/pool")
    def pool_report(video_id: str) -> dict[str, Any]:
        """拆完的爆款入选题池：建一条候选选题，记下出处和拆解（不把他的原文塞进选题素材——骨架只该读 作者 的话）。"""
        from ... import speak as speak_mod

        found = _report_topic(video_id)
        if found and not found.get("archived_at"):
            return {"topic": found, "existing": True}
        report_data = report(video_id)
        data = speak_mod.from_report(report_data)
        title = speak_mod._clean_title(data["title"])[:60] or "复刻"
        me = store.self_account()
        memo = f"拆解自：{data['author']}《{title}》{data['url']}" + (f"（平时的 {data['multiple']} 倍）" if data.get("multiple") else "")
        topic = store.create_topic(title, formats="video", account_id=me["id"] if me else None, memo=memo)
        speak_mod.save(_speak_dir(topic["id"]), data)
        store.log_event("pool", f"拆完的爆款入选题池：《{title[:30]}》", topic["id"])
        return {"topic": topic, "existing": False}
    def _swipe_view(row: dict[str, Any]) -> dict[str, Any]:
        from ... import swipe

        info = row.get("info") or {}
        topic = None
        if row.get("topic_id"):
            try:
                t = store.topic(row["topic_id"])
                topic = {"id": t["id"], "title": t["title"], "shipped": board_mod.is_shipped(t), "archived": bool(t.get("archived_at"))}
            except StoreError:
                topic = None
        status = "downloading" if row["state"] == "downloading" else "failed" if row["state"] == "failed" \
            else "shipped" if topic and topic["shipped"] else "making" if topic and not topic["archived"] else "saved"
        return {
            "id": row["id"], "url": row["url"], "platform": row["platform"], "platform_label": swipe.LABELS.get(row["platform"], row["platform"]),
            "status": status, "error": row.get("error"), "note": row.get("note") or "", "collection": row.get("collection") or "",
            "created_at": row["created_at"], "topic": topic,
            **{k: info.get(k) for k in ("title", "author", "published_at", "likes", "comments", "shares", "collects", "views", "is_video")},
            "cover": f"/api/swipe/{row['id']}/cover" if info.get("cover") else None,
            "video": f"/api/swipe/{row['id']}/video" if info.get("video") else None,
        }
    def _swipe_download(swipe_id: int) -> None:
        from ... import swipe

        row = store.swipe_video(swipe_id)
        try:
            folder = swipe.download(row["url"], row["platform"], out_dir=swipe_root, cookies=cookie_path if row["platform"] == "douyin" else None)
            store.update_swipe(swipe_id, state="ready", error=None, content_dir=str(folder), info=swipe.read_item(folder))
            store.log_event("swipe", f"流量视频存好了：{(store.swipe_video(swipe_id)['info'].get('title') or row['url'])[:40]}")
        except Exception as exc:  # noqa: BLE001 - 卡片上显示
            logger.warning("swipe %s failed: %s", swipe_id, exc)
            store.update_swipe(swipe_id, state="failed", error=str(exc)[:300] or type(exc).__name__)
    def _swipe_douyin_left() -> int:
        from ... import swipe

        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        return max(0, swipe.DOUYIN_DAILY_CAP - store.swipe_count_since("douyin", start))
    @app.get("/api/swipe")
    def list_swipe() -> dict[str, Any]:
        from ... import swipe

        return {"videos": [_swipe_view(r) for r in store.swipe_videos()], "collections": list(swipe.COLLECTIONS),
                "douyin_left": _swipe_douyin_left(), "douyin_cap": swipe.DOUYIN_DAILY_CAP}
    @app.post("/api/swipe")
    def add_swipe(body: SwipeBody) -> dict[str, Any]:
        from ... import swipe

        try:
            url, platform = swipe.clean_url(body.url or "")
        except swipe.SwipeError as exc:
            raise ValueError(str(exc)) from None
        if platform == "douyin" and _swipe_douyin_left() <= 0:
            raise ValueError(f"今天抖音的已经存了 {swipe.DOUYIN_DAILY_CAP} 条：用的是你的抖音登录，一天不多下，明天再存")
        row = store.add_swipe(url, platform, body.note)
        threading.Thread(target=_swipe_download, args=(row["id"],), name=f"swipe-{row['id']}", daemon=True).start()
        return {"video": _swipe_view(row)}
    @app.patch("/api/swipe/{swipe_id}")
    def patch_swipe(swipe_id: int, body: SwipeBody) -> dict[str, Any]:
        from ... import swipe

        fields: dict[str, Any] = {}
        if body.note is not None:
            fields["note"] = body.note.strip()[:300] or None
        if body.collection is not None:
            if body.collection and body.collection not in swipe.COLLECTIONS:
                raise ValueError("没有这个合集")
            fields["collection"] = body.collection or None
        return {"video": _swipe_view(store.update_swipe(swipe_id, **fields))}
    @app.post("/api/swipe/{swipe_id}/retry")
    def retry_swipe(swipe_id: int) -> dict[str, Any]:
        row = store.swipe_video(swipe_id)
        if row["state"] != "failed":
            raise ValueError("这条不用重试")
        store.update_swipe(swipe_id, state="downloading", error=None)
        threading.Thread(target=_swipe_download, args=(swipe_id,), name=f"swipe-{swipe_id}", daemon=True).start()
        return {"video": _swipe_view(store.swipe_video(swipe_id))}
    @app.delete("/api/swipe/{swipe_id}")
    def delete_swipe(swipe_id: int) -> dict[str, Any]:
        import shutil

        row = store.swipe_video(swipe_id)
        folder = Path(row["content_dir"]) if row.get("content_dir") else None
        # 只删 swipe 目录里的东西
        if folder and folder.is_dir() and swipe_root.resolve() in folder.resolve().parents:
            shutil.rmtree(folder, ignore_errors=True)
        store.delete_swipe(swipe_id)
        return {"ok": True}
    @app.post("/api/swipe/{swipe_id}/start")
    def start_swipe(swipe_id: int) -> dict[str, Any]:
        """开始复刻：建一条选题、放到「接下来要拍的」最上面。是他点的，不自动加。"""
        row = store.swipe_video(swipe_id)
        if row["state"] != "ready":
            raise ValueError("还没下好")
        if row.get("topic_id"):
            try:
                return {"topic": store.topic(row["topic_id"])}
            except StoreError:
                pass
        info = row.get("info") or {}
        title = f"复刻：{(info.get('title') or row['url'])[:40]}"
        memo = "\n".join(x for x in (f"流量视频：{row['url']}", f"为什么想转：{row['note']}" if row.get("note") else "",
                                     f"归哪个合集：{row['collection']}" if row.get("collection") else "") if x)
        me = store.self_account()
        topic = store.create_topic(title, formats="video", account_id=me["id"] if me else None, memo=memo)
        store.update_swipe(swipe_id, topic_id=topic["id"])
        store.add_shoot_item(title, top=True, topic_id=topic["id"])
        store.log_event("pool", f"开始复刻《{title[:30]}》", topic["id"])
        return {"topic": topic}
    def _swipe_file(swipe_id: int, key: str) -> Path:
        row = store.swipe_video(swipe_id)
        rel = (row.get("info") or {}).get(key)
        folder = Path(row["content_dir"]) if row.get("content_dir") else None
        if not rel or folder is None:
            raise HTTPException(status_code=404, detail="没有这个文件")
        path = (folder / rel).resolve()
        if folder.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="没有这个文件")
        return path
    @app.get("/api/swipe/{swipe_id}/cover")
    def swipe_cover(swipe_id: int) -> FileResponse:
        return FileResponse(_swipe_file(swipe_id, "cover"), headers={"Cache-Control": "private, max-age=86400"})
    @app.get("/api/swipe/{swipe_id}/video")
    def swipe_video_file(swipe_id: int) -> FileResponse:
        return FileResponse(_swipe_file(swipe_id, "video"), media_type="video/mp4")
    @app.get("/api/vault/note")
    def vault_note(path: str) -> dict[str, Any]:
        return vault.read_note(vault_path(), path)
    @app.get("/api/vault/raw-folders")
    def raw_folders() -> dict[str, Any]:
        from ... import rawnote

        return {"folders": rawnote.folders(_raw_root())}
    @app.post("/api/vault/raw-note")
    def new_raw_note(body: dict[str, Any]) -> dict[str, Any]:
        """他写的字原样存进 003：标题 + 正文，不改写、不覆盖。"""
        from ... import rawnote

        try:
            written = rawnote.write(_raw_root(), str(body.get("folder") or ""), str(body.get("title") or "")[:60], str(body.get("body") or "")[:50000])
        except rawnote.RawNoteError as exc:
            raise ValueError(str(exc)) from exc
        rel = str(written.relative_to(vault.vault_root(vault_path())))
        store.log_event("note", f"新建了一篇原始输出：{rel}")
        return {"path": rel, "name": written.name}
    @app.get("/api/vault/raw")
    def vault_raw(path: str) -> Response:
        target = vault.safe_path(vault.vault_root(vault_path()), path)
        media = "text/html; charset=utf-8" if target.suffix.lower() == ".html" else "text/markdown; charset=utf-8"
        # Sandboxed: vault HTML can render but cannot run scripts against this app's API.
        return Response(
            target.read_bytes(),
            media_type=media,
            headers={"Content-Security-Policy": "sandbox allow-popups", "Cache-Control": "no-store"},
        )

    ctx.reports = reports  # Anna 看拆解报告列表
