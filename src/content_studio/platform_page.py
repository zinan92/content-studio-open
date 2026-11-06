"""平台页（10/6 作者）：左边按平台排，抖音、视频号、小红书、X 各一页，B 站 · YouTube · 公众号合成「其他三个」。

一页三段：待发（这条内容在这个平台要做的事：发哪几种、文案、封面或卡片、发了点一下）、
这个平台（默认发什么、流量话题、账号）、这个平台的数据和被删被限流的记录。
打包、发布两站的东西拆进各平台页；「每条内容发在哪」和概览进「汇总」。

这里只放不碰库、不碰文件的纯函数；读库、读文件、起任务的在 web.py 里。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import reach

PAGE_KEYS = ("douyin", "channels", "xiaohongshu", "x", "others")
GROUPS = {"others": ("bilibili", "youtube", "wechat_mp")}
GROUP_LABEL = {"others": "其他三个"}

# 每种形式在这个平台怎么发（10/6）：
#   auto  机器直接发（B 站投稿；YouTube 直接公开）。10/20 起 X 不走 API，全是 hand
#   draft 进草稿箱，他去后台点发布（公众号）
#   hand  文案和文件备好，他自己去传，传完点「发了」（视频号、小红书、抖音、X）
ACTION_LABEL = {"auto": "机器发", "draft": "进草稿箱", "hand": "你来传"}


def action_for(key: str, form: str) -> str:
    # 10/20 作者：X 不再走 API，和别的平台一样他自己传（文字也是）
    if key in ("bilibili", "youtube"):
        return "auto" if form == "video" else "hand"
    if key == "wechat_mp":
        return "draft" if form == "text" else "hand"
    return "hand"


def sent_row(key: str, form: str, *, records: dict[str, dict[str, Any]], posts: dict[tuple[str, str], dict[str, Any]],
             marks: dict[str, set[str]], topic: dict[str, Any]) -> dict[str, Any] | None:
    """这一条这个平台这种形式发了没有。四处记录合起来看：形式级（publish_posts）、平台级（publish_records，老记录没记形式的算发了）、
    抖音对上的作品（published_video_id）、全平台追踪里标的「在外面发过」（backfill_marks，只管视频）。"""
    row = posts.get((key, form))
    if row:
        return {"url": row.get("url"), "at": row.get("published_at"), "how": "post"}
    rec = records.get(key)
    if rec and (rec.get("form") or form) == form:
        return {"url": rec.get("url"), "at": rec.get("published_at"), "how": "record"}
    vid = topic.get("published_video_id")
    if form == "video" and vid:
        if key == "douyin":
            return {"url": f"https://www.douyin.com/video/{vid}", "at": None, "how": "douyin"}
        if key in marks.get(str(vid), set()):
            return {"url": None, "at": None, "how": "mark"}
    return None


def presentation_state(row: dict[str, Any]) -> dict[str, Any]:
    """Read-only presentation; task completion alone is never a publication receipt.

    Keep preparation, delivery and automatic scheduling independent. In particular,
    an old draft or a running upload remains visible when its inputs become stale.
    """
    sent, job = row.get("sent") or {}, row.get("job") or {}
    state, reason = "ready", ""
    if row.get("sent") is not None:
        state = "published"
    elif job.get("state") in ("running", "awaiting_confirm", "unknown"):
        state = job["state"]
        reason = job.get("message") or ""
    elif job.get("draft"):
        state = "draft"
    elif job.get("state") == "failed":
        state, reason = "failed", job.get("message") or ""
    elif not row.get("ready"):
        state, reason = "not_ready", row.get("why") or ""
    elif row.get("plan") == "wait":
        state, reason = "wait", row.get("plan_note") or ""
    labels = {"published": "已发布", "running": "发布中", "awaiting_confirm": "等待确认",
              "unknown": "发布结果待核对", "draft": "已存草稿", "failed": "发布失败",
              "not_ready": "素材未齐", "ready": "素材已就绪", "wait": "等待发布顺序"}
    return {"state": state, "label": labels[state], "reason": reason,
            "url": sent.get("url"), "published_at": sent.get("at"), "source": sent.get("how"),
            "draft_link": job.get("draft_link") if state == "draft" else None,
            "plan": row.get("plan"), "plan_note": row.get("plan_note")}


def duplicate_publications(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report one public post assigned to multiple topics, without picking a winner.

    Input includes both publish_posts and publish_records with a source label.
    Mirrors and multiple forms belonging to one topic are consolidated, not warned.
    """
    from .links import post_id

    grouped: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for row in rows:
        platform, topic_id = row.get("platform"), row.get("topic_id")
        pid = post_id(platform, row.get("url"))
        if pid is None or topic_id is None:
            continue
        topics = grouped.setdefault((platform, pid), {})
        entry = topics.setdefault(topic_id, {"topic_id": topic_id, "title": row.get("title") or "",
                                           "forms": [], "urls": [], "sources": []})
        for field, value in (("forms", row.get("form")), ("urls", row.get("url")), ("sources", row.get("source"))):
            if value and value not in entry[field]:
                entry[field].append(value)
    return [{"platform": platform, "post_id": pid, "topic_ids": sorted(topics),
             "publications": [topics[tid] for tid in sorted(topics)],
             "message": "同一帖子关联了多条内容，需核对原记录"}
            for (platform, pid), topics in sorted(grouped.items()) if len(topics) > 1]


