"""X 这条线：素材卡片、写建议稿、「发 X」，和每晚排好的每日短帖 / 长帖（10/4–10/8）。试用版没有这一块。"""
from __future__ import annotations

import subprocess
import re
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ... import writing_rules

from ... import outline, vault
from ...paths import config_dir
from ...store import StoreError
from ...web import XLineSkipBody, XLineTextBody, XSuggestBody, logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = (
    "_raw_folder", "_video_transcript", "anna_fn", "daily_original", "data_dir", "drafts_root", "feature_on", "places", "startup", "stop_auto", "store",
    "write_fn", "writer", "x_cover_fn", "x_fetch_fn", "x_illustrate_fn", "x_post_fn",
)
PROVIDES: tuple[str, ...] = ()
# Repost 候选：他那几个领域的榜（创业出海、全部不看：大半是社会新闻）
HOT_CATEGORIES = ("ai", "tech-digital", "knowledge-sharing", "indie-dev")


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    daily_original = ctx.daily_original
    data_dir = ctx.data_dir
    stop_auto = ctx.stop_auto
    store = ctx.store
    drafts_root = Path(ctx.drafts_root)
    _video_transcript_fn = ctx._video_transcript
    _raw_folder_fn = ctx._raw_folder
    vault_path = places.vault_path
    write_fn = ctx.write_fn
    writer = ctx.writer
    x_fetch_fn = ctx.x_fetch_fn
    x_post_fn = ctx.x_post_fn
    x_illustrate_fn = ctx.x_illustrate_fn
    x_cover_fn = ctx.x_cover_fn
    startup = ctx.startup
    turn_fn = ctx.anna_fn  # X 运营和 Anna 走同一个本机 AI 命令；测试里注入假的

    # -- X 单独一条线（10/4） ------------------------------------------------

    from . import x_line

    from ... import rawtidy

    rawtidy.register(app, ctx)

    x_cache = x_line.Cache()
    x_state = data_dir / x_line.STATE_FILE

    @app.get("/api/xline")
    def get_xline(fresh: bool = False) -> dict[str, Any]:
        """三处素材（GitHub、网站、Obsidian）+ 发过的。发过、放一边的卡片前端会藏起来。"""
        st = x_line.load_state(x_state)
        sources = x_line.gather(vault_path(), cache=x_cache, fresh=fresh, **({"fetch": x_fetch_fn} if x_fetch_fn else {}))
        return {"sources": sources, "posts": st["posts"][-50:][::-1], "skipped": st["skipped"],
                "used": sorted({p["source_id"] for p in st["posts"] if p.get("source_id")}),
                "today": x_line.today_count(st["posts"]), "github_user": x_line.github_user(), "site": x_line.site()}

    @app.post("/api/xline/organize")
    def xline_organize(body: XLineTextBody) -> dict[str, Any]:
        """只在 作者 点「整理」时跑：删口语、可调顺序、不改词，拆成几条。"""
        try:
            return {"posts": x_line.organize(body.text, **({"write_fn": write_fn} if write_fn else {}))}
        except (x_line.XLineError, writer.WriterError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/xline/post")
    def xline_post(body: XLineTextBody) -> dict[str, Any]:
        """作者 点了「发到 X」：用他自己的密钥发这一条。不排队、不重试。"""
        from ...x_post import XError, post_tweet

        from . import xhot

        quote = xhot.tweet_id(body.quote_url or "") if body.quote_url else None
        if body.quote_url and not quote:
            raise HTTPException(status_code=400, detail="被引用的那条链接不对")
        try:
            send = x_post_fn or post_tweet
            result = send(body.text, quote_tweet_id=quote) if quote else send(body.text)
        except XError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = x_line.record_post(x_state, text=body.text, source_id=body.source_id, how="quote" if quote else "api", url=result.get("url"))
        store.log_event("x", f"X 发了一条：{body.text.strip()[:30]}")
        return {"post": row}

    @app.post("/api/xline/posted")
    def xline_posted(body: XLineTextBody) -> dict[str, Any]:
        """复制去 X 自己发的（比如超过 280 字的长帖）：发完点一下，记进今天的数。"""
        return {"post": x_line.record_post(x_state, text=body.text, source_id=body.source_id, how="manual")}

    @app.post("/api/xline/suggest")
    def xline_suggest(body: XSuggestBody) -> dict[str, Any]:
        """进项里点了「发 X」（10/5 作者）：他自己的原始输出照原话整理；别人的东西按他的风格写一条建议稿。
        只在他点的时候跑；发不发、怎么改都是他。"""
        from . import x_suggest

        write = write_fn or x_suggest.default_write
        raw = next((src.folder for src in vault.INBOX_SOURCES if src.key == "raw"), x_suggest.RAW_FOLDER)
        if body.kind == "note" and body.path:
            note = vault.read_note(vault_path(), body.path)
            text = (note.get("body") or "").strip()
            sid = x_suggest.source_id("note", body.path)
            if x_suggest.is_own(body.path, raw):
                if not text:
                    raise ValueError("这篇是空的")
                try:
                    posts = x_line.organize(text, write_fn=write)
                except (x_line.XLineError, writer.WriterError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                return {"posts": posts, "own": True, "source_id": sid}
            meta = note.get("meta") or {}
            item = {"title": note.get("title"), "text": text, "url": meta.get("source") or meta.get("url") or "",
                    "author": meta.get("author") or "", "source": body.path.split("/")[0]}
        elif body.kind == "daily" and body.key and body.path and body.item:
            original = daily_original(body.key, body.path, body.item)
            it = original["item"]
            text = "\n\n".join(x for x in (it.get("summary") or "", original.get("deep") or "", original.get("body") or "") if x)
            item = {"title": it.get("title"), "text": text, "url": (it.get("urls") or [""])[0], "author": original["meta"].get("author", ""),
                    "source": f"{it.get('source') or ''}（日报）"}
            sid = x_suggest.source_id("daily", f"{body.key}:{body.item}")
        elif body.kind == "feed" and body.url:
            item = {"title": body.title or "", "text": "", "url": body.url, "author": body.author or "", "source": "抖音视频"}
            sid = x_suggest.source_id("feed", body.url)
        elif body.kind == "xhot" and body.url:
            # X 热榜上别人的帖子。引用帖：原帖跟着引用卡片出来，稿子里不用再贴链接，只写他的判断
            item = {"title": body.title or "", "text": body.text or "", "url": "" if body.quote else body.url, "author": body.author or "",
                    "source": "X 上的帖子（这条是引用帖，原帖会跟着出来）" if body.quote else "X 上的帖子"}
            sid = x_suggest.source_id("xhot", body.url)
        else:
            raise ValueError("不知道要发哪一条")
        try:
            path, style, fresh = x_suggest.ensure_style(vault.vault_root(vault_path()), write)
            post = x_suggest.suggest(item, style=style, beliefs=x_suggest.views(), write_fn=write)
        except (x_suggest.SuggestError, writer.WriterError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"posts": [post], "own": False, "source_id": sid, "style": str(path), "style_new": fresh}

    # -- X 热榜（xhot.py，10/8 作者）：X 页和进项共用一份 ---------------------------------------------

    from . import xhot

    x_hot = xhot.Board(**({"fetch": x_fetch_fn} if x_fetch_fn else {}))

    @app.get("/api/xhot")
    def get_xhot(kind: str = "articles", period: str = "24h", dimension: str | None = None, category: str = "ai",
                 fresh: bool = False) -> dict[str, Any]:
        try:
            board = x_hot.rising(fresh=fresh) if kind == "rising" else x_hot.get(kind, period, dimension, category, fresh=fresh)
        except xhot.HotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**board, "kinds": [{"key": "topics", "label": "热门话题"}, {"key": "articles", "label": "热门长文"}, {"key": "tweets", "label": "热门推文"}],
                "dimensions": {k: list(v) for k, v in xhot.DIMENSIONS.items()},
                "categories": [{"key": k, "label": l} for k, l in xhot.CATEGORIES]}

    # -- X 运营 Agent（xops.py，10/9 作者）：常驻 X 页，不是 作者、也不是 Anna --------------------------

    from . import xops

    xops_perf = xops.Perf(x_fetch_fn or xhot.fetch_json)
    xops_state: dict[str, Any] = {"busy": False, "error": None}
    xops_lock = threading.Lock()

    def _xops_context() -> str:
        from . import x_suggest

        data = x_daily.load(x_daily_path)
        try:
            rising = x_hot.rising().get("items") or []
        except xhot.HotError:
            rising = []
        return xops.context(queue=x_daily.view(x_daily_path, counts=_x_counts(), auto_send=store.settings()["x_auto_send"], flow_now=_flow_now()), counts=_x_counts(),
                            perf=xops_perf.summary(data["days"], x_daily.now_bj().date()), rising=rising, beliefs=x_suggest.views())

    def _xops_turn(message: str, screen: str) -> None:
        from ..team import anna as anna_mod

        try:
            chat = store.anna_chat(xops.THREAD)
            reply = xops.run_turn(ctx_text=_xops_context(), message=message, session_id=chat["session_id"], screen=screen,
                                  turn_fn=turn_fn or (lambda s_, u_, sid: anna_mod.cli_turn(s_, u_, sid)))
            store.append_anna(xops.THREAD, {k: reply[k] for k in ("role", "text", "actions", "at")}, session_id=reply.get("session_id"))
        except Exception as exc:  # noqa: BLE001 - 面板上显示
            logger.warning("xops turn failed: %s", exc)
            with xops_lock:
                xops_state["error"] = str(exc)[:300] or type(exc).__name__
        finally:
            with xops_lock:
                xops_state["busy"] = False

    @app.get("/api/xops")
    def get_xops() -> dict[str, Any]:
        chat = store.anna_chat(xops.THREAD)
        with xops_lock:
            return {"messages": chat["messages"], **xops_state, "role": xops.role_path().name}

    @app.post("/api/xops")
    def post_xops(body: dict[str, Any]) -> dict[str, Any]:
        message = str(body.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="先说点什么")
        if len(message) > 4000:
            raise HTTPException(status_code=400, detail="一次最多 4000 字")
        with xops_lock:
            if xops_state["busy"]:
                return {"started": False, "message": f"{xops.name()} 还在想上一条"}
            xops_state.update(busy=True, error=None)
        store.append_anna(xops.THREAD, {"role": "park", "text": message, "at": xops.now_iso()})
        threading.Thread(target=_xops_turn, args=(message, str(body.get("screen") or "")), name="xops", daemon=True).start()
        return {"started": True}

    @app.delete("/api/xops")
    def delete_xops() -> dict[str, Any]:
        with xops_lock:
            if xops_state["busy"]:
                raise HTTPException(status_code=400, detail=f"{xops.name()} 还在想，等他答完再清")
            xops_state["error"] = None
        store.clear_anna(xops.THREAD)
        return {"ok": True}

    app.state.xops_context = _xops_context

    # AI 草稿经用户确认后才排队，intent 只作为手动入口。
    from . import x_replies

    replies_lock = threading.Lock()
    replies_state: dict[str, Any] = {"busy": False, "error": None}

    def _reply_pool() -> list[dict[str, Any]]:
        """回复候选：正在涨的 + AI 圈 24 小时热门推文（热榜上的帖子大多已经发出 8–24 小时，只看正在涨的几乎选不出来）。"""
        return ((x_hot.rising().get("items") or [])
                + (x_hot.get("tweets", "24h", "reads", "ai").get("items") or [])
                + (x_hot.get("articles", "24h", "reads", "ai").get("items") or []))

    @app.get("/api/xline/replies")
    def get_x_replies() -> dict[str, Any]:
        try:
            result = x_replies.view(_reply_pool(), settings=store.settings())
        except xhot.HotError as exc:
            result = {**x_replies.view([], settings=store.settings()), "source_error": str(exc)}
        with replies_lock:
            return {**result, **replies_state}

    def _reply_drafts(limit: int = 30, *, auto: bool = False, now=None) -> None:
        from ..team import anna as anna_mod

        try:
            # 只读现有风格；这里不采集 vault、不自动生成规则。
            style = x_replies.load_style(store.settings())
            if auto:
                x_replies.auto_draft(_reply_pool(), settings=store.settings(), soul=xops.soul()["text"], style=style,
                                     vault_root=vault.vault_root(vault_path()),
                                     turn_fn=turn_fn or anna_mod.cli_turn, now=now)
            else:
                x_replies.draft(_reply_pool(), soul=xops.soul()["text"], style=style, vault_root=vault.vault_root(vault_path()),
                                turn_fn=turn_fn or anna_mod.cli_turn, limit=limit)
        except Exception as exc:  # 后台错误留给页面重试
            logger.warning("x replies draft: %s", exc)
            with replies_lock:
                replies_state["error"] = ("找不到 X 写作风格.md，请先配置写作风格" if isinstance(exc, FileNotFoundError)
                                          else str(exc)[:300] or type(exc).__name__)
        finally:
            with replies_lock:
                replies_state["busy"] = False

    @app.post("/api/xline/replies/draft")
    def draft_x_replies(body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            limit = int((body or {}).get("limit", 30))
            if not 1 <= limit <= 30:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="每批写 1–30 条") from exc
        with replies_lock:
            if replies_state["busy"]:
                return {"started": False}
            replies_state.update(busy=True, error=None)
        threading.Thread(target=_reply_drafts, args=(limit,), name="x-replies", daemon=True).start()
        return {"started": True}

    @app.post("/api/xline/replies/approve-all")
    def approve_x_replies(body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return {"approved": x_replies.approve_all(edits=(body or {}).get("edits"))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/xline/replies/retry-api")
    def retry_x_reply_api() -> dict[str, Any]:
        x_replies.retry_api()
        return {"ok": True}

    @app.post("/api/xline/replies/{tweet_id}/handed")
    def hand_x_reply(tweet_id: str) -> dict[str, Any]:
        try:
            return {"reply": x_replies.handed(tweet_id)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/xline/replies/{tweet_id}")
    def mark_x_reply(tweet_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"reply": x_replies.mark(tweet_id, body.get("state"), text=body.get("text"))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/xhot/save")
    def save_xhot(body: dict[str, Any]) -> dict[str, Any]:
        """「收进进项」：存一篇笔记进「我收藏的」，进项里就能看到、能入选题池。"""
        folder = next((s.folder for s in vault.INBOX_SOURCES if s.key == "saved"), None)
        if not folder:
            raise HTTPException(status_code=400, detail="设置里还没配「我收藏的」文件夹")
        try:
            path, new = xhot.save(vault.vault_root(vault_path()) / folder, body)
        except (xhot.HotError, vault.VaultError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if new:
            store.log_event("input", f"X 热榜收进进项：{str(body.get('title') or '')[:30]}")
        return {"path": f"{folder}/{path.name}", "new": new}

    # -- X 每日短帖（x_daily.py，10/5 作者）：Wendy 前一晚排好，早上打勾，勾了的当天排着发 ------------------

    from . import post_review, topic_article, topic_script, write_flow, write_module, write_patch, write_steps, x_daily, x_qa

    x_daily_path = x_daily.path()
    from . import x_live

    live_sampler = x_live.HourlySampler()

    @app.get("/api/xline/live")
    def get_x_live() -> dict[str, Any]:
        return {**x_live.live(store.path, x_daily_path, settings=store.settings(),
                              analytics_root=config_dir() / "x-analytics"),
                "halted_message": x_replies.stop_message()}

    def _x_live_tick(*, now=None, get=None):
        return live_sampler.tick(store, now=now, get=get)

    def _x_daily_on() -> bool:
        """X 每天排短帖、长文、引用、回复那套开不开：试用版 / 设置 · 流程里关了 xline，或 10/19 作者 关掉（设置 x_daily）都算关。
        实时数据（_x_live_loop）不看这个，照常读。"""
        return ctx.feature_on("xline") and bool(store.settings().get("x_daily"))

    def _x_live_loop() -> None:
        while not stop_auto.is_set():
            if ctx.feature_on("xline"):
                _x_live_tick()
            stop_auto.wait(60)

    def _x_replies_tick(*, now=None):
        from ...x_post import post_tweet

        result = x_replies.tick(post_fn=x_post_fn or post_tweet, settings=store.settings(), now=now)
        if result:
            message = x_replies.stop_message(now=now)
            store.log_event("x", message or f"X 回复：{result.get('state')} {result.get('reply_url') or result.get('error') or ''}")
        return result

    def _x_replies_auto_draft(*, now=None) -> bool:
        with replies_lock:
            if replies_state["busy"] or not x_replies.auto_draft_due(settings=store.settings(), now=now):
                return False
            replies_state.update(busy=True, error=None)
        threading.Thread(target=_reply_drafts, kwargs={"auto": True, "now": now},
                         name="x-replies-auto", daemon=True).start()
        return True

    def _x_replies_loop() -> None:
        x_replies.recover_sending()
        while not stop_auto.is_set():
            if _x_daily_on():
                try:
                    _x_replies_tick()
                    _x_replies_auto_draft()
                except Exception as exc:
                    logger.warning("x replies tick: %s", exc)
            stop_auto.wait(30)

    app.state.x_live_tick = _x_live_tick
    app.state.x_daily_on = _x_daily_on
    app.state.x_replies_tick = _x_replies_tick
    app.state.x_replies_auto_draft = _x_replies_auto_draft
    x_daily_run: dict[str, Any] = {"planning": None, "error": None, "failed_day": None, "hot_busy": False, "hot_error": None, "merging": None,
                                   "topup_busy": False}

    def _video_notes() -> set[str]:
        """被选题（视频）用作素材、还在压着的笔记：先不进长帖（10/8 作者：拍成视频的也可以发，但是要过一段时间）。"""
        return x_daily.held_video_notes(store.topics(include_archived=True))

    def _read_full(sid: str) -> str:
        return vault.read_note(vault_path(), sid.removeprefix("obsidian:")).get("body") or ""

    def _x_articles() -> int:
        return int(_x_counts().get("articles", x_daily.VALUE_PER_DAY))

    def _x_counts() -> dict[str, Any]:
        """每天发多少（设置里的 x_counts，10/9 作者：不写死）。"""
        return store.settings()["x_counts"]

    def _x_daily_plan(key: str, *, short: bool = True) -> None:
        x_daily_run.update(planning=key, error=None, failed_day=None)
        try:
            st = x_line.load_state(x_state)
            sources = x_line.gather(vault_path(), cache=x_cache, **({"fetch": x_fetch_fn} if x_fetch_fn else {}))
            counts = _x_counts()
            n_article, n_post = x_daily.split_counts(counts)
            x_daily.plan(x_daily_path, key, sources=sources, skipped=set(st["skipped"]),
                         posted={p["source_id"] for p in st["posts"] if p.get("source_id")},
                         write_fn=write_fn or writer.cli_write, short=short, long_avoid=_video_notes(), read_full=_read_full,
                         n=int(counts.get("own_short", 50)), n_long=n_article, n_post=n_post)
            store.log_event("x", f"{xops.name()} 排好了 {key} 的 X：长文 {n_article} 篇、长帖 {n_post} 条")
        except Exception as exc:  # noqa: BLE001 - 页面显示
            logger.warning("x daily plan %s: %s", key, exc)
            x_daily_run.update(error=str(exc)[:300] or type(exc).__name__, failed_day=key)  # 这一天不再自己重试，等他点
        finally:
            x_daily_run["planning"] = None

    def _x_make_picks(key: str) -> None:
        st = x_line.load_state(x_state)
        sources = x_line.gather(vault_path(), cache=x_cache, **({"fetch": x_fetch_fn} if x_fetch_fn else {}))
        with x_daily._LOCK:
            data = x_daily.load(x_daily_path)
            avoid = x_daily.picked_sources(data) | set(st["skipped"]) | _video_notes()
        notes = x_daily.long_candidates(sources, avoid=avoid, read_full=_read_full, n=x_daily.PICKS_PER_DAY)
        x_daily.add_picks(x_daily_path, key, notes)
        x_daily.fill_articles(x_daily_path, key, want=_x_articles())  # 价值线：工作台挑前几篇做成长文
        logger.info("x picks %s: %s", key, len(notes))

    def _x_short_topup(n: int) -> None:
        try:
            st = x_line.load_state(x_state)
            sources = x_line.gather(vault_path(), cache=x_cache, **({"fetch": x_fetch_fn} if x_fetch_fn else {}))
            key = x_daily.day_key(x_daily.now_bj())
            from . import x_suggest

            made = x_daily.topup_shorts(x_daily_path, key, sources=sources, skipped=set(st["skipped"]),
                                        posted={p["source_id"] for p in st["posts"] if p.get("source_id")},
                                        write_fn=write_fn or writer.cli_write, n=n,
                                        style=x_replies.load_style(store.settings()), check_fn=x_suggest.check)
            logger.info("x short topup %s: asked %s made %s", key, n, made)
        except Exception as exc:  # noqa: BLE001 - 下一轮再来
            logger.warning("x short topup: %s", exc)
        finally:
            x_daily_run["topup_busy"] = False

    def _x_daily_record(row: dict[str, Any]) -> None:
        x_line.record_post(x_state, text=row["text"], source_id=row.get("source_id"), how=row.get("how") or "queue", url=row.get("url"))
        store.log_event("x", f"X 发了一条（你早上勾过的）：{row['text'][:30]}")

    def _x_send(text: str, *, long: bool = False, post: dict[str, Any] | None = None, quote_url: str | None = None) -> dict[str, Any]:
        """短帖照旧发推文；热点短帖发成引用帖；长文写回 article.md，发成 X 图文文章。X 只让存草稿就算没发成（去 X 点一下再「我发了」）。"""
        from ...x_post import XError, post_tweet

        if quote_url:
            qid = xhot.tweet_id(quote_url)
            if not qid:
                raise XError("被引用的那条链接不对")
            return post_tweet(text, quote_tweet_id=qid)
        if not long:
            return post_tweet(text)
        if (post or {}).get("format") == "post":  # 长帖：一条纯文字长 post（Premium 最长 25,000）
            return post_tweet(text.lstrip("# ").strip(), long=True)
        from . import x_article

        article = Path(str((post or {}).get("article") or ""))
        if not article.parent.is_dir():
            raise XError("这篇长文的文件夹不见了，点「重做」")
        article.write_text(text.rstrip() + "\n", encoding="utf-8")
        cover = article.parent / "x-cover.png"  # 10/10：作者 形象 + 红色的封面；没出成就退回纯文字横幅
        result = x_article.publish_article(article, publish=True, cover=cover if cover.is_file() else None)
        if not result.get("published"):
            raise XError(result.get("message") or "X 只存了草稿：去 X 的文章草稿里点发布，回来点「我发了」")
        return {"url": result.get("url")}

    def _pct_setting() -> int:
        return write_module.clamp_pct(store.settings()["write_flow"].get("max_change_pct", 20))

    def _module(trk: dict[str, Any] | None = None) -> Any:
        """读 park-writing 的清单，改动预算用他在页面上定的：这一篇自己改过的，否则设置里的默认（20%）。"""
        return write_module.load(max_change_pct=(trk or {}).get("max_pct") or _pct_setting())

    def _flow_pick(post: dict[str, Any] | None = None) -> tuple[Any, str, list[str]]:
        """这一篇走哪个流程：文章上选过的，没有就是设置里的默认；返回 (清单, 流程名, 步骤 id)。清单有问题直接抛 ModuleError。"""
        module = _module((post or {}).get("trk"))
        saved = store.settings()["write_flow"]
        name = (post or {}).get("flow_name") or saved["default"]
        if name in module.flows:
            return module, name, list(module.flows[name])
        if name in saved["custom"]:
            return module, name, [i for i in saved["custom"][name] if i in module.steps]
        first = next(iter(module.flows))
        return module, first, list(module.flows[first])

    def _summary_wanted(post: dict[str, Any], when: Any) -> bool:
        """带日期的 summary 只在补发的老笔记上写（10/12 作者）：写作日期早于 7 天；今天写的新内容不写。卡片上能手动开关。"""
        mode = post.get("summary_mode")
        if mode in ("on", "off"):
            return mode == "on"
        return bool(when and (x_daily.now_bj().date() - when).days > 7)

    def _flow_for(post: dict[str, Any]) -> dict[str, Any] | None:
        """装了带清单的 park-writing 才按清单做；没装走老的整理。清单读不懂：这一步不运行，原因给 作者 看。"""
        if not write_module.available():
            return None
        try:
            module, name, ids = _flow_pick(post)
        except write_module.ModuleError as exc:
            raise RuntimeError(f"park-writing 的 module.yaml 有问题，这一步没运行：\n{exc}") from exc
        return {"module": module, "name": name, "ids": ids}

    def x_long_prep(key: str, post: dict[str, Any]) -> None:
        """做一篇长文：读整篇笔记 → park-writing 改 → 配图。做完 prep=ready，做不成 failed + 原因。"""
        from ... import illustrate
        from . import x_long

        x_daily.set_post(x_daily_path, key, post["id"], prep="running", prep_error=None, qa=None, qa_before=None,
                         qa_changes=None, qa_dropped=None, trk=None, prep_at=x_daily.now_bj().isoformat(timespec="seconds"))
        try:
            if post.get("compiled"):  # 主题合集：他的原话按编号排好了，不改写、不写 summary，只配图
                path = x_long.folder(post["id"]) / x_long.ARTICLE
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(post["text"].rstrip() + "\n", encoding="utf-8")
                (x_illustrate_fn or illustrate.illustrate)(path)
                x_daily.set_post(x_daily_path, key, post["id"], prep="ready", text=path.read_text(encoding="utf-8"), article=str(path))
                store.log_event("x", f"{key} 的合集长文配好图了，等你看：{post['text'].splitlines()[0].lstrip('# ')[:30]}")
                return
            raw = vault.read_note(vault_path(), post["source_id"].removeprefix("obsidian:"))
            note = x_line.plain(raw.get("body") or "")
            run = _flow_for(post)  # 装了带清单的 park-writing：第一轮一次调用，打分 + 修改清单；清单有问题直接报错，不装作跑了
            when0 = x_long.written_on(str(post.get("source_id") or ""), raw.get("meta"))
            want_summary = _summary_wanted(post, when0) if run else True
            first: dict[str, Any] = {}

            def by_patch(title: str, original: str) -> str:
                base = f"# {title}\n\n{original.strip()}\n"
                first.update(base=base, result=write_patch.run_round1(run["module"], run["ids"], base, write_fn=write_fn or writer.cli_write))
                return base  # 正文不动：修改是清单，等他逐条接受

            text, path, when = x_long.prepare(post, note, write_fn=write_fn or writer.cli_write, meta=raw.get("meta"),
                                              illustrate_fn=x_illustrate_fn or illustrate.illustrate,
                                              steps_fn=by_patch if run else None, summary=want_summary)
            extra: dict[str, Any] = {"trk": None, "flow_run": None}
            if run:
                parts = write_steps.split_article(text, summary=want_summary)
                trk = write_patch.build_trk(first["result"], first["base"], parts, when=write_steps.now_iso(),
                                            pct=run["module"].constraints["max-change-pct"])
                trk["flow"] = run["name"]
                trk["ids"] = run["ids"]
                text = x_daily.trk_render_text({"trk": trk})
                path.write_text(text, encoding="utf-8")
                extra = {"trk": trk, "flow_run": None}
        except Exception as exc:  # noqa: BLE001 - 卡片上显示，等他点「重做」
            logger.warning("x long prep %s: %s", post["id"], exc)
            x_daily.set_post(x_daily_path, key, post["id"], prep="failed", prep_error=str(exc)[:300] or type(exc).__name__)
            return
        x_daily.set_post(x_daily_path, key, post["id"], prep="ready", text=text, article=str(path),
                         summary=want_summary, written_on=when.isoformat() if when else None,
                         flow_prep={"skill": write_flow.skill_version()}, **extra)
        store.log_event("x", f"{key} 的长文做好了，等你看：{text.splitlines()[0].lstrip('# ')[:30]}")

    def x_long_add_summary(key: str, post: dict[str, Any]) -> None:
        """10/9 之前做好、还没勾的长文：只补开头那段 summary，不重新改写、不重新配图。补不上记下原因，不反复试。"""
        from . import x_long

        try:
            raw = vault.read_note(vault_path(), post["source_id"].removeprefix("obsidian:"))
            note, meta = x_line.plain(raw.get("body") or ""), raw.get("meta")
            when = x_long.written_on(post["source_id"], meta)
            title = post["text"].split("\n", 1)[0].lstrip("# ").strip()
            text = x_long.with_summary(post["text"], x_long.summarize(title, note, when=when, context=x_long.context_of(meta),
                                                                       write_fn=write_fn or writer.cli_write))
        except Exception as exc:  # noqa: BLE001
            logger.warning("x long summary %s: %s", post["id"], exc)
            x_daily.set_post(x_daily_path, key, post["id"], summary=False, summary_error=str(exc)[:300])
            return
        if post.get("article"):
            Path(post["article"]).write_text(text, encoding="utf-8")
        x_daily.set_post(x_daily_path, key, post["id"], text=text, summary=True, written_on=when.isoformat() if when else None)

    def x_long_rewrite_summary(key: str, post: dict[str, Any]) -> dict[str, Any]:
        """只重写 summary：重新读笔记的日期和内容，换掉标题下面那一段，正文和配图不动。"""
        from . import x_long

        raw = vault.read_note(vault_path(), post["source_id"].removeprefix("obsidian:"))
        note, meta = x_line.plain(raw.get("body") or ""), raw.get("meta")
        when = x_long.written_on(post["source_id"], meta)
        title = post["text"].split("\n", 1)[0].lstrip("# ").strip()
        summary = x_long.summarize(title, note, when=when, context=x_long.context_of(meta), write_fn=write_fn or writer.cli_write)
        text = x_long.replace_summary(post["text"], summary) if post.get("summary") else x_long.with_summary(post["text"], summary)
        if post.get("article"):
            Path(post["article"]).write_text(text, encoding="utf-8")
        return x_daily.set_post(x_daily_path, key, post["id"], text=text, summary=True, summary_error=None,
                                written_on=when.isoformat() if when else None)

    @app.post("/api/xline/daily/{key}/{post_id}/summary")
    def rewrite_x_long_summary(key: str, post_id: str) -> dict[str, Any]:
        """10/9 作者：长文的 summary 单独能重写（比如笔记补了日期），正文和配图不动。一次半分钟左右。"""
        from . import x_long

        post = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if not post or not post.get("long") or post.get("prep") != "ready" or post["state"] not in ("pending", "approved") or post.get("swapped"):
            raise HTTPException(status_code=400, detail="这一篇现在不能重写 summary")
        try:
            return {"post": x_long_rewrite_summary(key, post)}
        except (x_long.LongError, writer.WriterError, vault.VaultError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def x_long_cover(key: str, post: dict[str, Any], headline: str | None = None) -> None:
        """出这篇长文的封面：没给标题就先按「标题.md」写几个封面标题、用第一条；再用他的形象出图。出不来不挡发文。"""
        from ... import titles
        from . import x_cover_ip, x_long

        x_daily.set_post(x_daily_path, key, post["id"], cover="running", cover_error=None)
        try:
            title = post["text"].split("\n", 1)[0].lstrip("# ").strip()
            options = post.get("cover_titles") or []
            if not headline:
                options = x_cover_ip.headlines(title, post["text"], write_fn=write_fn or writer.cli_write, framework=titles.load_framework())
                headline = options[0]["title"]
            x_cover_ip.draw(x_long.post_folder(post), headline, **({"runner": x_cover_fn} if x_cover_fn else {}))
        except Exception as exc:  # noqa: BLE001 - 卡片上显示，等他点「重做封面」
            logger.warning("x long cover %s: %s", post["id"], exc)
            x_daily.set_post(x_daily_path, key, post["id"], cover="failed", cover_error=str(exc)[:300] or type(exc).__name__,
                             **({"cover_titles": options} if options else {}))
            return
        x_daily.set_post(x_daily_path, key, post["id"], cover="ready", cover_title=headline, cover_titles=options)
        store.log_event("x", f"{key} 的长文封面出好了：{headline}")

    @app.post("/api/xline/daily/{key}/{post_id}/cover")
    def redo_x_long_cover(key: str, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """「重做封面」：用他选的那条标题（或自己改的）重新出图；不给标题就重新写标题再出。后台跑，几分钟。"""
        post = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if not post or not post.get("long") or post.get("format") == "post" or post.get("prep") != "ready" \
                or post["state"] not in ("pending", "approved") or post.get("swapped"):
            raise HTTPException(status_code=400, detail="这一篇现在不能出封面")
        if post.get("cover") == "running":
            return {"started": False, "message": "封面正在出"}
        headline = str(body.get("title") or "").strip() or None
        if headline and len(headline) > 30:
            raise HTTPException(status_code=400, detail="封面标题太长了，30 个字以内")
        x_daily.set_post(x_daily_path, key, post_id, cover="running", cover_error=None)
        threading.Thread(target=x_long_cover, args=(key, post, headline), name="x-cover", daemon=True).start()
        return {"started": True, "message": "在出封面，几分钟"}

    app.state.x_long_cover = x_long_cover

    def qa_rules_response(*, include_bundled: bool = False) -> dict[str, Any]:
        rules = x_qa.load_rules()
        path = Path(rules["path"]).resolve()
        workflows = outline.workflows_dir().resolve()
        rules["resettable"] = (writing_rules.skill_dir() is None and not rules["bundled"] and path == (config_dir() / x_qa.RULES_FILE).resolve()
                               and not (workflows != outline.DEFAULT_WORKFLOWS.resolve()
                                        and path == workflows / x_qa.RULES_FILE))
        if include_bundled:
            rules["bundled_text"] = x_qa.bundled_rules()
        return rules

    @app.get("/api/xline/qa-rules")
    def get_x_qa_rules() -> dict[str, Any]:
        try:
            return qa_rules_response(include_bundled=True)
        except x_qa.QAError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/xline/qa-rules")
    def put_x_qa_rules(body: XLineTextBody) -> dict[str, Any]:
        text = body.text.strip()
        if len(text) < 20 or len(text) > 20000:
            raise HTTPException(status_code=400, detail="规则太短" if len(text) < 20 else "规则太长")
        try:
            path = x_qa.save_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
            store.log_event("x", "改了 X 发前 QA 规则")
            return qa_rules_response()
        except (OSError, x_qa.QAError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/xline/qa-rules")
    def reset_x_qa_rules() -> dict[str, Any]:
        try:
            rules = qa_rules_response()
            if not rules["resettable"]:
                raise HTTPException(status_code=400, detail="这份在你的规则文件夹里，去那里删" if not rules["bundled"] else "已经是自带的通用版")
            Path(rules["path"]).unlink()
            return qa_rules_response()
        except (OSError, x_qa.QAError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _flow_now() -> dict[str, Any]:
        """每一步现在该用的规则版本，页面拿它和文章上记的比，看哪些是旧规则跑的。"""
        from . import x_qa

        try:
            qa_hash = x_qa.rules_hash(x_qa.load_rules()["text"])
        except Exception:  # noqa: BLE001 - 读不到规则就不比 QA 那几步
            qa_hash = None
        module = None
        if write_module.available():
            try:
                module = write_module.load()
            except write_module.ModuleError:
                module = None  # 清单有问题时页面按老的步骤表画，设置页会显示原因
        return write_flow.current(qa_hash, x_qa.VERSION, module, _pct_setting())

    def _complete_on_fail() -> str:
        """清单里「完整度」这一步不过怎么办。没装带清单的 skill 就是只标红。"""
        if not write_module.available():
            return "warn"
        try:
            step = write_module.load().steps.get("check-complete")
        except write_module.ModuleError:
            return "warn"
        return step.on_fail if step else "warn"

    def x_long_qa(key: str, post: dict[str, Any]) -> None:
        """10/10 作者：发之前过一遍 QA——错字、读不通、没讲完的结尾。只按单子改那几处，改了什么页面上逐条列出来，能一键还原。"""
        from . import x_qa

        with x_daily._LOCK:
            fresh = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post["id"]), None)
            if fresh is None or fresh["state"] not in ("pending", "approved"):
                return
            x_daily.set_post(x_daily_path, key, post["id"], qa="running", qa_error=None,
                             **({"state": "pending", "decided_at": None} if fresh.get("auto") else {}))
        trk = fresh.get("trk")
        seen = trk["base"] if trk else fresh["text"]  # 带修改清单的：QA 看他的原文，它的改动并进清单
        try:
            rules = x_qa.load_rules()["text"]
            source = "、".join(str(fresh.get(k)) for k in ("source_kind", "source_title") if fresh.get(k))
            if fresh.get("hot"):
                source = "他对一条正在火的帖子的看法（引用帖，原帖会跟着显示）"
            has_intro = (any(c["reason"] == "导语" and c["status"] in ("accepted", "edited") for c in trk["changes"])
                         if trk else bool(fresh.get("intro")))
            result = x_qa.run(seen, kind="短帖" if not fresh.get("long") else "长帖" if fresh.get("format") == "post" else "长文", write_fn=write_fn or writer.cli_write,
                              summary=False if trk else bool(fresh.get("summary")), source=source, has_intro=has_intro, rules=rules, short=not fresh.get("long"))
        except Exception as exc:  # noqa: BLE001 - QA 不成不挡发：原文照旧，卡片上写原因
            logger.warning("x qa %s: %s", post["id"], exc)
            x_daily.apply_qa(x_daily_path, key, post["id"], seen=seen, error=str(exc) or type(exc).__name__, version=x_qa.VERSION)
            return
        done = x_daily.apply_qa(x_daily_path, key, post["id"], seen=seen, result=result, version=x_qa.VERSION,
                                rules_hash=x_qa.rules_hash(rules), auto_send=store.settings()["x_auto_send"],
                                complete_on_fail=_complete_on_fail(),
                                change_cap=(trk or {}).get("max_pct") or _pct_setting())
        if done.get("qa") == "ready" and result["changes"]:
            store.log_event("x", f"{key} QA 改了 {len(result['changes'])} 处：{seen.splitlines()[0].lstrip('# ')[:30]}")

    @app.post("/api/xline/daily/{key}/{post_id}/qa/rerun")
    def rerun_x_qa(key: str, post_id: str) -> dict[str, Any]:
        """「用新规则重跑」：这一篇的检查重新排队，后台循环下一轮就跑，不动正文。"""
        try:
            return {"post": x_daily.rerun_qa(x_daily_path, key, post_id)}
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _save_article(post: dict[str, Any]) -> None:
        if post.get("article") and Path(post["article"]).parent.is_dir():
            Path(post["article"]).write_text(post["text"], encoding="utf-8")

    # 批注视图的「处理修改」X 的文章和加工中的口播稿共用一套：差别只在文字和清单存在哪（target）。
    class _TrkError(Exception):
        pass

    class _XTarget:
        kind = "x"

        def __init__(self, key: str, post_id: str) -> None:
            self.key, self.post_id = key, post_id

        def get(self) -> dict[str, Any] | None:
            return next((x for x in x_daily.load(x_daily_path)["days"].get(self.key, {}).get("posts", []) if x["id"] == self.post_id), None)

        def update(self, fn: Callable[[dict[str, Any]], None], label: str | None = None) -> dict[str, Any]:
            try:
                return x_daily.trk_update(x_daily_path, self.key, self.post_id, fn, label)
            except x_daily.DailyError as exc:
                raise _TrkError(str(exc)) from exc

        def saved(self, post: dict[str, Any]) -> None:
            _save_article(post)

        def module(self, trk: dict[str, Any] | None) -> Any:
            return _module(trk)

    class _TopicTarget:
        kind = "topic"

        def __init__(self, topic_id: int) -> None:
            self.topic_id = topic_id

        def get(self) -> dict[str, Any] | None:
            return topic_script.read(drafts_root, self.topic_id)

        def update(self, fn: Callable[[dict[str, Any]], None], label: str | None = None) -> dict[str, Any]:
            try:
                return topic_script.update(drafts_root, self.topic_id, fn, label)
            except topic_script.ScriptError as exc:
                raise _TrkError(str(exc)) from exc

        def saved(self, post: dict[str, Any]) -> None:
            return None

        def module(self, trk: dict[str, Any] | None) -> Any:
            return _module(trk)

    class _ArticleTarget:
        """「标题和封面」那篇 X 图文文章（10/13 作者：润色走批注视图，不再整篇重写）。"""
        kind = "article"

        def __init__(self, topic_id: int) -> None:
            self.topic_id = topic_id

        def path(self) -> Path | None:
            raw = store.topic(self.topic_id).get("article_path")
            return Path(raw) if raw else None

        def get(self) -> dict[str, Any] | None:
            path = self.path()
            return topic_article.read(path) if path else None

        def update(self, fn: Callable[[dict[str, Any]], None], label: str | None = None) -> dict[str, Any]:
            path = self.path()
            if path is None:
                raise _TrkError("这一条还没有文章")
            try:
                return topic_article.update(path, fn, label)
            except topic_article.ArticleError as exc:
                raise _TrkError(str(exc)) from exc

        def saved(self, post: dict[str, Any]) -> None:
            return None

        def module(self, trk: dict[str, Any] | None) -> Any:
            return _module(trk)

    def _http(exc: _TrkError, code: int = 400) -> HTTPException:
        return HTTPException(status_code=code, detail=str(exc))

    def _t_start_rescore(t: Any) -> bool:
        """给现在的文字重新打六项分（后台，一两分钟）。已经在打就不重复。返回有没有开始。"""
        started = {"v": False}

        def mark(trk: dict[str, Any]) -> None:
            if not trk.get("rescoring"):
                trk.update(rescoring=True, rescore_error=None)
                started["v"] = True

        try:
            t.update(mark)
        except _TrkError:
            return False
        if not started["v"]:
            return False

        def work() -> None:
            try:
                fresh = t.get()
                module = t.module(fresh.get("trk"))
                scores = write_patch.rescore(module, fresh["trk"].get("ids") or [], fresh["text"], write_fn=write_fn or writer.cli_write)
                t.update(lambda trk: trk.update(rescoring=False, scores={**trk["scores"], "after": scores, "after_at": write_steps.now_iso(), "stale": False}))
            except Exception as exc:  # noqa: BLE001 - 页面上写原因
                logger.warning("trk rescore %s: %s", getattr(t, "post_id", getattr(t, "topic_id", "?")), exc)
                try:
                    t.update(lambda trk: trk.update(rescoring=False, rescore_error=str(exc)[:200] or type(exc).__name__))
                except _TrkError:
                    pass

        threading.Thread(target=work, name="trk-rescore", daemon=True).start()
        return True

    def _t_auto_rescore(t: Any, post: dict[str, Any]) -> None:
        """修改都处理完了就自动重新打分（他说的：点了「全部接受」应该马上给分）；已经是最新的不重打。"""
        trk = post.get("trk") or {}
        if write_patch.pending_edits(trk.get("changes", [])) or trk.get("rescoring"):
            return
        sc = trk.get("scores") or {}
        if sc.get("after") and not sc.get("stale"):
            return
        if write_module.available():
            _t_start_rescore(t)

    def _t_after(t: Any, post: dict[str, Any]) -> dict[str, Any]:
        t.saved(post)
        _t_auto_rescore(t, post)
        return t.get() or post

    def _t_status(t: Any, cid: str, body: dict[str, Any]) -> dict[str, Any]:
        edit = body.get("edit")
        status = str(body.get("status") or "")
        label = {"accepted": "接受一处", "rejected": "不要一处", "edited": "改了一处", "pending": "放回待处理", "resolved": "评论标已读"}.get(status, status)
        return _t_after(t, t.update(lambda trk: write_patch.set_status(trk["changes"], cid, status, None if edit is None else str(edit)), label))

    def _t_all(t: Any, body: dict[str, Any]) -> dict[str, Any]:
        which = str(body.get("all") or "")
        label = {"accepted": "全部接受", "rejected": "全部不要", "reset": "全部还原", "restore": "不保存，退回打开时"}.get(which, which)
        if which == "restore":  # 「不保存，关闭」：回到打开批注视图时的样子（这一步本身也能撤销）
            snap = body.get("snapshot")
            post = t.update(lambda trk: write_patch.restore(trk, snap), label)
            if isinstance(snap, dict) and snap.get("scores_fresh") and (post["trk"].get("scores") or {}).get("after"):
                post = t.update(lambda trk: trk["scores"].update(stale=False))  # 文字和打开时一样：打开时的分还算数，不白打一次
            return _t_after(t, post)
        return _t_after(t, t.update(lambda trk: write_patch.set_all(trk["changes"], which), label))

    def _t_undo(t: Any) -> tuple[dict[str, Any], str | None]:
        done: dict[str, str] = {}
        post = t.update(lambda trk: done.update(label=write_patch.undo(trk)))
        t.saved(post)
        return post, done.get("label")

    def _t_budget(t: Any, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        raw = body.get("pct")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 1 <= int(raw) <= write_module.MAX_CHANGE_PCT:
            raise HTTPException(status_code=400, detail=f"预算要在 1% 到 {write_module.MAX_CHANGE_PCT}% 之间")
        added = {"n": 0}
        post = t.update(lambda trk: added.update(n=write_patch.apply_budget(trk, int(raw))), f"改预算到 {int(raw)}%")
        return _t_after(t, post), added["n"]

    @app.post("/api/xline/daily/{key}/{post_id}/trk/rescore")
    def rescore_x_trk(key: str, post_id: str) -> dict[str, Any]:
        """处理完修改以后再打一次分（也会在修改都处理完时自动打）。后台，一两分钟。"""
        t = _XTarget(key, post_id)
        post = t.get()
        if not post or not post.get("trk"):
            raise HTTPException(status_code=400, detail="这一篇没有修改清单")
        if post["trk"].get("rescoring"):
            raise HTTPException(status_code=409, detail="正在打分，等一下")
        if not _t_start_rescore(t):
            raise HTTPException(status_code=400, detail="现在不能打分")
        return {"started": True, "message": "在重新打分，一两分钟"}

    @app.post("/api/xline/daily/{key}/{post_id}/trk/summary")
    def toggle_x_trk_summary(key: str, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """带日期的 summary 开关（补发的老笔记才默认写）。开：立刻记下「要写」，后台写一段，写好之前页面上勾着、显示在写；
        关：去掉。写失败了才把勾拿掉并说原因。"""
        from . import x_long

        on = bool(body.get("on"))
        post = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if not post or not post.get("trk"):
            raise HTTPException(status_code=400, detail="这一篇没有修改清单")
        if post.get("summary_busy"):
            raise HTTPException(status_code=409, detail="summary 正在写，等一下")
        if not on:
            try:
                row = x_daily.trk_update(x_daily_path, key, post_id, lambda t: t["parts"].update(summary=None))
            except x_daily.DailyError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            row = x_daily.set_post(x_daily_path, key, post_id, summary=False, summary_mode="off", summary_error=None)
            _save_article(row)
            return {"started": False, "post": row}
        x_daily.set_post(x_daily_path, key, post_id, summary_mode="on", summary_busy=True, summary_error=None)

        def work() -> None:
            try:
                raw = vault.read_note(vault_path(), post["source_id"].removeprefix("obsidian:"))
                note, meta = x_line.plain(raw.get("body") or ""), raw.get("meta")
                when = x_long.written_on(post["source_id"], meta)
                title = post["trk"]["parts"]["title"].lstrip("# ").strip()
                summary = x_long.summarize(title, note, when=when, context=x_long.context_of(meta), write_fn=write_fn or writer.cli_write)
                row = x_daily.trk_update(x_daily_path, key, post_id, lambda t: t["parts"].update(summary=summary.strip()))
                row = x_daily.set_post(x_daily_path, key, post_id, summary=True, summary_busy=False, summary_error=None,
                                       written_on=when.isoformat() if when else None)
                _save_article(row)
            except Exception as exc:  # noqa: BLE001
                logger.warning("x trk summary %s: %s", post_id, exc)
                x_daily.set_post(x_daily_path, key, post_id, summary=False, summary_mode="off", summary_busy=False,
                                 summary_error=str(exc)[:200] or type(exc).__name__)

        threading.Thread(target=work, name="x-trk-summary", daemon=True).start()
        return {"started": True, "message": "在写带日期的 summary，一两分钟"}

    @app.post("/api/xline/daily/{key}/{post_id}/trk")
    def set_all_x_trk(key: str, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """全部接受 / 全部不要（只动还没处理的修改）/ 全部还原成待处理。"""
        try:
            return {"post": _t_all(_XTarget(key, post_id), body)}
        except _TrkError as exc:
            raise _http(exc) from exc

    @app.post("/api/xline/daily/{key}/{post_id}/trk/budget")
    def set_x_trk_budget(key: str, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """这一篇的改动预算（%）。调高：「没放进来」的按顺序放进来；调低：已有的修改不动（接受过的不会被撤销），只是不再放新的。"""
        try:
            post, added = _t_budget(_XTarget(key, post_id), body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"post": post, "added": added}

    @app.post("/api/xline/daily/{key}/{post_id}/trk/undo")
    def undo_x_trk(key: str, post_id: str) -> dict[str, Any]:
        """撤销上一步处理（接受、不要、改字、全部接受…），一直能撤到最早一步。"""
        try:
            post, label = _t_undo(_XTarget(key, post_id))
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"post": post, "undone": label}

    @app.post("/api/xline/daily/{key}/{post_id}/trk/{cid}")
    def set_x_trk(key: str, post_id: str, cid: str, body: dict[str, Any]) -> dict[str, Any]:
        """批注视图上处理一处修改：接受 / 不要 / 用我改的 / 放回待处理。"""
        try:
            return {"post": _t_status(_XTarget(key, post_id), cid, body)}
        except _TrkError as exc:
            raise _http(exc) from exc

    # -- 加工中的口播稿（10/12 作者）：付息稿 / 他自己贴的 / 拍完的逐字稿，走同一个批注视图 ------------------------
    script_run: dict[int, dict[str, Any]] = {}
    script_lock = threading.Lock()

    def _topic_or_404(topic_id: int) -> dict[str, Any]:
        try:
            return store.topic(topic_id)
        except Exception as exc:  # noqa: BLE001 - 找不到就是 404
            raise HTTPException(status_code=404, detail="找不到这条视频") from exc

    # 口述、复刻存档时笔记里夹的一行说明（给骨架当标记用的），不是他念的话，不能进口播稿
    archive_note = re.compile(r"^>.*下面每一句都是我（作者）自己说的话.*$", re.M)

    def _own_note_text(topic: dict[str, Any]) -> str:
        """这条内容挂的、在他原始输出文件夹里的笔记：他自己的话，原样拼起来（只去掉存档时夹的那一行说明）。"""
        prefix = _raw_folder_fn().strip("/") + "/"
        parts = []
        for path in topic.get("note_paths") or []:
            if not str(path).startswith(prefix):
                continue
            try:
                body = (vault.read_note(vault_path(), path).get("body") or "").strip()
            except Exception:  # noqa: BLE001 - 读不到的跳过
                continue
            body = re.sub(r"\n{3,}", "\n\n", archive_note.sub("", body)).strip()
            if body:
                parts.append(body)
        return "\n\n".join(parts)

    def _review_items() -> list[dict[str, Any]]:
        """park-writing 评判清单里的每一项：口播稿页画总评用。reasons = 它的修改在清单里标的原因；second = 第一轮不打（错字、导语）。
        清单读不了或老版本没有 review：空，页面退回原来的打分。"""
        try:
            module = _module(None)
        except write_module.ModuleError:
            return []
        out = []
        for item in module.review:
            out.append({"id": item.id, "title": item.title,
                        "reasons": [write_patch.STEP_REASON[s] for s in item.steps if s in write_patch.STEP_REASON],
                        "second": all(module.steps[s].round == 2 for s in item.steps)})
        return out

    def _script_view(topic_id: int) -> dict[str, Any]:
        from ... import coupon, outline

        topic = _topic_or_404(topic_id)
        cur = topic_script.read(drafts_root, topic_id)
        if cur:
            cur["trk"]["pct_effective"] = cur["trk"].get("max_pct") or _pct_setting()
        run = script_run.get(topic_id) or {}
        try:
            transcript = bool(_video_transcript_fn(topic))
        except Exception:  # noqa: BLE001 - 读不到就当没有
            transcript = False
        from ... import schedule as schedule_mod

        return {"running": bool(run.get("running")), "stage": run.get("stage"), "error": run.get("error"), "script": cur,
                "review": _review_items(),
                "has": {"note": bool(_own_note_text(topic)), "coupon": bool(coupon.read_coupon(drafts_root, topic_id)),
                        "skeleton": bool(outline.read_outline(topic)), "transcript": transcript},
                "mode": schedule_mod.content_mode(topic, _raw_folder_fn(), drafts_root),
                "title": topic.get("title"), "available": write_module.available()}

    def _script_work(topic_id: int, source: str, pasted: str, raise_errors: bool = False) -> None:
        from ... import coupon, outline

        said = None

        def stage(name: str) -> None:
            script_run[topic_id] = {"running": True, "stage": name, "error": None}

        try:
            topic = store.topic(topic_id)
            stage("准备")
            module, name, ids = _flow_pick(None)
            fn = write_fn or writer.cli_write
            if source == "coupon":
                coupon_md = (coupon.read_coupon(drafts_root, topic_id) or {}).get("markdown", "")
                skeleton = (outline.read_outline(topic) or {}).get("markdown", "")
                if not coupon_md and not skeleton:
                    raise topic_script.ScriptError("先写骨架（和密度），口播稿是照它们整理的")
                stage("把付息稿整理成口播逐字稿")
                sources = writer.topic_sources(str(vault_path()), topic, drafts_root)
                base = topic_script.generate(topic, coupon=coupon_md, skeleton=skeleton, sources=sources,
                                             style_rules=module.step_text("style") if module.steps.get("style") and module.steps["style"].runnable else "",
                                             write_fn=fn)
            elif source == "note":  # 10/12 作者：已经有他自己的话：原话就是底稿，不重写、不压缩
                text = _own_note_text(topic)
                if len(re.sub(r"\s+", "", text)) < topic_script.MIN_CHARS:
                    raise topic_script.ScriptError("这条没有挂你原始输出里的笔记，或者太短")
                base = topic_script.base_from(str(topic.get("title") or "口播稿"), text)
            elif source == "paste":
                if len(re.sub(r"\s+", "", pasted)) < topic_script.MIN_CHARS:
                    raise topic_script.ScriptError(f"贴进来的稿子太短，不到 {topic_script.MIN_CHARS} 字")
                base = topic_script.base_from(str(topic.get("title") or "口播稿"), pasted)
            else:
                text = _video_transcript_fn(topic)
                if len(re.sub(r"\s+", "", text)) < topic_script.MIN_CHARS:
                    raise topic_script.ScriptError("这条视频还没有转写的逐字稿，或者太短")
                base = topic_script.base_from(str(topic.get("title") or "口播稿"), text)
                said = post_review.transcript_hash(text)  # 记下用的是哪一版逐字稿：重录了才重做
            stage("打分、提修改清单")
            result = write_patch.run_round1(module, ids, base, write_fn=fn)
            trk = write_patch.build_trk(result, base, topic_script.parts_for(base), when=write_steps.now_iso(),
                                        pct=module.constraints["max-change-pct"])
            trk.update(flow=name, ids=ids, source=source)
            if source == "transcript":
                trk["transcript_hash"] = said
            topic_script.save_new(drafts_root, topic_id, trk)
            script_run[topic_id] = {"running": False, "stage": None, "error": None}
            store.log_event("x", f"《{str(topic.get('title') or '')[:24]}》的口播稿好了，等你处理修改", topic_id)
        except Exception as exc:  # noqa: BLE001 - 页面上写原因
            logger.warning("topic script %s: %s", topic_id, exc)
            script_run[topic_id] = {"running": False, "stage": None, "error": str(exc)[:300] or type(exc).__name__}
            if raise_errors:
                raise

    def _prep_hold(topic_id: int) -> str | None:
        """一条做完再备下一条：正在做的那条没发完，别的选题不出口播稿（web.py 里的 _prep_hold）。"""
        ask = getattr(app.state, "prep_hold", None)
        return ask(topic_id) if ask else None

    def _script_claim(topic_id: int) -> bool:
        with script_lock:
            if (script_run.get(topic_id) or {}).get("running"):
                return False
            script_run[topic_id] = {"running": True, "stage": "准备", "error": None}
            return True

    def _script_run_sync(topic_id: int, source: str) -> None:
        """排期「准备稿子」一包一包跑：同步做完，失败抛出来让排期记下。"""
        hold = _prep_hold(topic_id)
        if hold:
            raise topic_script.ScriptError(hold)
        if not _script_claim(topic_id):
            raise topic_script.ScriptError("这一条的口播稿正在做")
        _script_work(topic_id, source, "", raise_errors=True)

    def _script_start(topic_id: int, source: str) -> dict[str, Any]:
        """说完了（「你说一遍」存好）就在后台开始：原话走第一轮。"""
        hold = _prep_hold(topic_id)
        if hold:
            return {"started": False, "message": hold}
        if not _script_claim(topic_id):
            return {"started": False, "message": "正在做"}
        threading.Thread(target=_script_work, args=(topic_id, source, ""), name=f"topic-script-{topic_id}", daemon=True).start()
        return {"started": True, "message": "在用你的原话做口播稿，几分钟"}

    def _script_auto(topic_id: int) -> dict[str, Any]:
        """10/19 作者：拍完视频进来，口播稿就该已经在那儿——逐字稿是他的原话，自动走第一轮，不用再点「开始」。

        视频放进项目、whisper 转写完、关联已有项目、打开口播稿页签时都会调；该做才做：
        已经是这一版逐字稿做的就不动；拍前的稿子（原话 / 付息稿 / 贴的）或上一次录的逐字稿换成这一次说的，
        旧的留 .bak；同一版逐字稿失败过就不自动重试（页面上有原因，他自己点）。"""
        topic = _topic_or_404(topic_id)
        try:
            text = str(_video_transcript_fn(topic) or "")
        except Exception:  # noqa: BLE001 - 读不到就当没有
            text = ""
        if len(re.sub(r"\s+", "", text)) < topic_script.MIN_CHARS:
            return {"started": False, "message": "还没有逐字稿"}
        if not write_module.available():
            return {"started": False, "message": "这台机器没有带清单的 park-writing"}
        said = post_review.transcript_hash(text)
        cur = topic_script.read(drafts_root, topic_id)
        if cur and cur["trk"].get("source") == "transcript" and cur["trk"].get("transcript_hash") in (said, None):
            return {"started": False, "message": "口播稿已经是这一版逐字稿"}
        run = script_run.get(topic_id) or {}
        if run.get("error") and run.get("auto_hash") == said:
            return {"started": False, "message": run["error"]}
        hold = _prep_hold(topic_id)
        if hold:
            return {"started": False, "message": hold}
        if not _script_claim(topic_id):
            return {"started": False, "message": "正在做"}
        if cur:
            keep = topic_script.folder(drafts_root, topic_id)
            for name in (topic_script.SCRIPT, topic_script.TRK):
                if (keep / name).is_file():
                    (keep / f"{name}.bak").write_bytes((keep / name).read_bytes())

        def work() -> None:
            _script_work(topic_id, "transcript", "")
            if (script_run.get(topic_id) or {}).get("error"):
                script_run[topic_id] = {**script_run[topic_id], "auto_hash": said}

        threading.Thread(target=work, name=f"topic-script-auto-{topic_id}", daemon=True).start()
        return {"started": True, "message": "在用拍完的逐字稿做口播稿，几分钟" + ("（拍前的稿子留了备份）" if cur else "")}

    app.state.topic_script_auto = _script_auto
    app.state.topic_script_ready = write_module.available
    app.state.topic_script_run = _script_run_sync
    app.state.topic_script_start = _script_start

    @app.get("/api/topics/{topic_id}/script")
    def get_topic_script(topic_id: int) -> dict[str, Any]:
        try:  # 视频已经在项目里、逐字稿还没变成口播稿（比如今天以前放进来的）：打开就补上
            _script_auto(topic_id)
        except Exception as exc:  # noqa: BLE001 - 补不上不影响看
            logger.warning("topic script auto %s: %s", topic_id, exc)
        return _script_view(topic_id)

    @app.post("/api/topics/{topic_id}/script")
    def start_topic_script(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """生成口播稿并提第一轮修改。source: coupon（付息稿整理成口语逐字稿）/ paste（他自己贴的）/ transcript（拍完的逐字稿）。
        已经有他处理过的修改时，要 force 才重来（重来会清掉他处理过的）。后台，几分钟。"""
        topic = _topic_or_404(topic_id)
        hold = _prep_hold(topic_id)
        if hold:
            raise HTTPException(status_code=409, detail=hold)
        source = str(body.get("source") or "coupon")
        if source not in topic_script.SOURCES:
            raise HTTPException(status_code=400, detail="来源只能是付息稿、贴进来的稿子、拍完的逐字稿")
        if not write_module.available():
            raise HTTPException(status_code=400, detail="这台机器没有带清单的 park-writing，没法走写作流程")
        try:
            _flow_pick(None)
        except write_module.ModuleError as exc:
            raise HTTPException(status_code=400, detail=f"park-writing 的 module.yaml 有问题，没运行：\n{exc}") from exc
        cur = topic_script.read(drafts_root, topic_id)
        handled = write_patch.handled_count(cur["trk"]) if cur else 0
        if handled and not body.get("force"):
            raise HTTPException(status_code=409, detail=f"重新生成会清掉你已经处理的 {handled} 处修改，确定的话再点一次")
        with script_lock:
            if (script_run.get(topic_id) or {}).get("running"):
                raise HTTPException(status_code=409, detail="正在生成，等它做完")
            script_run[topic_id] = {"running": True, "stage": "准备", "error": None}
        if cur:  # 他确认过要重来：旧的留一份备份，不直接丢
            base = topic_script.folder(drafts_root, topic_id)
            for name in (topic_script.SCRIPT, topic_script.TRK):
                if (base / name).is_file():
                    (base / f"{name}.bak").write_bytes((base / name).read_bytes())
        threading.Thread(target=_script_work, args=(topic_id, source, str(body.get("text") or "")), name=f"topic-script-{topic_id}", daemon=True).start()
        return {"started": True, "message": "在做口播稿，几分钟"}

    @app.post("/api/topics/{topic_id}/script/trk/rescore")
    def rescore_topic_script(topic_id: int) -> dict[str, Any]:
        t = _TopicTarget(topic_id)
        cur = t.get()
        if not cur:
            raise HTTPException(status_code=400, detail="这一条还没有口播稿")
        if cur["trk"].get("rescoring"):
            raise HTTPException(status_code=409, detail="正在打分，等一下")
        if not _t_start_rescore(t):
            raise HTTPException(status_code=400, detail="现在不能打分")
        return {"started": True, "message": "在重新打分，一两分钟"}

    @app.post("/api/topics/{topic_id}/script/trk/budget")
    def budget_topic_script(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        try:
            _, added = _t_budget(_TopicTarget(topic_id), body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"script": _script_view(topic_id)["script"], "added": added}

    @app.post("/api/topics/{topic_id}/script/trk/undo")
    def undo_topic_script(topic_id: int) -> dict[str, Any]:
        try:
            _, label = _t_undo(_TopicTarget(topic_id))
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"script": _script_view(topic_id)["script"], "undone": label}

    @app.post("/api/topics/{topic_id}/script/trk")
    def all_topic_script(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        try:
            _t_all(_TopicTarget(topic_id), body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"script": _script_view(topic_id)["script"]}

    @app.post("/api/topics/{topic_id}/script/trk/{cid}")
    def status_topic_script(topic_id: int, cid: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            _t_status(_TopicTarget(topic_id), cid, body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"script": _script_view(topic_id)["script"]}

    # -- 拍后批注（10/13 作者）：字幕放进项目就自动出，只打分、只批注，写成「下一条要注意的」----------------------------
    review_run: dict[int, dict[str, Any]] = {}
    review_lock = threading.Lock()

    def _review_transcript(topic: dict[str, Any]) -> str:
        try:
            return str(_video_transcript_fn(topic) or "")
        except Exception:  # noqa: BLE001 - 读不到就当没有字幕
            return ""

    def _review_view(topic_id: int) -> dict[str, Any]:
        topic = _topic_or_404(topic_id)
        text = _review_transcript(topic)
        has = len(re.sub(r"\s+", "", text)) >= post_review.MIN_CHARS
        cur = post_review.read(drafts_root, topic_id)
        run = review_run.get(topic_id) or {}
        h = post_review.transcript_hash(text) if has else None
        try:
            ready = bool(_module(None).post_shoot and _module(None).review)
        except write_module.ModuleError:
            ready = False
        failed_here = bool(run.get("error")) and run.get("hash") == h
        return {"running": bool(run.get("running")), "error": run.get("error"), "review": cur, "has_transcript": has,
                "stale": bool(cur and h and cur.get("hash") != h), "available": write_module.available() and ready,
                "title": topic.get("title"),
                "can_auto": bool(ready and has and not run.get("running") and not failed_here and not (cur and cur.get("hash") == h))}

    def _review_work(topic_id: int, text: str) -> None:
        h = post_review.transcript_hash(text)
        try:
            module = _module(None)
            result = post_review.run(module, text, write_fn=write_fn or writer.cli_write)
            post_review.save(drafts_root, topic_id, {**result, "hash": h, "created_at": write_steps.now_iso(),
                                                      "title": str(store.topic(topic_id).get("title") or ""),
                                                      "items": [{"id": i.id, "title": i.title} for i in module.review]})
            review_run[topic_id] = {"running": False, "error": None, "hash": h}
            store.log_event("x", f"《{str(store.topic(topic_id).get('title') or '')[:24]}》的拍后批注好了", topic_id)
        except Exception as exc:  # noqa: BLE001 - 页面上写原因
            logger.warning("post-shoot review %s: %s", topic_id, exc)
            review_run[topic_id] = {"running": False, "error": str(exc)[:300] or type(exc).__name__, "hash": h}

    def _review_start(topic_id: int, force: bool = False, wait: bool = False) -> dict[str, Any]:
        """字幕放进项目（或打开「拍后」页签）时调：没有字幕、清单里没有评判清单、同一份字幕已经批注过（没点重来）就不动。"""
        topic = _topic_or_404(topic_id)
        text = _review_transcript(topic)
        if len(re.sub(r"\s+", "", text)) < post_review.MIN_CHARS:
            return {"started": False, "message": "还没有字幕"}
        cur = post_review.read(drafts_root, topic_id)
        if cur and cur.get("hash") == post_review.transcript_hash(text) and not force:
            return {"started": False, "message": "这份字幕已经批注过了"}
        with review_lock:
            if (review_run.get(topic_id) or {}).get("running"):
                return {"started": False, "message": "正在批注"}
            review_run[topic_id] = {"running": True, "error": None, "hash": post_review.transcript_hash(text)}
        if wait:
            _review_work(topic_id, text)
        else:
            threading.Thread(target=_review_work, args=(topic_id, text), name=f"post-review-{topic_id}", daemon=True).start()
        return {"started": True, "message": "在做拍后批注，一两分钟"}

    app.state.topic_review_start = _review_start

    @app.get("/api/topics/{topic_id}/review")
    def get_topic_review(topic_id: int) -> dict[str, Any]:
        return _review_view(topic_id)

    @app.post("/api/topics/{topic_id}/review")
    def start_topic_review(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        if not _review_view(topic_id)["available"]:
            raise HTTPException(status_code=400, detail="这台机器的 park-writing 清单里还没有评判清单和拍后批注，先更新它")
        return _review_start(topic_id, force=bool(body.get("force")))

    @app.get("/api/review/latest")
    def latest_review(exclude: int | None = None) -> dict[str, Any]:
        """下一条口述前提醒：最近一条拍后批注里的「下一条要注意的」，跳过正在做的这条。"""
        return {"review": post_review.latest(drafts_root, exclude)}

    # -- 「标题和封面」那篇文章的润色：第一轮打分 + 修改清单，批注视图逐条处理（10/13 作者）-------------------------
    polish_run: dict[int, dict[str, Any]] = {}

    def _polish_view(topic_id: int) -> dict[str, Any]:
        topic = _topic_or_404(topic_id)
        cur = _ArticleTarget(topic_id).get()
        if cur:
            cur["trk"]["pct_effective"] = cur["trk"].get("max_pct") or _pct_setting()
        run = polish_run.get(topic_id) or {}
        return {"running": bool(run.get("running")), "stage": run.get("stage"), "error": run.get("error"), "polish": cur,
                "title": topic.get("title"), "available": write_module.available()}

    def _polish_work(topic_id: int, article: Path, original: str) -> None:
        try:
            module, name, ids = _flow_pick(None)
            base, parts = topic_article.split(original)
            polish_run[topic_id] = {"running": True, "stage": "打分、提修改清单", "error": None}
            result = write_patch.run_round1(module, ids, base, write_fn=write_fn or writer.cli_write)
            trk = write_patch.build_trk(result, base, parts, when=write_steps.now_iso(), pct=module.constraints["max-change-pct"])
            trk.update(flow=name, ids=ids, source="article")
            topic_article.save_new(article, trk, original=original)
            polish_run[topic_id] = {"running": False, "stage": None, "error": None}
            store.log_event("copy", f"《{str(store.topic(topic_id).get('title') or '')[:24]}》的文章打好分、提好修改了，等你处理", topic_id)
        except Exception as exc:  # noqa: BLE001 - 页面上写原因
            logger.warning("article polish %s: %s", topic_id, exc)
            polish_run[topic_id] = {"running": False, "stage": None, "error": str(exc)[:300] or type(exc).__name__}

    @app.get("/api/topics/{topic_id}/polish")
    def get_topic_polish(topic_id: int) -> dict[str, Any]:
        return _polish_view(topic_id)

    @app.post("/api/topics/{topic_id}/polish")
    def start_polish(topic_id: int, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """润色（10/2 起有这个按钮；10/13 改）：对现在的文章跑第一轮，打分、提修改清单，不改原文，他在批注视图里逐条处理。
        已经有他处理过的修改时，要 force 才重来（重来会清掉他处理过的）。后台，几分钟。"""
        body = body or {}
        topic = _topic_or_404(topic_id)
        article = Path(topic["article_path"]) if topic.get("article_path") else None
        if article is None or not article.is_file():
            raise HTTPException(status_code=400, detail="还没有文章，先写好再润色")
        if topic.get("write_state") == "running":
            raise HTTPException(status_code=409, detail="这篇文章正在写，写完再润色")
        if not write_module.available():
            raise HTTPException(status_code=400, detail="这台机器没有带清单的 park-writing，没法走写作流程")
        try:
            _flow_pick(None)
        except write_module.ModuleError as exc:
            raise HTTPException(status_code=400, detail=f"park-writing 的 module.yaml 有问题，没运行：\n{exc}") from exc
        original = article.read_text(encoding="utf-8")
        if len(re.sub(r"\s+", "", topic_article.split(original)[0])) < topic_article.MIN_CHARS:
            raise HTTPException(status_code=400, detail=f"文章正文不到 {topic_article.MIN_CHARS} 字，没什么可润色的")
        cur = topic_article.read(article)
        handled = write_patch.handled_count(cur["trk"]) if cur else 0
        if handled and not body.get("force"):
            raise HTTPException(status_code=409, detail=f"重新润色会清掉你已经处理的 {handled} 处修改（接受了的会留在文章里），确定的话再点一次")
        with script_lock:
            if (polish_run.get(topic_id) or {}).get("running"):
                raise HTTPException(status_code=409, detail="正在润色，等它做完")
            polish_run[topic_id] = {"running": True, "stage": "准备", "error": None}
        threading.Thread(target=_polish_work, args=(topic_id, article, original), name=f"polish-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始润色：先打分，再在你的原文上提修改，你逐条接受。几分钟"}

    @app.post("/api/topics/{topic_id}/polish/trk/rescore")
    def rescore_topic_polish(topic_id: int) -> dict[str, Any]:
        t = _ArticleTarget(topic_id)
        cur = t.get()
        if not cur:
            raise HTTPException(status_code=400, detail="这篇文章没有在润色")
        if cur["trk"].get("rescoring"):
            raise HTTPException(status_code=409, detail="正在打分，等一下")
        if not _t_start_rescore(t):
            raise HTTPException(status_code=400, detail="现在不能打分")
        return {"started": True, "message": "在重新打分，一两分钟"}

    @app.post("/api/topics/{topic_id}/polish/trk/budget")
    def budget_topic_polish(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        try:
            _, added = _t_budget(_ArticleTarget(topic_id), body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"polish": _polish_view(topic_id)["polish"], "added": added}

    @app.post("/api/topics/{topic_id}/polish/trk/undo")
    def undo_topic_polish(topic_id: int) -> dict[str, Any]:
        try:
            _, label = _t_undo(_ArticleTarget(topic_id))
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"polish": _polish_view(topic_id)["polish"], "undone": label}

    @app.post("/api/topics/{topic_id}/polish/trk")
    def all_topic_polish(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        try:
            _t_all(_ArticleTarget(topic_id), body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"polish": _polish_view(topic_id)["polish"]}

    @app.post("/api/topics/{topic_id}/polish/trk/{cid}")
    def status_topic_polish(topic_id: int, cid: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            _t_status(_ArticleTarget(topic_id), cid, body)
        except _TrkError as exc:
            raise _http(exc) from exc
        return {"polish": _polish_view(topic_id)["polish"]}

    @app.post("/api/xline/daily/{key}/{post_id}/qa/revert")
    def revert_x_qa(key: str, post_id: str) -> dict[str, Any]:
        """QA 改的不要：回到他自己的原文。"""
        try:
            return {"post": x_daily.revert_qa(x_daily_path, key, post_id)}
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    app.state.x_long_qa = x_long_qa

    def _x_long_loop() -> None:
        """一篇一篇做，做完一篇马上看下一篇；没活就半分钟看一次。"""
        while not stop_auto.is_set():
            if not _x_daily_on():  # 关了就不改长文、不出插图
                stop_auto.wait(60)
                continue
            try:
                job = x_daily.split_next(x_daily_path)
                if job:  # 他点了「拆解」：先拆，几分钟内短帖就进自动发
                    made = x_daily.split_pick(x_daily_path, job[0], job[1]["id"], write_fn=write_fn or writer.cli_write)
                    store.log_event("x", f"《{job[1]['title'][:30]}》拆成了 {made} 条短帖，过 QA 就发")
                    continue
                job = x_daily.prep_next(x_daily_path)
                if job:
                    x_long_prep(*job)
                    continue
                job = x_daily.summary_next(x_daily_path)
                if job:
                    x_long_add_summary(*job)
                    continue
                try:
                    current_rules_hash = x_qa.rules_hash(x_qa.load_rules()["text"])
                except x_qa.QAError:
                    current_rules_hash = None
                job = x_daily.qa_next(x_daily_path, qa_version=x_qa.VERSION, rules_hash=current_rules_hash)
                if job:
                    x_long_qa(*job)
                    continue
                job = x_daily.cover_next(x_daily_path)
                if job:
                    x_long_cover(*job)
                    continue
                job = x_daily.merge_next(x_daily_path)
                if job:
                    try:
                        x_long_merge(*job)
                    finally:
                        x_daily_run["merging"] = None
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("x long loop: %s", exc)
            stop_auto.wait(30)

    def x_long_merge(key: str, posts: list[dict[str, Any]]) -> None:
        """10/12 作者：价值不够的几篇找共同主题拼一篇（rawtidy 那套：按段落引用拼、衔接 ≤5%、覆盖 ≥90%；只生成文字，不动笔记）。"""
        from ... import rawtidy

        notes = []
        for post in posts:
            sid = str(post.get("source_id") or "")
            body = ""
            if sid.startswith("obsidian:") or sid.endswith(".md"):
                try:
                    note = vault.read_note(vault_path(), sid.removeprefix("obsidian:"))
                    body, title = note.get("body") or "", note.get("title") or x_daily.long_title(sid.rsplit("/", 1)[-1])
                except Exception:  # noqa: BLE001 - 读不到就用队列里那份
                    body = ""
            if not body:  # 长帖（短句合并）、读不到的笔记：用队列里的正文，去掉标题行
                lines = post["text"].strip().split("\n", 1)
                title, body = lines[0].lstrip("# ").strip(), (lines[1] if len(lines) > 1 else "")
            if body.strip():
                notes.append({"path": sid or post["id"], "title": title, "body": body.strip(), "_post": post["id"]})
        tried = [p["id"] for p in posts]
        x_daily_run["merging"] = key  # 页面上「正在拼」
        try:
            groups = rawtidy.propose(notes, write_fn=write_fn or writer.cli_write, limit=1) if len(notes) >= 2 else []
            group = next((g for g in groups if g.get("status") == "ready" and g["type"] == "merge"), None)
            reason = "" if group else "; ".join(g.get("reason", "") for g in groups) or "拼不出共同主题"
        except Exception as exc:  # noqa: BLE001 - 下一批再说
            group, reason = None, str(exc)
        if group:  # 合并稿记的是来源路径；队列里那几篇按 source_id 对回去
            group = {**group, "sources": [{"path": n["path"]} for n in group["sources"]]}
        row = x_daily.add_merged(x_daily_path, key, tried, group, reason=reason)
        x_daily_run["merging"] = None
        logger.info("x long merge %s: %s", key, f"made {row['id']} from {row['merged_from']}" if row else f"failed: {reason}")
        if row:
            store.log_event("x", f"{xops.name()} 把 {len(row['merged_from'])} 篇价值不够的拼成一篇：{row['source_title'][:30]}")

    def _x_topup(keys: list[str]) -> None:
        """10/9 作者「从现在开始……已经排好的内容也重新 rearrange」：改了每天数量，已经排好的日子按新数量补齐。"""
        try:
            st = x_line.load_state(x_state)
            sources = x_line.gather(vault_path(), cache=x_cache, **({"fetch": x_fetch_fn} if x_fetch_fn else {}))
            avoid = {p["source_id"] for p in st["posts"] if p.get("source_id")} | set(st["skipped"]) | _video_notes()
            n_article, n_post = x_daily.split_counts(_x_counts())
            for key in keys:
                try:
                    x_daily.topup(x_daily_path, key, sources=sources, avoid=avoid, read_full=_read_full,
                                  write_fn=write_fn or writer.cli_write, n_article=n_article, n_post=n_post)
                except x_daily.DailyError as exc:
                    logger.warning("x topup %s: %s", key, exc)
                    x_daily.set_target(x_daily_path, key, [n_article, n_post])  # 素材不够也算补过，不每分钟重试
            store.log_event("x", f"按每天长文 {n_article} 篇、长帖 {n_post} 篇，补齐了 {len(keys)} 天")
        except Exception as exc:  # noqa: BLE001
            logger.warning("x topup: %s", exc)
        finally:
            x_daily_run["topup_busy"] = False

    app.state.x_topup = _x_topup

    def _x_hot_batch(key: str, n: int) -> None:
        """写一批热点短帖草稿：持续在涨里今天还没看过的，X 运营挑他有观点的写引用帖。他打了勾才发。"""
        from . import x_suggest

        cands: list[dict[str, Any]] = []
        report: dict[str, Any] = {}
        try:
            seen = x_daily.hot_seen(x_daily_path, key)
            # 持续在涨里大半是社会新闻，他没观点的都会被跳过；再加上他那几个领域 24 小时的推文和长文，候选多一些
            # （10/13 Repost 每天 100 条：只看 AI 一类时一次只有 70 多条候选，早上一批就看掉一半）
            pool = list(x_hot.rising().get("items") or [])
            for cat in HOT_CATEGORIES:
                for kind in ("tweets", "articles"):
                    try:
                        pool += x_hot.get(kind, "24h", "reads", cat).get("items") or []
                    except Exception as exc:  # noqa: BLE001 - 一个榜读不到不挡别的
                        logger.info("x hot %s %s: %s", kind, cat, exc)
            cands = list({x["url"]: x for x in pool if x.get("url") and x["url"] not in seen}.values())[: n * 4]
            try:  # 每条配上他原始输出里最贴的几句原话（repost 优先用原话）
                lines = x_replies.raw_lines(vault.vault_root(vault_path()))
                cands = [{**c, "park_lines": [m["text"] for m in x_replies.match_lines(str(c.get("text") or c.get("title") or ""), lines, k=4)]} for c in cands]
            except Exception as exc:  # noqa: BLE001 - 找不到原话就只写暴论
                logger.info("x hot park lines: %s", exc)
            if cands:
                write = write_fn or x_suggest.default_write
                _, style, _ = x_suggest.ensure_style(vault.vault_root(vault_path()), write)
                report: dict[str, Any] = {}
                drafts = x_daily.build_hot(cands, n=n, style=style, beliefs=x_suggest.views(), write_fn=write,
                                           check_fn=lambda t, it: x_suggest.check(t, it, limit=x_daily.MAX_LONG), report=report)
            else:
                drafts = []
            x_daily.add_hot(x_daily_path, key, drafts, [c["url"] for c in cands],
                            note=None if drafts else (
                                f"{x_daily.now_bj().strftime('%H:%M')} 这一批写了 {report.get('found', 0)} 条都没过检查（{'；'.join(dict.fromkeys(report.get('drops') or []))[:80]}）"
                                if report.get("found") else
                                f"{x_daily.now_bj().strftime('%H:%M')} 这一批看了 {len(cands)} 条正在涨的，都和你的领域无关，没写"))
            logger.info("x hot batch %s: looked %s wrote %s", key, len(cands), len(drafts))
            store.log_event("x", f"X 运营写了 {len(drafts)} 条引用（看了 {len(cands)} 条持续在涨的），过 QA 就发")
        except Exception as exc:  # noqa: BLE001 - 页面显示；这一批算写过，2 小时后再来
            logger.warning("x hot batch: %s", exc)
            x_daily_run["hot_error"] = str(exc)[:300] or type(exc).__name__
            x_daily.add_hot(x_daily_path, key, [], [])
        finally:
            x_daily_run["hot_busy"] = False

    def _x_hot_start(n: int) -> None:
        x_daily_run.update(hot_busy=True, hot_error=None)
        threading.Thread(target=_x_hot_batch, args=(x_daily.day_key(x_daily.now_bj()), n), name="x-hot", daemon=True).start()

    @app.post("/api/xline/hot")
    def x_hot_now() -> dict[str, Any]:
        """「现在写一批」：不等 2 小时；今天写的还是不超过每天上限。"""
        cap = int(_x_counts().get("hot", 0))
        today = x_daily.load(x_daily_path)["days"].get(x_daily.day_key(x_daily.now_bj())) or {"posts": []}
        n = min(x_daily.HOT_BATCH, cap - sum(1 for x in today["posts"] if x.get("hot")))
        if x_daily_run["hot_busy"]:
            return {"started": False, "message": f"{xops.name()} 正在写这一批"}
        if n <= 0:
            return {"started": False, "message": f"今天的热点短帖已经写满 {cap} 条了（每天上限在上面改）"}
        _x_hot_start(n)
        return {"started": True, "message": f"{xops.name()} 在从持续在涨里挑、写最多 {n} 条，一两分钟"}

    app.state.x_hot_batch = _x_hot_batch

    def _x_daily_loop() -> None:

        with x_daily._LOCK:
            data = x_daily.load(x_daily_path)
            if x_daily.unsure_after_restart(data):
                x_daily.save(x_daily_path, data)
        while not stop_auto.is_set():
            if not _x_daily_on():  # 试用版、「设置 · 流程」里关了、或 10/19 起的 x_daily 关着：不排、不发，也不花 AI 额度
                stop_auto.wait(60)
                continue
            try:
                key = x_daily.plan_due(x_daily_path, own_short=0)  # 10/12 晚：短帖白天按暴论补（topup），晚上不再排原话短帖
                if key and not x_daily_run["planning"] and x_daily_run["failed_day"] != key:
                    _x_daily_plan(key, short=False)
                # 长帖提前排满 7 天（#507）：不经过模型，排得快；一天排坏了不挡后面的
                for later in x_daily.long_days_due(x_daily_path):
                    if x_daily_run["planning"] or x_daily_run["failed_day"] == later:
                        break
                    _x_daily_plan(later, short=False)
                _x_daily_retire_videos()
                counts = _x_counts()
                if int(counts.get("own_short", 50)) <= 0:
                    x_daily.cancel_shorts(x_daily_path, x_daily.day_key(x_daily.now_bj()))
                due = x_daily.topup_due(x_daily_path, list(x_daily.split_counts(counts)))
                if due and not x_daily_run["topup_busy"]:
                    x_daily_run["topup_busy"] = True
                    threading.Thread(target=_x_topup, args=(due,), name="x-topup", daemon=True).start()
                # 10/12 作者：每天 10 篇候选（发文 / 长帖 / 拆解 / 不发），读笔记不调模型，很快
                pick_day = x_daily.picks_due(x_daily_path)
                if pick_day:
                    _x_make_picks(pick_day)
                x_daily.fill_articles(x_daily_path, x_daily.day_key(x_daily.now_bj()), want=_x_articles())  # 价值线一直保持这么多篇（拆了、不发了就补）
                # 10/12 作者：短帖每天 50 条（10/13 起 100）。一次最多 25，全天 23:00 前补到数
                short_n = x_daily.short_topup_due(x_daily_path, int(counts.get("own_short", 50)))
                if short_n and not x_daily_run["topup_busy"] and not x_daily_run["planning"]:
                    x_daily_run["topup_busy"] = True
                    threading.Thread(target=_x_short_topup, args=(short_n,), name="x-short-topup", daemon=True).start()
                n = x_daily.hot_due(x_daily_path, int(counts.get("hot", 0)))
                if n and not x_daily_run["hot_busy"]:
                    _x_hot_start(n)
                x_daily.tick(x_daily_path, post_fn=x_post_fn or _x_send, record_fn=_x_daily_record,
                             auto_send=store.settings()["x_auto_send"], target=x_daily.daily_target(counts))
            except Exception as exc:  # noqa: BLE001 - 下一分钟再来
                logger.warning("x daily tick: %s", exc)
            stop_auto.wait(60)

    def _x_long_swap(key: str, post_id: str, *, reason: str | None = None, allow_empty: bool = False) -> dict[str, Any] | None:
        st = x_line.load_state(x_state)
        sources = x_line.gather(vault_path(), cache=x_cache, **({"fetch": x_fetch_fn} if x_fetch_fn else {}))
        old = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        avoid = {p["source_id"] for p in st["posts"] if p.get("source_id")} | set(st["skipped"]) | _video_notes()
        row = x_daily.swap_long(x_daily_path, key, post_id, sources=sources, avoid=avoid | {(old or {}).get("source_id")},
                                read_full=_read_full, reason=reason, allow_empty=allow_empty)
        if old and old.get("source_id") and not reason and old["source_id"] not in _video_notes():
            x_line.skip(x_state, old["source_id"])  # 他点的「换一篇」：这篇放一边，以后不再排；压着的视频笔记不放一边，到期还能排
        return row

    def _x_daily_retire_videos() -> None:
        """排着还没勾的长帖，笔记后来被拍成视频了：自动换一篇。"""
        for key, post_id in x_daily.video_note_posts(x_daily_path, _video_notes()):
            _x_long_swap(key, post_id, reason=f"拍成视频了，{x_daily.VIDEO_HOLD_DAYS} 天后再排，先换了一篇", allow_empty=True)
            store.log_event("x", f"{key} 的一篇长文拍成视频了，换了一篇")

    @app.post("/api/xline/daily/{key}/{post_id}/prep")
    def redo_x_long(key: str, post_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """长文「重做」：没做成的、或者想重新改写配图的，排回去重新做（后台，十来分钟）。body.flow 能换这一篇走的流程。"""
        post = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if not post or not post.get("long") or post["state"] not in ("pending", "approved", "rejected") or post.get("swapped"):
            raise HTTPException(status_code=400, detail="这一篇不能重做")
        flow = (body or {}).get("flow")
        if flow:
            try:
                names = {*_flow_pick()[0].flows, *store.settings()["write_flow"]["custom"]}
            except write_module.ModuleError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if flow not in names:
                raise HTTPException(status_code=400, detail=f"没有「{flow}」这个流程")
        return {"post": x_daily.set_post(x_daily_path, key, post_id, prep=None, prep_error=None,
                                         state="pending" if post["state"] == "approved" else post["state"],
                                         **({"flow_name": flow} if flow else {}))}

    @app.get("/api/xline/write/module")
    def write_module_info() -> dict[str, Any]:
        """park-writing 的模块清单：给页面画按钮和设置里的流程。读不懂时 ok=false 带原因。"""
        if not write_module.available():
            return {"ok": False, "installed": False, "error": "这台机器没有带 module.yaml 的 park-writing，写长文走老的整理"}
        try:
            module = write_module.load()
        except write_module.ModuleError as exc:
            return {"ok": False, "installed": True, "error": str(exc)}
        saved = store.settings()["write_flow"]
        commit = None
        try:  # skill 是本机的 git 检出：GitHub 上合并了的改动要拉下来才生效，页面上写出现在读的是哪一版
            commit = subprocess.run(["git", "-C", str(module.root), "log", "-1", "--format=%h %cd", "--date=format:%m-%d %H:%M"],
                                    capture_output=True, text=True, timeout=5, check=True).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            pass
        module = _module()
        return {"ok": True, "installed": True, "version": module.version, "skill": {"path": str(module.root), "commit": commit}, "default": saved["default"],
                "max_change_pct": _pct_setting(), "max_change_pct_limit": write_module.MAX_CHANGE_PCT,
                "flows": {k: list(v) for k, v in module.flows.items()}, "custom": saved["custom"],
                "constraints": module.constraints, "asked_change_pct": module.asked_change_pct,
                "draft_reasons": sorted({write_patch.STEP_REASON[s.id] for s in module.ordered()
                                         if s.id in write_patch.STEP_REASON and s.runnable and s.fix == "edit" and write_patch.step_may_add(s)}),
                "steps": [{"id": s.id, "title": s.title, "group": s.group, "status": s.status, "does": s.does, "output": s.output,
                           "round": s.round, "fix": s.fix, "on_fail": s.on_fail, "version": module.step_version(s.id) if s.runnable else None}
                          for s in module.ordered()]}

    @app.put("/api/xline/write/flow")
    def set_write_flow(body: dict[str, Any]) -> dict[str, Any]:
        """默认走哪个流程；另存 / 删掉自己的流程（最多 2 个，只存开了哪些步骤，顺序固定）。"""
        try:
            module = write_module.load()
        except write_module.ModuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved = store.settings()["write_flow"]
        custom = dict(saved["custom"])
        if body.get("delete"):
            custom.pop(str(body["delete"]), None)
        if body.get("save"):
            name, ids = str(body["save"].get("name") or "").strip(), body["save"].get("steps")
            if not name or name in module.flows:
                raise HTTPException(status_code=400, detail="起个名字，不能和出厂的流程重名")
            if not isinstance(ids, list) or not ids or any(i not in module.steps for i in ids) or len(set(ids)) != len(ids):
                raise HTTPException(status_code=400, detail="步骤要是清单里有的，不能重复")
            custom[name] = [s.id for s in module.flow_steps(ids)]  # 顺序按清单的，不按他点的先后
        default = str(body.get("default") or saved["default"])
        if default not in module.flows and default not in custom:
            default = next(iter(module.flows))
        pct = body.get("max_change_pct", saved.get("max_change_pct", 20))
        try:
            return {"write_flow": store.update_settings({"write_flow": {"default": default, "custom": custom, "max_change_pct": pct}})["write_flow"]}
        except StoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/xline/daily/{key}/{post_id}/file/{name:path}")
    def x_long_file(key: str, post_id: str, name: str) -> FileResponse:
        """长文里的插图、封面，给卡片预览用。只读这一篇自己的文件夹。"""
        from . import x_long

        post = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        base = (x_long.post_folder(post) if post else x_long.folder(post_id)).resolve()
        path = (base / name).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="没有这张图")
        return FileResponse(path)

    @app.post("/api/xline/daily/{key}/{post_id}/swap")
    def swap_x_daily(key: str, post_id: str) -> dict[str, Any]:
        """长帖「换一篇」：这篇不发、放一边，下一篇顶上。"""
        try:
            row = _x_long_swap(key, post_id)
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"post": row}

    @app.get("/api/xline/daily")
    def get_x_daily() -> dict[str, Any]:
        return {**x_daily.view(x_daily_path, counts=_x_counts(), auto_send=store.settings()["x_auto_send"], flow_now=_flow_now()), **x_daily_run}

    @app.put("/api/xline/counts")
    def set_x_counts(body: dict[str, Any]) -> dict[str, Any]:
        """X 每天发多少：长的总数、其中长帖占比、热点短帖上限。改了从还没排的那天起生效，已经排好的不动。"""
        try:
            return {"counts": store.update_settings({"x_counts": body})["x_counts"]}
        except StoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/xline/daily/plan")
    def plan_x_daily(body: dict[str, Any]) -> dict[str, Any]:
        """「现在排」：默认排今天的（第一次用、或者昨晚没排上）。后台跑，一两分钟。"""
        now = x_daily.now_bj()
        key = x_daily.day_key(now + timedelta(days=1)) if body.get("day") == "tomorrow" else x_daily.day_key(now)
        if x_daily_run["planning"]:
            return {"started": False, "message": f"{xops.name()} 正在排"}
        x_daily_run.update(planning=key, error=None)
        threading.Thread(target=_x_daily_plan, args=(key,), name="x-daily-plan", daemon=True).start()
        return {"started": True, "message": f"{xops.name()} 在从你的原始输出里挑（短帖、长文哪个没排补哪个），一两分钟"}

    @app.patch("/api/xline/daily/{key}/{post_id}")
    def mark_x_daily(key: str, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """打勾 approved / 打叉 rejected / 撤回 pending；也能改字。打叉的来源记成放一边，Wendy 不再排它。"""
        before = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if before and before.get("trk"):
            if body.get("text") is not None:
                raise HTTPException(status_code=400, detail="这篇带修改清单：要改字，在批注视图里用「用我改的」")
            left = write_patch.pending_edits(before["trk"]["changes"])
            if body.get("state") == "approved" and left:
                raise HTTPException(status_code=400, detail=f"还有 {left} 处修改没处理：逐条处理，或点「全部接受 / 全部不要」")
        try:
            post = x_daily.mark(x_daily_path, key, post_id, state=body.get("state"), text=body.get("text"),
                                post_cap=x_daily.split_counts(_x_counts())[1] or None)  # 10/12 起长的不自动排（0）：他自己勾的不设上限
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if post.get("source_id") and before and before["state"] != post["state"] and "rejected" in (before["state"], post["state"]) \
                and not (post.get("long") and post["source_id"] in _video_notes()):  # 压着的视频笔记打叉不放一边，到期还能排
            x_line.skip(x_state, post["source_id"], undo=post["state"] != "rejected")
        return {"post": post}

    @app.post("/api/xline/daily/{key}/approve-all")
    def approve_all_x_daily(key: str) -> dict[str, Any]:
        """「剩下的全勾」：还没打勾也没打叉、已经做好的都勾上；长帖勾满当天的数量就停（他点的才算，不会自己勾）。"""
        n, left = 0, 0
        cap = x_daily.split_counts(_x_counts())[1] or None
        for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []):
            if x["state"] != "pending" or x.get("swapped"):
                continue
            if x.get("qa_complete") is False or x.get("qa_value_ok") is False or x.get("qa") == "running" or (
                    x.get("long") and x.get("prep") == "ready" and x.get("qa") is None):
                left += 1
                continue
            try:
                x_daily.mark(x_daily_path, key, x["id"], state="approved", post_cap=cap)
                n += 1
            except x_daily.DailyError:
                left += 1  # 还在做的长文、勾满了的长帖
        return {"approved": n, "left": left}

    @app.post("/api/xline/picks/{key}/{pick_id}")
    def choose_x_pick(key: str, pick_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """候选卡上的四个按钮。不发 = 这篇笔记放一边（素材里也不再推）。"""
        try:
            pick = x_daily.choose(x_daily_path, key, pick_id, str((body or {}).get("action") or ""))
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if pick["choice"] == "skip":
            x_line.skip(x_state, pick["source_id"])
        store.log_event("x", f"候选《{pick['title'][:30]}》：{x_daily.PICK_ACTIONS[pick['choice']]}")
        return {"pick": {k: v for k, v in pick.items() if k != "text"}}

    @app.post("/api/xline/value/{key}/own")
    def x_value_own(key: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"own": x_daily.set_own(x_daily_path, key, **{k: v for k, v in (body or {}).items() if k in ("article", "video")})}

    @app.post("/api/xline/value/{key}/{post_id}")
    def x_value_action(key: str, post_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """价值线卡片：拆成短帖 / 不发（不发 = 这篇笔记放一边）。撤下后从候选里补一篇。"""
        try:
            out = x_daily.value_action(x_daily_path, key, post_id, str((body or {}).get("action") or ""))
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if (out.get("pick") or {}).get("choice") == "skip":
            x_line.skip(x_state, out["pick"]["source_id"])
        return {"ok": True}

    @app.post("/api/xline/daily/{key}/{post_id}/draft")
    def draft_x_article(key: str, post_id: str) -> dict[str, Any]:
        """发文：改写、配图、封面、QA 都好了，整篇存进 X 的文章草稿，他自己去 X 点发布。"""
        from . import x_article
        from ...x_post import CREDITS_OUT, XError

        post = next((x for x in x_daily.load(x_daily_path)["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if post is None or not post.get("manual_publish"):
            raise HTTPException(status_code=400, detail="这一篇不是要存草稿的长文")
        if post.get("prep") != "ready":
            raise HTTPException(status_code=400, detail="还在改写配图，好了再存")
        left = write_patch.pending_edits(post["trk"]["changes"]) if post.get("trk") else 0
        if left:
            raise HTTPException(status_code=400, detail=f"还有 {left} 处修改没处理：逐条处理，或点「全部接受 / 全部不要」")
        if _complete_on_fail() == "block" and post.get("qa_complete") is False:
            raise HTTPException(status_code=400, detail="完整度没过，这个流程设了「拦住」：改好以后重跑检查，过了才能存草稿")
        article = Path(str(post.get("article") or ""))
        if not article.parent.is_dir():
            raise HTTPException(status_code=400, detail="这篇长文的文件夹不见了，点「重做」")
        article.write_text(post["text"].rstrip() + "\n", encoding="utf-8")
        cover = article.parent / "x-cover.png"
        try:
            result = x_article.publish_article(article, publish=False, cover=cover if cover.is_file() else None)
        except XError as exc:
            if CREDITS_OUT in str(exc):
                x_daily.set_credits_out(x_daily_path, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = x_daily.mark_drafted(x_daily_path, key, post_id, result.get("url"))
        store.log_event("x", f"长文存进 X 草稿：{post.get('source_title') or ''}"[:60])
        return {"post": row}

    @app.post("/api/xline/daily/{key}/{post_id}/handed")
    def handed_x_quote(key: str, post_id: str) -> dict[str, Any]:
        """引用帖：X 不让工作台发，他点了「去 X 发」。"""
        try:
            return {"post": x_daily.quote_handed(x_daily_path, key, post_id)}
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/xline/daily/resume")
    def resume_x_daily() -> dict[str, Any]:
        """X API 充值好了（或者今天被停了想接着发）：下一分钟接着发。"""
        x_daily.resume(x_daily_path)
        return {"ok": True}

    @app.post("/api/xline/quotes/retry-api")
    def retry_x_quotes() -> dict[str, Any]:
        x_daily.retry_quotes(x_daily_path)
        return {"ok": True}

    @app.post("/api/xline/daily/{key}/{post_id}/manual")
    def manual_x_daily(key: str, post_id: str) -> dict[str, Any]:
        """没发成、不确定的那条，复制去 X 自己发了：记一条。"""
        try:
            post = x_daily.manual(x_daily_path, key, post_id)
        except x_daily.DailyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _x_daily_record(post)
        return {"post": post}

    @app.post("/api/xline/skip")
    def xline_skip(body: XLineSkipBody) -> dict[str, Any]:
        return {"skipped": x_line.skip(x_state, body.source_id, undo=body.undo)}

    startup.append(lambda: threading.Thread(target=_x_daily_loop, name="x-daily", daemon=True).start())
    # 10/20 作者：X 的 API 拿掉。每小时读数、自动回复这两个循环不再起（函数留着，测试还能直接调）
    startup.append(lambda: threading.Thread(target=_x_long_loop, name="x-long", daemon=True).start())
    app.state.x_long_add_summary = x_long_add_summary
    app.state.x_long_prep = x_long_prep  # 长文改写配图：测试用（平时由 x-long 线程调）
    app.state.x_send = _x_send
