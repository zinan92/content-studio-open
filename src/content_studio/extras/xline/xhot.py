"""X 热榜：读 xzhishu.com（X 指数榜）的公开接口，看中文 X 上什么在火（10/8 作者，#539）。

作者：「热门话题榜、热门长文榜、热门推文榜，这些都有用。我觉得阅读最多和收藏最多都是有用的。」
放两处：X 页一块「X 上在火」、进项一个 tab，同一份数据。

- 长文、推文：/rankings/tweets/leaderboard，period 24h / 48h，dimension reads / bookmarks / latest，
  category 按分类（默认 AI）；长文多一个 contentType=article。
- 话题：/topics/hot，dimension heat / reads，带每个话题的源推文。
- 他们说每 10 分钟更新一次，这里也缓存 10 分钟，不多打。数据是第三方整理的，仅供参考。
- 「收进进项」写一篇笔记进「我收藏的」文件夹，格式照 X 收藏那条管线（frontmatter 有 url、collected_at），
  同一条帖子只存一次。
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

API = "https://xzhishu.com/api/v1"
SITE = "https://xzhishu.com"
TTL = 600
PAGE = 30
KINDS = ("topics", "articles", "tweets")
PERIODS = ("24h", "48h")
DIMENSIONS = {"topics": ("heat", "reads"), "articles": ("reads", "bookmarks", "latest", "velocity"),
              "tweets": ("reads", "bookmarks", "latest", "velocity")}
# 他关心的领域在前；all = 不筛（推文榜不筛基本是社会新闻）
CATEGORIES = (("ai", "AI"), ("tech-digital", "科技数码"), ("knowledge-sharing", "知识分享"), ("indie-dev", "独立开发"),
              ("startup-global", "创业&出海"), ("all", "全部"))

Fetch = Callable[[str], Any]


class HotError(RuntimeError):
    """Shown to 作者 as-is."""


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 content-studio", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise HotError(f"读不到 X 指数榜：{exc}") from exc


def _when(ms: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _creator(c: dict[str, Any] | None) -> dict[str, str]:
    c = c or {}
    return {"author": str(c.get("name") or ""), "handle": str(c.get("handle") or "")}


def post_url(value: Any) -> str:
    """榜单链接只接受 X/Twitter 的 HTTPS 原帖，统一格式便于跨榜去重。"""
    try:
        url = urllib.parse.urlsplit(str(value or "").strip())
        if url.scheme != "https" or url.netloc.lower() not in ("x.com", "www.x.com", "twitter.com", "www.twitter.com"):
            return ""
        if not re.fullmatch(r"/(?:[A-Za-z0-9_]+|i/web)/status/[0-9]+/?", url.path):
            return ""
        return "https://x.com" + url.path.rstrip("/")
    except ValueError:
        return ""


def post_item(it: dict[str, Any], kind: str) -> dict[str, Any]:
    text = str(it.get("articlePreview") or it.get("content") or "").strip()
    title = str(it.get("articleTitle") or "").strip() or text.split("\n", 1)[0][:80]
    return {"id": str(it.get("url") or it.get("id") or ""), "kind": kind, "rank": it.get("rank"), "title": title, "text": text,
            "url": post_url(it.get("url")), **_creator(it.get("creator")), "category": str(it.get("category") or ""),
            "reads": int(it.get("reads") or 0), "bookmarks": int(it.get("bookmarks") or 0), "likes": int(it.get("likes") or 0),
            "reposts": int(it.get("reposts") or 0), "comments": int(it.get("comments") or 0),
            "published_at": _when(it.get("publishedAt")), "cover": it.get("articleCoverUrl") or None,
            "trend": [int(x or 0) for x in it.get("trafficTrend") or []]}


# -- 持续在涨（10/9 作者：「过去 10 个小时什么东西在持续获得注意力……我自己有点看不过来」）------------------
# 每条帖子带一条逐小时的流量线（发出来以后每小时多了多少阅读）。持续在涨 = 最近 10 小时一直有人看，而且最后几小时还没掉下去；
# 刚冒头一两个小时的、早就过气的都不算。几个他关心的分类各取「涨得最快」的那页，合起来按最近 10 小时的量排。

RISING_SOURCES = (("tweets", "ai"), ("tweets", "tech-digital"), ("tweets", "knowledge-sharing"), ("tweets", "indie-dev"),
                  ("tweets", "startup-global"), ("articles", "all"))
RISING_HOURS = 10
RISING_MIN_HOURS = 5      # 至少看了 5 个小时，才说得上「持续」
RISING_STILL = 0.4        # 最后 3 小时的平均，至少是这 10 小时最高那小时的四成：还在被看
RISING_TOP = 20


def rising_score(trend: list[int]) -> tuple[int, bool]:
    """(最近 10 小时多了多少阅读, 算不算持续在涨)。流量线第一格是发出来那一刻的 0，不算。"""
    hours = list(trend[1:]) if trend and trend[0] == 0 else list(trend)
    last = hours[-RISING_HOURS:]
    if len(hours) < RISING_MIN_HOURS or not last or max(last) <= 0:
        return sum(last), False
    still = sum(last[-3:]) / len(last[-3:])
    return sum(last), still >= RISING_STILL * max(last)


def rising(boards: list[dict[str, Any]], top: int = RISING_TOP) -> list[dict[str, Any]]:
    """几个榜合起来去重，留下持续在涨的，按最近 10 小时的量排。"""
    seen, out = set(), []
    for b in boards:
        for it in b.get("items") or []:
            if not it.get("url") or it["url"] in seen:
                continue
            seen.add(it["url"])
            gained, ok = rising_score(it.get("trend") or [])
            if ok:
                out.append({**it, "kind": it.get("kind") or "tweets", "gained": gained, "hours": max(0, len(it.get("trend") or []) - 1)})
    out.sort(key=lambda x: x["gained"], reverse=True)
    return [{**x, "rank": i + 1} for i, x in enumerate(out[:top])]


def topic_item(t: dict[str, Any]) -> dict[str, Any]:
    tweets = [{"id": str(s.get("url") or s.get("id") or ""), "kind": "tweets", "title": str(s.get("content") or "").split("\n", 1)[0][:80],
               "text": str(s.get("content") or "").strip(), "url": post_url(s.get("url")), **_creator(s.get("creator")),
               "reads": int(s.get("readsCount") or 0), "likes": int(s.get("likesCount") or 0),
               "published_at": _when(s.get("publishedAt"))} for s in t.get("sourceTweets") or []]
    return {"id": str(t.get("id") or ""), "kind": "topics", "rank": t.get("rank"), "title": str(t.get("title") or ""),
            "text": str(t.get("summary") or ""), "heat": t.get("heatDisplay") or t.get("heat"), "tags": list(t.get("tags") or []),
            "tweet_count": int(t.get("tweetCount") or 0), "reads": int(t.get("readsCount") or 0), "tweets": tweets}


def board_url(kind: str, period: str, dimension: str, category: str) -> str:
    if kind == "topics":
        return f"{API}/topics/hot?" + urllib.parse.urlencode({"limit": PAGE, "period": period, "dimension": dimension, "detail": 1})
    q = {"period": period, "dimension": dimension, "page": 1, "pageSize": PAGE}
    if kind == "articles":
        q["contentType"] = "article"
    if category != "all":
        q["category"] = category
    return f"{API}/rankings/tweets/leaderboard?" + urllib.parse.urlencode(q)


def check(kind: str, period: str, dimension: str, category: str) -> None:
    if kind not in KINDS:
        raise HotError("只有话题、长文、推文三个榜")
    if period not in PERIODS:
        raise HotError("时间只能是 24 小时或 48 小时")
    if dimension not in DIMENSIONS[kind]:
        raise HotError("这个榜不能这样排")
    if category not in dict(CATEGORIES):
        raise HotError("没有这个分类")


class Board:
    """同一组参数 10 分钟内只读一次。"""

    def __init__(self, fetch: Fetch = fetch_json, ttl: float = TTL, clock: Callable[[], float] = time.monotonic) -> None:
        self.fetch, self.ttl, self.clock, self._lock, self._data = fetch, ttl, clock, threading.Lock(), {}

    def get(self, kind: str, period: str = "24h", dimension: str | None = None, category: str = "ai", *, fresh: bool = False) -> dict[str, Any]:
        dimension = dimension or DIMENSIONS.get(kind, ("reads",))[0]
        check(kind, period, dimension, category)
        key = (kind, period, dimension, "all" if kind == "topics" else category)
        with self._lock:
            hit = self._data.get(key)
            if hit and not fresh and self.clock() - hit[0] < self.ttl:
                return hit[1]
        raw = self.fetch(board_url(kind, period, dimension, category)) or {}
        if raw.get("code") and not raw.get("items") and not raw.get("topics"):
            raise HotError(f"X 指数榜不认这次查询：{raw.get('message') or raw.get('code')}")
        items = [topic_item(t) for t in raw.get("topics") or []] if kind == "topics" else [post_item(it, kind) for it in raw.get("items") or []]
        value = {"kind": kind, "period": period, "dimension": dimension, "category": key[3], "items": items,
                 "updated_at": _when(raw.get("updatedAt")), "source": f"{SITE}/rankings/{kind}"}
        with self._lock:
            self._data[key] = (self.clock(), value)
        return value

    def rising(self, *, fresh: bool = False) -> dict[str, Any]:
        """持续在涨：几个榜各读一页（各自也缓存 10 分钟），合起来算。"""
        boards = [self.get(kind, "24h", "velocity", cat, fresh=fresh) for kind, cat in RISING_SOURCES]
        stamps = [b["updated_at"] for b in boards if b.get("updated_at")]
        return {"kind": "rising", "period": "10h", "items": rising(boards), "updated_at": max(stamps) if stamps else None,
                "source": f"{SITE}/rankings/tweets"}


# -- 收进进项 -----------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    s = re.sub(r"[^\w一-鿿]+", "-", text.lower()).strip("-")
    # 留够日期和链接摘要的位置；Linux 文件名限制按 UTF-8 字节计算。
    return s.encode("utf-8")[:200].decode("utf-8", errors="ignore") or "x"


def note_name(item: dict[str, Any], now: datetime | None = None) -> str:
    now = now or datetime.now()
    digest = hashlib.sha1(str(item.get("url") or item.get("title") or "").encode()).hexdigest()[:10]
    return f"{now:%y%m%d}_X_{_slug(str(item.get('title') or ''))}__{digest}.md"


def save(folder: Path, item: dict[str, Any], now: datetime | None = None) -> tuple[Path, bool]:
    """存一篇笔记进「我收藏的」。同一条帖子（按链接）已经存过就不再存，返回 (路径, 是不是新存的)。"""
    url = post_url(item.get("url"))
    if not url:
        raise HotError("这一条没有链接，存不了")
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    old = next(iter(folder.glob(f"*__{digest}.md")), None)
    if old:
        return old, False
    now = now or datetime.now()
    title = str(item.get("title") or "").replace("\n", " ").strip() or url
    who = " ".join(x for x in (item.get("author") or "", item.get("handle") or "") if x)
    meta = {"id": url, "url": url, "source_name": "X 热榜", "profile_name": "X 热榜", "platform": "twitter", "channel": "x",
            "author": who, "category": item.get("category") or "", "source_category": "hot-list",
            "published_at": item.get("published_at") or "", "collected_at": f"{now:%Y-%m-%d}"}
    numbers = "，".join(f"{label} {item[k]}" for k, label in (("reads", "阅读"), ("bookmarks", "收藏"), ("likes", "点赞")) if item.get(k))
    # JSON 字符串也是 YAML 的双引号标量；冒号、引号不会破坏 Obsidian 属性。
    body = "\n".join(f"{k}: {json.dumps(str(v).replace(chr(10), ' '), ensure_ascii=False)}" for k, v in meta.items())
    text = f"---\n{body}\n---\n\n# {title}\n\nsource: X 热榜 · {who} · [link]({url}){f'（{numbers}）' if numbers else ''}\n\n{str(item.get('text') or '').strip()}\n"
    path = folder / note_name({**item, "url": url}, now)
    path.write_text(text, encoding="utf-8")
    return path, True


def tweet_id(url: str) -> str | None:
    m = re.search(r"/status/(\d+)$", post_url(url))
    return m.group(1) if m else None