def publication_metrics(platform: str, rows: list[dict[str, Any]], snapshots: dict[tuple[str, str], int],
                        *, title_match: int | None = None) -> dict[str, Any]:
    """Annotate read coverage separately from publication. A known zero is complete.

    A title-only fallback can cover one published form; it cannot explain two
    distinct publications. Do not let one known snapshot make their total complete.
    """
    from .links import post_id

    published_count = sum(row["presentation"]["state"] == "published" for row in rows)
    annotated, missing_ids, missing_forms = [], set(), []
    for row in rows:
        sent = row.get("sent") or {}
        published = row["presentation"]["state"] == "published"
        pid = post_id(platform, sent.get("url")) if published else None
        value = snapshots.get((platform, pid)) if pid else None
        source = "post_snapshot" if value is not None else None
        if published and value is None and published_count == 1 and title_match is not None:
            value, source = title_match, "title_match"
        if published and value is None:
            if pid:
                missing_ids.add(pid)
            missing_forms.append(row["form"])
        annotated.append({**row, "metrics": {"views": value, "post_id": pid,
                                            "complete": published and value is not None, "source": source}})
    return {"forms": annotated, "metrics_complete": not missing_forms,
            "missing_post_ids": sorted(missing_ids), "missing_forms": missing_forms}


def attach_views(key: str, posts: list[dict[str, Any]], views_by_id: dict[tuple[str, str], int],
                 title_views: list[tuple[str, int]], post_id_fn) -> list[dict[str, Any]]:
    """每一笔发出去的，配上最近读到的累计数：按链接里的帖子编号对；小红书没有编号，按标题对（和概览一个规矩）。"""
    from .backfill import similarity

    out = []
    for p in posts:
        views = None
        pid = post_id_fn(key, p.get("url")) if p.get("url") else None
        if pid is not None and (key, pid) in views_by_id:
            views = views_by_id[(key, pid)]
        elif key == "xiaohongshu" and title_views:
            best = max(title_views, key=lambda tv: similarity(p.get("title") or "", tv[0]))
            if similarity(p.get("title") or "", best[0]) >= 0.6:
                views = best[1]
        out.append({**p, "views": views})
    return out


