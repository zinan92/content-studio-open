"""全网粉丝：每天记一次每个平台的粉丝数，画成一条线，再照最近的速度算月底能到多少。

10/5 作者：「全网粉丝画一个 curve，能让我看到进度」「预期月底粉丝数……I can see the results, I can see it happen。」

- 能自己读的：抖音（每天同步自己的号时顺手存）、X（v1.1 verify_credentials，只读）、B站（relation/stat，用投稿那份登录）。
- 读不到的：小红书、视频号、公众号、YouTube（YouTube 要改 content-ops 的脚本，还没做）。作者 想填就填一次，
  之后一直按最后一次的数算，不是每天的活。
- 一天一个平台一行；同一天读到多次，留最后一次。以前没记过，不倒推：抖音 9/21、9/29 两个点是从库的备份里找到的。
- 不拿每条视频的「涨粉」加起来倒推总数——那不算掉粉，是编出来的。
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
import json
from typing import Any, Callable
import urllib.request

from .store import StudioStore

AUTO = ("douyin", "x", "bilibili")
MANUAL = ("xiaohongshu", "channels", "wechat_mp", "youtube")
LABELS = {"douyin": "抖音", "x": "X", "bilibili": "B站", "xiaohongshu": "小红书", "channels": "视频号", "wechat_mp": "公众号", "youtube": "YouTube"}
RATE_WINDOW = 14  # 涨粉速度看最近两周
MIN_SPAN = 3  # 两次读数至少隔 3 天才算速度，不然一天的抖动就是「速度」


class FollowersError(RuntimeError):
    pass


def x_followers() -> int:
    from .extras.positioning import x_profile

    n = x_profile.read().get("followers_count")
    if n is None:
        raise FollowersError("X 没返回粉丝数")
    return int(n)


def bilibili_followers() -> int:
    from . import platform_stats as ps

    try:
        raw = json.loads(ps.BILI_COOKIES.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FollowersError("没有 B站 登录") from exc
    cookies = {c["name"]: c["value"] for c in (raw.get("cookie_info") or {}).get("cookies") or [] if c.get("name")}
    mid = cookies.get("DedeUserID")
    if not mid:
        raise FollowersError("B站 登录里没有账号 ID")
    request = urllib.request.Request(f"https://api.bilibili.com/x/relation/stat?vmid={mid}", headers={
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()), "User-Agent": ps.UA, "Referer": "https://space.bilibili.com/"})
    data = ps._get_json(request)
    if data.get("code") != 0:
        raise FollowersError(f"B站 返回 {data.get('code')}：{data.get('message')}")
    return int((data.get("data") or {})["follower"])


FETCHERS: dict[str, Callable[[], int]] = {"x": x_followers, "bilibili": bilibili_followers}


def sync(store: StudioStore, today: date, fetchers: dict[str, Callable[[], int]] | None = None) -> dict[str, Any]:
    """今天读一次：抖音拿刚同步完的自己的号，X、B站 各问一次。一个平台失败不影响别的。"""
    out: dict[str, Any] = {}
    from .reach import local_day

    me = store.self_account()
    # 抖音今天没同步成（cookies 过期、风控）就不记：账号表里是昨天的数，记成今天的会把线拉平、把速度拉成 0
    if me and me.get("follower_count") is not None and local_day(me.get("last_synced_at")) == today.isoformat():
        store.set_followers(today.isoformat(), "douyin", int(me["follower_count"]), "auto")
        out["douyin"] = int(me["follower_count"])
    for key, fetch in (FETCHERS if fetchers is None else fetchers).items():
        try:
            n = fetch()
        except Exception as exc:  # noqa: BLE001 - 一个平台读不到，照样记别的
            out[key] = f"error: {exc}"[:160]
            continue
        store.set_followers(today.isoformat(), key, n, "auto")
        out[key] = n
    return out


def _value_on(readings: list[tuple[str, int]], day: str) -> int | None:
    """day 那天这个平台算多少：那天或之前最后一次读数；比第一次读数还早，就按第一次的（画平，页面上说明）。"""
    before = [v for d, v in readings if d <= day]
    if before:
        return before[-1]
    return readings[0][1] if readings else None


def summary(rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """rows: day, platform, followers（按 day 排）。返回曲线的点、现在多少、月底预计多少。

    曲线只在有读数的那几天落点，总数 = 每个平台到那天为止最后一次的数。某个平台比别的晚开始记，
    它开始之前按它第一次的数画平（late 里列出来）。
    月底预计 = 现在 + 每个平台最近两周的日均涨粉 × 到月底还剩几天。哪个平台读数不够隔 3 天，它的速度先不算（pending）。"""
    by_platform: dict[str, list[tuple[str, int]]] = {}
    for r in rows:
        by_platform.setdefault(r["platform"], []).append((r["day"], int(r["followers"])))
    if not by_platform:
        return {"points": [], "latest": None, "latest_day": None, "month_end": None, "rate": None, "platforms": [], "late": [], "pending": []}
    days = sorted({d for readings in by_platform.values() for d, _ in readings})
    first_day = days[0]
    points = [{"day": d, "total": sum(_value_on(r, d) or 0 for r in by_platform.values()),
               "by_platform": {k: _value_on(r, d) for k, r in by_platform.items()}} for d in days]
    latest = points[-1]
    rate, pending = 0.0, []
    since = (today - timedelta(days=RATE_WINDOW)).isoformat()
    for key, readings in by_platform.items():
        last_day, last = readings[-1]
        base = next(((d, v) for d, v in readings if d >= since), None)
        span = (date.fromisoformat(last_day) - date.fromisoformat(base[0])).days if base else 0
        if span < MIN_SPAN:
            pending.append(LABELS.get(key, key))
            continue
        rate += (last - base[1]) / span
    month_last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    left = (month_last - today).days
    return {
        "points": points, "latest": latest["total"], "latest_day": latest["day"],
        "rate": round(rate, 1), "month_end": round(latest["total"] + rate * left), "month_last": month_last.isoformat(),
        "platforms": [LABELS.get(k, k) for k in by_platform],
        "late": [LABELS.get(k, k) for k, r in by_platform.items() if r[0][0] > first_day],
        "pending": pending,
    }


def month_reach(days_total: dict[str, int], today: date) -> dict[str, Any]:
    """预期本月触达（10/5 作者 改名，原来叫「30 天节奏」= 7 天日均 × 30）：
    这个月已经过完的日子加起来 + 最近 7 个过完的日子的日均 × 这个月还剩几天（含今天）。今天还没过完，不拿今天的半截数。"""
    month_first = today.replace(day=1)
    month_last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    done_days = sorted(d for d in days_total if d < today.isoformat())
    last7 = [days_total[d] for d in done_days[-7:]]
    avg7 = round(sum(last7) / len(last7)) if last7 else 0
    so_far = sum(days_total[d] for d in done_days if d >= month_first.isoformat())
    left = (month_last - today).days + 1
    return {"so_far": so_far, "avg7": avg7, "left": left, "expected": so_far + avg7 * left, "month": today.month}
