"""战况：Wendy 背的 KPI，每个拆成一棵树——目标、现在、每天要多少、照现在的速度到哪、靠哪几个数撬动。

10/12 作者：「Wendy 是这个 project 的 full owner……一旦定下了 KPI，就要 make that happen，而且要确保 KPI is viable。」
他只干两件事：和 Wendy 一起定 KPI；定完严格执行。所以这一页是 Wendy 的账，他看、不用操作。

- 目标是他拍板的（设置里 douyin_follow_target / x_follow_target / x_kpi.impressions / kpi.revenue_monthly）：
  默认都是空的，在设置里填。
- 转化率不是目标，是算出来的（10/12 作者：「转化率不是我们的目标，而是计算出来的」）：
  每千播放（曝光）涨几个粉 = 最近 14 天全号的粉丝差 ÷ 同几天的播放和。不拿每条视频的「涨粉」加起来——那不算掉粉，也漏了主页、直播进来的。
- 每天要多少播放 = 每天要涨的粉 ÷ 现在的转化率。照现在的速度 = 现在 + 最近 7 天日均涨粉 × 剩下的天数。
- 收入每 3 天问他一次有没有新的收入点（10/12 作者：「不用每天……每 3 天来催我一次」）。
"""
from __future__ import annotations

from datetime import date, timedelta
from math import ceil
from statistics import median
from typing import Any

CONV_WINDOW = 14   # 转化率看最近两周
RATE_WINDOW = 7    # 涨粉速度、日均播放看最近 7 个过完的日子
LEVER_VIDEOS = 5   # 每条视频的几个数，看最近 5 条的中位数
MONEY_ASK_EVERY = 3
MIN_SPAN = 3       # 两次读数至少隔 3 天才算速度（和 followers.py 一样）


def _value_on(readings: list[tuple[str, int]], day: str) -> int | None:
    """day 那天结束时有多少：那天或之前最后一次读数；比第一次读数还早就没有（不往前画平，速度算不出来就是算不出来）。"""
    before = [v for d, v in readings if d <= day]
    return before[-1] if before else None


def _iso(d: date) -> str:
    return d.isoformat()


def follow_line(readings: list[tuple[str, int]], target: dict[str, Any], today: date, *, now: int | None = None) -> dict[str, Any]:
    """一个平台的粉丝 KPI。readings 按天排、一天一个数（那天最后一次读数）；now 是比今天那行更新的读数（X 每小时读一次）。"""
    start_day, end_day = date.fromisoformat(target["start_day"]), date.fromisoformat(target["end_day"])
    start, end = int(target["start"]), int(target["end"])
    current = now if now is not None else (readings[-1][1] if readings else None)
    days_left = max(1, (end_day - today).days)
    yesterday = today - timedelta(days=1)
    v_y, base_day = _value_on(readings, _iso(yesterday)), yesterday - timedelta(days=RATE_WINDOW)
    v_base = _value_on(readings, _iso(base_day))
    if v_base is None and readings:  # 记的天数不到 7 天：从第一次读数算，至少隔 MIN_SPAN 天才算速度
        base_day = date.fromisoformat(readings[0][0])
        v_base = readings[0][1] if (yesterday - base_day).days >= MIN_SPAN else None
    span = (yesterday - base_day).days
    rate = round((v_y - v_base) / span, 1) if v_y is not None and v_base is not None and span > 0 else None
    need = max(0, ceil((end - current) / days_left)) if current is not None else None
    forecast = round(current + rate * days_left) if current is not None and rate is not None else None
    fraction = min(1, max(0, (today - start_day).days / max(1, (end_day - start_day).days)))
    expected = round(start + (end - start) * fraction)
    since = _iso(start_day - timedelta(days=RATE_WINDOW))
    return {
        "now": current, "start": start, "start_day": _iso(start_day), "end": end, "end_day": _iso(end_day), "days_left": days_left,
        "expected": expected, "gap": current - expected if current is not None else None,
        # 达标 = 今天在直线上，而且照最近的速度到得了终点（10/12：第一天人人都在线上，光看直线等于没说）
        "ok": current is not None and current >= expected and (forecast is None or forecast >= end),
        "need_per_day": need, "rate": rate, "forecast": forecast,
        "times": round(need / rate, 1) if need and rate and rate > 0 else None,
        "points": [{"day": d, "v": v} for d, v in readings if d >= since],
    }


