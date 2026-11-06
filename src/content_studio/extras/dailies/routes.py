"""日报：进项里一期一期看日报、单条入选题池，K 线日报看板，今天页的读日报（9/19 起）。试用版没有这一块。"""
from __future__ import annotations

from typing import Any
from pathlib import Path
from datetime import date
from ... import vault
from ...store import StoreError
from ...web import DailyPickBody
from ...core.dates import parse_day


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ("drafts_root", "places", "store")
PROVIDES: tuple[str, ...] = ("daily_original",)


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    drafts_root = ctx.drafts_root
    store = ctx.store
    vault_path = places.vault_path

    @app.get("/api/today/dailies")
    def today_dailies(day: str | None = None) -> dict[str, Any]:
        target = parse_day(day)
        checks = store.daily_checks(target.isoformat())
        items = vault.dailies(vault_path(), target)
        return {"day": target.isoformat(), "items": [{**item, "checked_at": checks.get(item["key"])} for item in items]}

    @app.get("/api/kline/board")
    def kline_board_api() -> dict[str, Any]:
        """K 线日报 tab: every watchlist asset as a compact daily card (read-only)."""
        from . import kline_board
        return kline_board.board()

    @app.get("/api/vault/dailies")
    def vault_daily_history(key: str, limit: int = 30) -> dict[str, Any]:
        items = vault.daily_history(vault_path(), key, limit)
        checked = {d: True for d in store.checked_days(key)}
        return {"key": key, "items": [{**i, "checked": bool(checked.get(i["day"]))} for i in items]}

    # -- 日报：一期一条条看，单条入选题池 ---------------------------------------

    def _daily_source(key: str) -> Any:
        source = next((s for s in vault.DAILY_SOURCES if s.key == key), None)
        if source is None:
            raise ValueError(f"没有这份日报：{key}")
        return source

    def _daily_issue(key: str, path: str | None) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        from . import newsletter

        source = _daily_source(key)
        history = vault.daily_history(vault_path(), key, 60)
        if not history:
            raise ValueError("这份日报还没有出过")
        entry = next((h for h in history if h["path"] == path), None) if path else history[0]
        if entry is None:
            raise ValueError("找不到这一期日报")
        note = vault.read_note(vault_path(), entry["path"])
        return source, entry, newsletter.parse_issue(note.get("body") or "")

    @app.get("/api/vault/daily/issue")
    def daily_issue(key: str, path: str | None = None) -> dict[str, Any]:
        """One issue, item by item. Without `path` it is the newest issue (today's after 08:30)."""
        from . import newsletter

        source, entry, parsed = _daily_issue(key, path)
        picks = store.daily_picks()
        day = newsletter.issue_day(Path(entry["path"]).name)
        index = newsletter.originals_index(Path(source.items) if source.items else None, day) if day else {}
        topics = {t["id"]: t for t in store.topics(include_archived=True)}
        for section in parsed["sections"]:
            for item in section["items"]:
                keys = [newsletter.url_key(u) for u in item["urls"]]
                tid = next((picks[k] for k in keys if k in picks), None)
                t = topics.get(tid) if tid else None
                item["topic_id"] = tid if t else None
                item["topic_archived"] = bool(t and t.get("archived_at"))
                item["has_original"] = newsletter.find_original(item, index) is not None
                item["has_deep"] = any(k in parsed["deep"] for k in keys)
        return {"key": key, "label": source.label, "path": entry["path"], "day": entry["day"], "title": parsed["title"] or entry["title"],
                "is_today": entry["day"] == date.today().isoformat(), "sections": parsed["sections"],
                "history": [{"path": h["path"], "day": h["day"], "title": h["title"]} for h in vault.daily_history(vault_path(), key, 60)]}

    def _daily_item(key: str, path: str, item_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], str]:
        source, entry, parsed = _daily_issue(key, path)
        item = next((i for s in parsed["sections"] for i in s["items"] if i["id"] == item_id), None)
        if item is None:
            raise ValueError("这一期里找不到这条快讯")
        return source, entry, parsed, item, entry["title"]

    @app.get("/api/vault/daily/original")
    def daily_original(key: str, path: str, item: str) -> dict[str, Any]:
        """The full text behind one 快讯, to read in place before taking it."""
        from . import newsletter

        source, entry, parsed, it, _ = _daily_item(key, path, item)
        day = newsletter.issue_day(Path(entry["path"]).name)
        found = newsletter.find_original(it, newsletter.originals_index(Path(source.items) if source.items else None, day)) if day else None
        deep = next((parsed["deep"][newsletter.url_key(u)] for u in it["urls"] if newsletter.url_key(u) in parsed["deep"]), None)
        original = newsletter.read_original(found) if found else None
        return {"item": it, "quality": "原文" if original else "只有摘要", "deep": deep["body"] if deep else "",
                "body": original["body"] if original else "", "meta": {k: str(v) for k, v in (original or {}).get("meta", {}).items() if k in ("source", "author", "url", "published_at", "platform")}}

    @app.post("/api/vault/daily/pick")
    def daily_pick(body: DailyPickBody) -> dict[str, Any]:
        """Take one 快讯 into 选题池. Its original text is snapshotted with the topic — the
        pipeline keeps only a few days — and nothing is written to the vault."""
        from . import newsletter

        source, entry, parsed, it, issue = _daily_item(body.key, body.path, body.item)
        keys = [newsletter.url_key(u) for u in it["urls"]]
        picks = store.daily_picks()
        existing = next((picks[k] for k in keys if k in picks), None)
        if existing is not None:
            try:
                topic = store.topic(existing)
            except StoreError:
                topic = None
            if topic is not None:
                if topic.get("archived_at"):
                    topic = store.update_topic(topic["id"], archived_at=None)
                    store.log_event("pool", f"《{topic['title'][:30]}》又捡回来了", topic["id"])
                return {"topic": topic, "quality": None, "again": True}
        day = newsletter.issue_day(Path(entry["path"]).name)
        found = newsletter.find_original(it, newsletter.originals_index(Path(source.items) if source.items else None, day)) if day else None
        original = newsletter.read_original(found) if found else None
        deep = next((parsed["deep"][k] for k in keys if k in parsed["deep"]), None)
        me = store.self_account()
        topic = store.create_topic(it["title"], account_id=me["id"] if me else None,
                                   memo=f"来自{issue} · {it['source']}" + ("" if original else "（只有摘要，原文已不在日报管道里）"))
        newsletter.save_snapshot(drafts_root, topic["id"], it, newsletter.snapshot_markdown(it, issue=issue, original=original, deep=deep))
        for k in keys:
            store.add_daily_pick(k, topic["id"], issue)
        store.log_event("pool", f"《{topic['title'][:30]}》从{source.label}进了选题池", topic["id"])
        return {"topic": topic, "quality": "原文" if original else "只有摘要", "again": False}


    ctx.daily_original = daily_original  # 别的积木要用
