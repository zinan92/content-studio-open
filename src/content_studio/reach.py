"""触达 (reach): how many people 作者's content reached each day, across every platform.

作者's first KPI is reach, not conversion. Douyin reach is computed from the view
snapshots the daily sync already records (views gained per day, summed over his
videos). Every other platform has no data connector yet, so its daily views are
typed in by hand until one exists; the numbers are stored per day and platform and
added into the same total.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

# key, label, auto (the workbench pulls the numbers itself), mark (the tile letter), hue.
# 作者 has an account on all nine. `auto` is about *data*, not publishing — 抖音 from its own
# sync, B站 / X / 研习室 from platform_stats (9/25); for the rest he types them in. Brand logos are deliberately not bundled: they are other companies' trademarks,
# so each platform gets a letter tile in its own hue instead.
PLATFORMS: tuple[tuple[str, str, bool], ...] = (
    ("douyin", "抖音", True),
    ("channels", "视频号", False),
    ("xiaohongshu", "小红书", False),
    ("wechat_mp", "公众号", False),
    ("miniprogram", "研习室", True),
    ("x", "X", False),  # 10/20：X 不走 API 了，数据手填
    ("bilibili", "B 站", True),
    ("youtube", "YouTube", False),
    ("xiaoyuzhou", "小宇宙", False),
)
PLATFORM_KEYS = tuple(k for k, _, _ in PLATFORMS)
# 手填的平台去哪看今天的数（9/29：视频号没有开放接口、公众号没认证，只能 作者 每天看一眼填一个数）
STATS_URLS = {
    "channels": "https://channels.weixin.qq.com/platform/statistic/post",
    "x": "https://x.com/i/account_analytics",
    "wechat_mp": "https://mp.weixin.qq.com/",
}
AUTO_KEYS = tuple(k for k, _, auto in PLATFORMS if auto)
# 9/29 作者：注意力分层。主攻 抖音、视频号、小红书（发视频）和 X（发文字 + 每天回复）；
# 公众号、B 站、YouTube 零成本照发，不投入、不看数。页面上主攻的放左边，其余放右边淡一点。
CORE = ("douyin", "channels", "xiaohongshu", "x")
# 出摊时每个平台发的是什么：视频 / 文字 / 图文（默认值；能选的平台在 FORM_CHOICES，选了存在 platform_accounts[key]["form"]）
# 9/29 作者：「如果未来我们做给客户的话，我们要给客户一个选择，让他决定究竟想发什么。」
# 10/5 作者：四大平台（抖音、视频号、小红书、X）文字、图文、视频都能发，默认都是视频——
# 以后几乎是纯视频，要建立信任感。每条内容开始做时定好（选题上的 platform_forms），也能手动改。
FORM = {"douyin": "video", "channels": "video", "xiaohongshu": "video", "bilibili": "video", "youtube": "video",
        "x": "video", "wechat_mp": "text", "miniprogram": "text", "xiaoyuzhou": "audio"}
FORM_LABEL = {"video": "视频", "text": "文章", "cards": "图文", "audio": "音频"}
# 10/7 作者：拍完（或写完）在「标题和封面」那一页的一张表上定每个平台发什么。B 站、YouTube 只能发视频，
# 公众号只能发文章——各一个格子，勾上就发、不勾就这条不发（不发记在 publish_skips，不靠空列表）。
FORM_CHOICES = {**{key: ("video", "cards", "text") for key in ("douyin", "channels", "xiaohongshu", "x")},
                "wechat_mp": ("text",), "bilibili": ("video",), "youtube": ("video",)}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def default_forms(key: str, accounts: dict | None) -> list[str]:
    """这个平台默认发哪几种（10/6 作者：X、小红书可能视频、图文、文字都发，每个平台能多选）。
    设置里选过的优先（新的 forms 列表，或老的单个 form），没选按内置默认；至少一种。"""
    acct = (accounts or {}).get(key) or {}
    choices = FORM_CHOICES.get(key, ())
    chosen = [f for f in _as_list(acct.get("forms")) if f in choices] or ([acct["form"]] if acct.get("form") in choices else [])
    return list(dict.fromkeys(chosen)) or [FORM.get(key, "video")]


def forms_list(topic: dict | None, accounts: dict | None) -> dict[str, list[str]]:
    """这一条内容每个平台发哪几种：这条上定过的 > 设置里的默认 > 内置默认。每个平台至少一种。"""
    chosen = (topic or {}).get("platform_forms") or {}
    out: dict[str, list[str]] = {}
    for key, _, _ in PLATFORMS:
        mine = list(dict.fromkeys(f for f in _as_list(chosen.get(key)) if f in FORM_CHOICES.get(key, ())))
        out[key] = mine or default_forms(key, accounts)
    return out


def form_of(key: str, accounts: dict | None) -> str:
    """这个平台默认发什么（第一种）。老调用方还按单个形式读；多选看 default_forms。"""
    return default_forms(key, accounts)[0]


def forms_for(topic: dict | None, accounts: dict | None) -> dict[str, str]:
    """这一条内容每个平台发什么（第一种）。多选看 forms_list。"""
    return {key: forms[0] for key, forms in forms_list(topic, accounts).items()}


PLATFORM_STYLE: dict[str, dict[str, str]] = {
    "douyin": {"mark": "抖", "hue": "#111111"},  # 9/29 作者：抖音黑，和 X 一样是黑底品牌色
    "channels": {"mark": "视", "hue": "#07C160"},
    "xiaohongshu": {"mark": "红", "hue": "#FF2442"},
    "wechat_mp": {"mark": "公", "hue": "#07C160"},
    "miniprogram": {"mark": "研", "hue": "#5B8FF9"},
    "x": {"mark": "X", "hue": "#111111"},
    "bilibili": {"mark": "B", "hue": "#00A1D6"},
    "youtube": {"mark": "Y", "hue": "#FF0000"},
    "xiaoyuzhou": {"mark": "宇", "hue": "#FA4D3C"},
}


def local_day(stamp: Any) -> str:
    """一次读数（或发布时间）算哪一天：本机时区（北京）的日历日。

    10/3 作者：「概览晚上 12 点就归零，现在到底怎么算的？」——以前拿 UTC 字符串的前 10 位当日期，
    北京时间早上 8 点才换日：半夜 0–8 点的读数记到前一天，页面上的「今天」（本地日期）又 0 点就换了。
    没带时区的时间按字面日期。"""
    text = str(stamp or "")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone().date().isoformat()


def utc_bound(day: date) -> str:
    """本地 day 的 0 点，写成库里读数时间的样子（UTC），给 SQL 的 fetched_at >= ? 用。"""
    return datetime.combine(day, time.min).astimezone().astimezone(timezone.utc).isoformat(timespec="seconds")


def daily_views(snapshots: list[dict[str, Any]], days: int, today: date) -> dict[str, int]:
    """Views gained per day from snapshots (video_id, fetched_at, views).

    For each video, the views on a day = last snapshot that day minus the last snapshot
    before that day. A video's first snapshot counts fully only if it was published within
    the previous day; for an older video it is just the baseline.
    Days with no snapshot for a video contribute nothing for it, so a missed sync shows
    up as a low day rather than being smeared over the week.
    """
    by_video: dict[str, list[tuple[str, int]]] = {}
    published: dict[str, str] = {}
    for row in snapshots:
        if row.get("views") is None:
            continue
        by_video.setdefault(row["video_id"], []).append((row["fetched_at"], int(row["views"])))
        if row.get("published_at"):
            published[row["video_id"]] = local_day(row["published_at"])
    start = today - timedelta(days=days - 1)
    totals = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for video_id, rows in by_video.items():
        rows.sort()
        last_day_value: dict[str, int] = {}
        for stamp, views in rows:
            last_day_value[local_day(stamp)] = views  # the last snapshot of each (local) day wins
        previous: int | None = None
        prev_day: str | None = None
        for day in sorted(last_day_value):
            views = last_day_value[day]
            if previous is None:
                # First snapshot: only a video published within the last day is "new reach";
                # an old video's first snapshot is a baseline, not views gained today.
                fresh = published.get(video_id) is None or published[video_id] >= (date.fromisoformat(day) - timedelta(days=1)).isoformat()
                gained = views if fresh else 0
                if day in totals:
                    totals[day] += gained
            else:
                # 10/12：中间几天没读到（X 只给最近 100 条，老帖被回复挤出去），再读到时涨的是这几天的总和——
                # 平摊回没读到的那几天，不全算在再读到的这一天（10/11 曾因此多算出 19 万）。
                gained = max(0, views - previous)
                gap = [(date.fromisoformat(prev_day) + timedelta(days=i)).isoformat()
                       for i in range(1, (date.fromisoformat(day) - date.fromisoformat(prev_day)).days + 1)]
                share, rest = divmod(gained, len(gap))
                for i, d in enumerate(gap):
                    if d in totals:
                        totals[d] += share + (1 if i < rest else 0)
            previous, prev_day = views, day
    return totals


def summary(days_total: dict[str, dict[str, int]], today: date) -> dict[str, Any]:
    """Totals per day, 7-day average and the pace projected over 30 days."""
    ordered = sorted(days_total)
    per_day = [{"day": d, "total": sum(days_total[d].values()), "by_platform": days_total[d]} for d in ordered]
    last7 = [p["total"] for p in per_day[-7:]]
    avg7 = round(sum(last7) / len(last7)) if last7 else 0
    today_key = today.isoformat()
    today_total = next((p["total"] for p in per_day if p["day"] == today_key), 0)
    return {"days": per_day, "today": today_total, "avg7": avg7, "pace30": avg7 * 30}