def conversion(readings: list[tuple[str, int]], views_by_day: dict[str, int], today: date, *, window: int = CONV_WINDOW) -> dict[str, Any] | None:
    """每千播放涨几个粉：最近 window 个过完的日子（有播放读数、前一天有粉丝读数的才算）。"""
    if not readings:
        return None
    first = date.fromisoformat(readings[0][0])
    start = max(today - timedelta(days=window), first + timedelta(days=1))
    yesterday = today - timedelta(days=1)
    if start > yesterday:
        return None
    days = [start + timedelta(days=i) for i in range((yesterday - start).days + 1)]
    views = sum(views_by_day.get(_iso(d)) or 0 for d in days)
    a, b = _value_on(readings, _iso(start - timedelta(days=1))), _value_on(readings, _iso(yesterday))
    if not views or a is None or b is None:
        return None
    return {"per_1k": round((b - a) / views * 1000, 1), "fans": b - a, "views": views, "from": _iso(start), "to": _iso(yesterday)}


def daily_avg(views_by_day: dict[str, int], today: date, *, window: int = RATE_WINDOW) -> int | None:
    vals = [views_by_day[_iso(today - timedelta(days=i))] for i in range(1, window + 1) if _iso(today - timedelta(days=i)) in views_by_day]
    return round(sum(vals) / len(vals)) if vals else None


def _med(vals: list[float | None]) -> float | None:
    vals = [v for v in vals if v is not None]
    return median(vals) if vals else None


def douyin_levers(videos: list[dict[str, Any]], creator: dict[str, dict[str, Any]], today: date, local_day: Any) -> dict[str, Any]:
    """条数和每条的几个数。videos 是自己的号（有 published_at、views）；creator 是后台每条的数（按 video_id）。"""
    days = {local_day(v["published_at"]) for v in videos if v.get("published_at")}
    week = [_iso(today - timedelta(days=i)) for i in range(1, RATE_WINDOW + 1)]
    posted = sorted((v for v in videos if v.get("published_at")), key=lambda v: v["published_at"], reverse=True)
    recent = posted[:LEVER_VIDEOS]
    rows = [creator.get(v["video_id"]) or {} for v in recent]

    def ratio(r: dict[str, Any], key: str, scale: float = 1) -> float | None:
        n, views = r.get(key), r.get("view_count")
        return n / views * scale if n is not None and views else None

    last = posted[0] if posted else None
    return {
        "posted_7": sum(1 for d in week for v in videos if v.get("published_at") and local_day(v["published_at"]) == d),
        "posted_today": local_day(last["published_at"]) == _iso(today) if last else False,
        "days_since_post": (today - date.fromisoformat(local_day(last["published_at"]))).days if last else None,
        "posted_days_7": sum(1 for d in week if d in days),
        "views_median": _med([(r.get("view_count") or v.get("views")) for r, v in zip(rows, recent)]),
        "bounce_2s": _med([r.get("bounce_rate_2s") for r in rows]),
        "retain_5s": _med([r.get("completion_rate_5s") for r in rows]),
        "profile_rate": _med([ratio(r, "homepage_visit_count") for r in rows]),
        "fans_per_1k": _med([ratio(r, "fan_increment", 1000) for r in rows]),
        "videos": len(recent),
    }


def _md(day: str) -> str:
    return f"{int(day[5:7])}/{int(day[8:10])}"


def _say_follow(label: str, f: dict[str, Any], unit: str, need_views: int | None, avg: int | None) -> str:
    """Wendy 这一项的一句话：照现在的速度够不够，不够差几倍、差在哪。只用算出来的数。"""
    if f["now"] is None:
        return f"{label}还没有读数。"
    if f["rate"] is None:
        return f"{label}的读数还不够 3 天，速度先不算；每天要涨 {f['need_per_day']:,}。"
    if f["forecast"] is not None and f["forecast"] >= f["end"]:
        return f"照最近的速度（每天 +{f['rate']:,.0f}），{_md(f['end_day'])} 能到 {f['forecast']:,}，够。"
    head = f"每天要涨 {f['need_per_day']:,}，最近每天 +{f['rate']:,.0f}" + (f"，差 {f['times']} 倍" if f["times"] else "")
    tail = f"；照这个速度 {_md(f['end_day'])} 只到 {f['forecast']:,}" if f["forecast"] is not None else ""
    lever = f"。要每天 {need_views:,} {unit}（现在 {avg:,}）" if need_views and avg else ""
    return head + tail + lever + "。"