def group_rows(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一条内容发了几种形式：合成一行，形式列在一起，数取最大的那笔。"""
    rows: dict[int, dict[str, Any]] = {}
    for p in posts:
        row = rows.setdefault(p["topic_id"], {"topic_id": p["topic_id"], "title": p.get("title") or "", "forms": [], "url": None,
                                             "published_at": p.get("published_at"), "views": None})
        if p.get("form") and p["form"] not in row["forms"]:
            row["forms"].append(p["form"])
        if p.get("url") and not row["url"]:
            row["url"] = p["url"]
        if p.get("views") is not None and (row["views"] is None or p["views"] > row["views"]):
            row["views"] = p["views"]
        if (p.get("published_at") or "") < (row["published_at"] or ""):
            row["published_at"] = p.get("published_at")
    return sorted(rows.values(), key=lambda r: r["published_at"] or "", reverse=True)


def form_labels(forms: list[str]) -> list[str]:
    return [reach.FORM_LABEL.get(f, f) for f in forms]


# ---------------- 其他三个：自动发 + 汇总表（10/8 作者） ----------------
# 「只要是主线下来的内容，全部都自动处理」：B 站、YouTube 做好了机器自己发，不用点「发到 B 站」；
# 公众号做好了自己存进草稿箱，不用点「存进草稿箱」——他只去后台扫码群发。群发了没有，这一页自己看出来。
AUTO_KEYS = GROUPS["others"]
AUTO_MAX_TRIES = 3          # 一条一个平台机器最多自己发三次；还不成就停下，等他点「再发一次」
AUTO_RETRY_MINUTES = 30     # 没发成的，隔半小时再自己试；登录过期的，登好了马上再发
DRAFT_CHECK_MINUTES = 30    # 公众号草稿多久去看一次还在不在（群发之后草稿就从草稿箱里没了）


def _when(iso: str | None) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(iso)) if iso else None
    except ValueError:
        return None
    return at.replace(tzinfo=timezone.utc) if at and at.tzinfo is None else at


def auto_plan(row: dict[str, Any], jobs: list[dict[str, Any]], now: datetime, *, login_failed) -> tuple[str, str | None]:
    """这一格（一条内容 × 一个平台 × 一种形式）现在是什么情况、机器要不要自己发。

    row 是平台页「待发」里的一行（sent / ready / why / action）；jobs 是这条在这个平台的发布任务，新的在前；
    login_failed(job) 说这次没发成是不是因为登录过期。返回 (状态, 补充)：
      sent 发了 · wait 还差东西（补充 = 差什么） · hand 要他自己传 · running 机器在发
      draft 在草稿箱等他群发 · unknown 发的时候服务重启了，不知道发没发（不自己重发，免得发两遍）
      due 现在就该自己发 · retry 没发成，补充 = 几点自己再试 · failed 没发成、不再自己试了
    """
    if row.get("sent"):
        return "sent", None
    if row.get("action") not in ("auto", "draft"):
        return "hand", None
    if not row.get("ready"):
        return "wait", row.get("why") or ""
    live = [j for j in jobs if j.get("state") not in ("cancelled", "superseded")]
    if not live:
        return "due", None
    last = live[0]
    state = last.get("state")
    if state in ("running", "awaiting_confirm"):
        return "running", None
    if state == "unknown":
        return "unknown", None
    if state == "done":
        return ("draft", None) if (last.get("result") or {}).get("published") is False else ("sent", None)
    tries = sum(1 for j in live if j.get("state") == "failed")
    if tries >= AUTO_MAX_TRIES:
        return "failed", None
    if login_failed(last):
        return "due", None  # 登录过期：tick 那边先确认登上了才会发
    at = _when(last.get("finished_at") or last.get("created_at"))
    again = (at + timedelta(minutes=AUTO_RETRY_MINUTES)) if at else now
    return ("due", None) if now >= again else ("retry", again.isoformat(timespec="seconds"))


def summary_rows(groups: list[dict[str, Any]], posts: dict[str, list[dict[str, Any]]], *, since: str, limit: int = 30) -> list[dict[str, Any]]:
    """「其他三个」的汇总表：一行一条内容，三列是 B 站、YouTube、公众号，每格里一种形式一行。

    groups 是三个平台各自的待发（每行已经带好 plan 状态）；posts 是每个平台发过的（publish_posts / publish_records），
    只取 since 之后的。没发也不在待发里的格子不出现（这条没打算发这个平台）。"""
    rows: dict[int, dict[str, Any]] = {}

    def row_for(tid: int, title: str, at: str | None) -> dict[str, Any]:
        r = rows.setdefault(tid, {"topic_id": tid, "title": title, "at": at or "", "cells": {}})
        if (at or "") > r["at"]:
            r["at"] = at or ""
        return r

    for g in groups:
        key = g["key"]
        for it in g["pending"]:
            r = row_for(it["topic_id"], it["title"], it.get("updated_at"))
            r["cells"][key] = [{"form": fr["form"], "label": fr["label"], "state": fr["plan"], "note": fr.get("plan_note"),
                                "url": (fr.get("sent") or {}).get("url"), "at": (fr.get("sent") or {}).get("at"),
                                "message": (fr.get("job") or {}).get("message"), "draft_link": (fr.get("job") or {}).get("draft_link"),
                                "presentation": fr.get("presentation") or presentation_state(fr)}
                               for fr in it["rows"]]
    for key, mine in posts.items():
        for p in mine:
            if not p.get("topic_id") or (p.get("published_at") or "") < since:
                continue
            r = row_for(p["topic_id"], p.get("title") or "", p.get("published_at"))
            cell = r["cells"].setdefault(key, [])
            form = p.get("form") or ""
            if any(c["form"] == form or (not form and c["state"] == "sent") for c in cell):
                continue
            cell.append({"form": form, "label": reach.FORM_LABEL.get(form, ""), "state": "sent", "note": None,
                         "url": p.get("url"), "at": p.get("published_at"), "message": None, "draft_link": None,
                         "presentation": presentation_state({"sent": {"url": p.get("url"), "at": p.get("published_at"), "how": "record"}})})
    out = sorted(rows.values(), key=lambda r: r["at"], reverse=True)
    return out[:limit]


NEEDS_YOU = ("draft", "failed", "unknown", "hand")


def needs_you(table: list[dict[str, Any]], login: set[str]) -> int:
    """左栏「其他三个」右边的数：要他动手的格子（群发、没发成、不确定、要自己传、等他扫码登录），机器自己会发的不算。"""
    n = 0
    for r in table:
        for key, cell in r["cells"].items():
            n += sum(1 for c in cell if c["state"] in NEEDS_YOU or (key in login and c["state"] in ("due", "retry")))
    return n
