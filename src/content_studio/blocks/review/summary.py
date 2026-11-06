"""汇总 · 全部作品、每周复盘、粉丝数、作品库存档。"""
from __future__ import annotations

import threading
from typing import Any
from datetime import date, datetime, timedelta, timezone
from ...web import FollowersBody, _creator_rows, logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = (
    "_week", "archive_lock", "archive_state", "creator_db", "get_results", "kpi_config", "ops", "places",
    "read_state", "review_fn", "review_lock", "shipped_days", "start_archive", "store", "teardown_state", "money_days",
)
PROVIDES: tuple[str, ...] = ("get_review",)


def register(app: Any, ctx: Any) -> None:
    _week = ctx._week
    archive_lock = ctx.archive_lock
    archive_state = ctx.archive_state
    creator_db = ctx.creator_db
    get_results = ctx.get_results
    kpi_config = ctx.kpi_config
    ops = ctx.ops
    places = ctx.places
    read_state = ctx.read_state
    review_fn = ctx.review_fn
    review_lock = ctx.review_lock
    shipped_days = ctx.shipped_days
    money_days = ctx.money_days
    start_archive = ctx.start_archive
    store = ctx.store
    teardown_state = ctx.teardown_state
    _load_report = places.load_report
    archive_root = places.archive_root

    @app.get("/api/mine")
    def mine(account_id: int | None = None) -> dict[str, Any]:
        me = store.self_account(account_id) or store.self_account()
        if me is None:
            return {"account": None, "videos": []}
        creator = _creator_rows(creator_db)
        videos = []
        for video in store.videos(me["id"]):
            metrics = creator.get(video["video_id"])
            videos.append({**video, "creator": metrics, **teardown_state(video["video_id"])})
        median = store.account_median(me["id"])
        return {
            "account": {**me, "syncing": me["id"] in ops.syncing or ops.full_sync_running},
            "median_likes": median,
            "videos": videos,
        }
    def _run_review(now_value: datetime) -> None:
        from ... import review

        key = review.week_key(now_value)
        try:
            me = store.self_account()
            if me is None:
                raise review.ReviewError("还没有连接自己的抖音号")
            own = store.videos(me["id"])
            breakouts = store.outliers(float(store.settings()["threshold"]))
            ids = [v["video_id"] for v in own] + [b["video_id"] for b in breakouts]
            reports_by_id = {vid: data for vid in ids if (data := _load_report(vid))}
            inputs = review.gather_inputs(
                own_videos=own, median_likes=store.account_median(me["id"]), creator=_creator_rows(creator_db),
                reports=reports_by_id, topics=store.topics(include_archived=True), breakouts=breakouts, now=now_value,
            )
            inputs["kpi"] = _week_kpi(now_value.astimezone().date())
            data = review.generate_review(inputs, **({"review_fn": review_fn} if review_fn else {}))
            store.set_review(key, state="done", data=data)
        except Exception as exc:  # noqa: BLE001 - shown on the review page
            logger.warning("review %s failed: %s", key, exc)
            store.set_review(key, state="failed", error=str(exc)[:300] or type(exc).__name__)
        finally:
            review_lock.release()

    def _week_kpi(today: date) -> dict[str, Any]:
        """周复盘要看的执行分：出摊几天、私信没回完几天、减了几分，跳过时写的理由（摆出重复的借口）。"""
        from ... import driver

        since = (today - timedelta(days=driver.WINDOW)).isoformat()
        cfg = kpi_config()
        reads = {}
        for i in range(driver.WINDOW):
            d = today - timedelta(days=i)
            ok = read_state(d)[1] if d.isoformat() >= cfg["read_started"] else None
            if ok is not None:
                reads[d.isoformat()] = ok
        days = driver.kpi_days(today, posted=shipped_days(), dms=store.dm_entries(since), started=cfg["started"],
                               x_replies=store.kpi_counts(since, "x_replies"), x_target=int(cfg["x_replies_daily"]),
                               reads=reads, read_started=cfg["read_started"], money=money_days(since), money_started=cfg["money_started"], money_ended=cfg.get("money_ended", "9999"))
        week = _week(driver.week_start(today), today)
        return {
            # 这一周（周一起）发了几条新视频、每周下限、周过完以后少了几条（少一条减 1 分，已经算进 week_demerits）
            "new_videos": week["new_videos"], "new_target": week["new_target"], "new_short": week["new_short"], "week_demerits": week["demerits"],
            "read_missed": sum(d["rd"] == "miss" for d in days),
            "x_missed": sum(d["xr"] == "miss" for d in days),
            "posted": sum(d["ship"] == "ok" for d in days),
            "dm_missed": sum(d["dm"] == "miss" for d in days),
            "money_missed": sum(d["mn"] == "miss" for d in days),
            "demerits": driver.demerits(days),
            "skips": [{"day": r["day"], "what": r["key"], "reason": r["reason"]} for r in store.driver_log(since, "skip")],
        }

    @app.get("/api/review")
    def get_review() -> dict[str, Any]:
        from ... import review

        key = review.week_key(datetime.now(timezone.utc))
        return store.review(key) or {"week": key, "state": "missing", "error": None, "data": None}

    @app.post("/api/review/generate")
    def post_review() -> dict[str, Any]:
        from ... import review

        now_value = datetime.now(timezone.utc)
        if not review_lock.acquire(blocking=False):
            return {"started": False, "message": "复盘正在生成"}
        store.set_review(review.week_key(now_value), state="running")
        threading.Thread(target=_run_review, args=(now_value,), name="review", daemon=True).start()
        return {"started": True, "message": "开始复盘这一周，一般 1–3 分钟"}
    @app.put("/api/followers")
    def put_followers(body: FollowersBody) -> dict[str, Any]:
        """读不到的平台（小红书、视频号、公众号、YouTube）他填一次，之后一直按这个数算。"""
        from ... import followers

        if body.platform not in followers.MANUAL:
            raise ValueError("这个平台的粉丝数是自动读的，不用手填")
        if body.followers < 0:
            raise ValueError("粉丝数不能是负数")
        store.set_followers(date.today().isoformat(), body.platform, body.followers, "manual")
        return get_results()
    @app.get("/api/archive")
    def get_archive() -> dict[str, Any]:
        from ... import archive

        raw = store.settings().get("douyin_archive") or ""
        root = archive_root()
        me = store.self_account()
        videos = [v for v in (store.public_videos(me["id"]) if me else []) if not v["is_image_post"]]
        missing = archive.pending(videos, root)
        with archive_lock:
            progress = dict(archive_state)
        local = sum(1 for v in videos if archive.source_of(root, v["video_id"]) == "local") if root is not None else 0
        return {"path": raw, "available": root is not None, "total": len(videos), "local": local,
                "archived": len(videos) - len(missing) if root is not None else 0, "pending": len(missing), "progress": progress or None}

    @app.post("/api/archive/run")
    def run_archive() -> dict[str, Any]:
        """把没存的全部存下来（第一次补齐用）。之后每次同步会自己补新的。"""
        if archive_root() is None:
            raise ValueError("作品库没配置，或者那块硬盘没插")
        if not start_archive(limit=None):
            raise ValueError("正在存，等这一轮存完")
        return {"started": True}

    ctx.get_review = get_review  # Anna/Wendy 读每周复盘