def build(*, today: date, followers: list[dict[str, Any]], views: dict[str, dict[str, int]], targets: dict[str, Any],
          x_now: int | None = None, videos: list[dict[str, Any]] | None = None, creator: dict[str, dict[str, Any]] | None = None,
          money: dict[str, Any] | None = None, money_notes: list[dict[str, Any]] | None = None, local_day: Any = None) -> dict[str, Any]:
    """followers: follower_counts 的行；views: {day: {platform: 播放}}（_reach_totals，已含 X 后台的准曝光）。"""
    local_day = local_day or (lambda s: str(s)[:10])
    by: dict[str, list[tuple[str, int]]] = {}
    for r in followers:
        by.setdefault(r["platform"], []).append((r["day"], int(r["followers"])))
    plat_views = {k: {d: v[k] for d, v in views.items() if k in v} for k in ("douyin", "x")}
    out: list[dict[str, Any]] = []

    dy = follow_line(by.get("douyin", []), targets["douyin"], today)
    dy_conv = conversion(by.get("douyin", []), plat_views["douyin"], today)
    dy_avg = daily_avg(plat_views["douyin"], today)
    dy_need = round(dy["need_per_day"] / dy_conv["per_1k"] * 1000) if dy["need_per_day"] and dy_conv and dy_conv["per_1k"] > 0 else None
    lev = douyin_levers(videos or [], creator or {}, today, local_day)
    say = _say_follow("抖音", dy, "播放", dy_need, dy_avg)
    if videos and lev["posted_days_7"] < RATE_WINDOW:  # 没有自己的号（没读到作品）就不说条数
        say += f" 先补条数：最近 7 天只有 {lev['posted_days_7']} 天发了，每天 1 条不商量。"
    out.append({"key": "douyin", "label": "抖音粉丝", **dy, "say": say,
                "tree": {"views_avg": dy_avg, "views_need": dy_need, "conv": dy_conv, **lev}})

    x = follow_line(by.get("x", []), targets["x"], today, now=x_now)
    x_conv = conversion(by.get("x", []), plat_views["x"], today)
    x_avg = daily_avg(plat_views["x"], today)
    x_need = round(x["need_per_day"] / x_conv["per_1k"] * 1000) if x["need_per_day"] and x_conv and x_conv["per_1k"] > 0 else None
    out.append({"key": "x", "label": "X 粉丝", **x, "say": _say_follow("X", x, "曝光", x_need, x_avg),
                "tree": {"views_avg": x_avg, "views_need": x_need, "views_target": targets.get("x_impressions"), "conv": x_conv}})

    m = None
    if money is not None:
        month_last = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        left = (month_last - today).days + 1
        short = max(0.0, float(money["target"]) - float(money["total"]))
        notes = sorted((n for n in money_notes or [] if n.get("day")), key=lambda n: n["day"])
        last = notes[-1] if notes else None
        since = (today - date.fromisoformat(last["day"])).days if last else None
        m = {"total": money["total"], "target": money["target"], "expected": money["expected"], "month": money["month"],
             "need_per_day": round(short / left) if short else 0, "days_left": left,
             "ok": money["expected"] >= money["target"],
             "last_note": last, "ask": since is None or since >= MONEY_ASK_EVERY}
    return {"day": _iso(today), "kpis": out, "money": m}


def brief_text(board: dict[str, Any]) -> str:
    """给 Wendy 每一轮读的那份账：和战况页同一份数。"""
    lines = ["[战况] 这是你背的 KPI（作者 拍板的目标）："]
    for k in board.get("kpis") or []:
        t = k["tree"]
        conv = t.get("conv")
        lines.append(f"- {k['label']}：现在 {k['now'] if k['now'] is not None else '—'}，目标 {k['end_day']} 前 {k['end']:,}，今天应到 {k['expected']:,}（{'达标' if k['ok'] else '落后'}）。{k['say']}"
                     + (f" 每千{'播放' if k['key'] == 'douyin' else '曝光'}涨 {conv['per_1k']} 个粉（{_md(conv['from'])}–{_md(conv['to'])}）。" if conv else ""))
        if k["key"] == "douyin":
            lines.append(f"  最近 7 天发了 {t['posted_7']} 条（{t['posted_days_7']}/7 天）；最近 {t['videos']} 条中位：播放 {t['views_median'] or '—'}，"
                         f"2 秒跳出 {_pct(t['bounce_2s'])}，5 秒完播 {_pct(t['retain_5s'])}，点进主页 {_pct(t['profile_rate'])}。")
    m = board.get("money")
    if m:
        lines.append(f"- 本月收入：¥{m['total']:,.0f} / ¥{m['target']:,.0f}，照这个速度月底 ¥{m['expected']:,.0f}；"
                     + ("这 3 天还没问过他有没有新的收入点，今天问一次。" if m["ask"] else f"上次他说的收入点：{_md(m['last_note']['day'])}「{m['last_note']['note']}」。"))
    return "\n".join(lines)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{round(v * 100)}%"
