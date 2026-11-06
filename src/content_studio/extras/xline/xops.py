"""X 运营：常驻在 X 页的独立运营 Agent（10/9 作者）。

作者：「X 是高频运营，所以我可能需要在页面有一个常驻专家……他不是我，也不是安娜，必须是一个独立的 X 运营 Agent。」

- 角色写在一份 Markdown 里（默认 examples/xops/X运营.md；profile 的 xops.role 或 CONTENT_STUDIO_XOPS_ROLE 指向他自己改的那份），
  每一轮现读，改文件就是改这个人。
- 每一轮带上他的工作资料：今天和明天的队列、每天发多少、最近 7 天发出去的长帖 / 长文各自的浏览和收藏（A/B 对比）、
  「持续在涨」前 10 条、主人的世界观和原则（世界观文件，只用来判断他有没有观点）。
- 和 Anna 一样走本机的 AI 命令（anna.cli_turn），只读不动手：想让主人点的写成 `[引用] 链接`、`[改数量] long=…` 一行，
  页面变成按钮，主人点了才发生。
- 对话存在 anna_chats 表里单独一个 thread（xops），和 Anna 的不混。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable

THREAD = "xops"
DEFAULT_ROLE = Path(__file__).resolve().parents[2] / "examples" / "xops" / "X运营.md"
PERF_DAYS = 7
PERF_TTL = 30 * 60
QUOTE_RE = re.compile(r"^\s*\[引用\]\s*(https://(?:x|twitter)\.com/\S+/status/\d+)\s*$")
COUNTS_RE = re.compile(r"^\s*\[改数量\]\s*(.+)$")
COUNT_KEYS = {"long": int, "post_share": float, "hot": int, "own_short": int, "articles": int}

Fetch = Callable[[str], Any]


def role_path() -> Path:
    from ... import conf

    raw = conf.value("xops.role")
    path = Path(raw).expanduser() if raw else DEFAULT_ROLE
    return path if path.is_file() else DEFAULT_ROLE


def name() -> str:
    """他叫什么：profile 的 brand.xops，默认 Michael（10/9 晚 作者 起的名字）。"""
    from ... import conf

    return conf.brand()["xops"]


def soul() -> dict[str, Any]:
    from ... import conf

    path = role_path()
    b = conf.brand()
    head = f"你叫 {b['xops']}，是主人的{b['xops_role']}。主人叫「{b['xops']}」或「{b['xops_role']}」说的都是你。\n\n"
    return {"text": head + path.read_text(encoding="utf-8"), "source": str(path), "name": b["xops"]}


# -- 最近 7 天的结果：长帖 / 长文 / 短帖各自多少浏览（10/9 测一周看哪种流量好）------------------------------


def tweet_stats(tweet_id: str, fetch: Fetch) -> dict[str, int] | None:
    """一条帖子现在的浏览、赞、收藏（读 fxtwitter 的公开接口，不用他的 X 密钥）。读不到返回 None。"""
    try:
        t = (fetch(f"https://api.fxtwitter.com/status/{tweet_id}") or {}).get("tweet") or {}
    except Exception:  # noqa: BLE001 - 读不到这一条就跳过
        return None
    if not t:
        return None
    return {"views": int(t.get("views") or 0), "likes": int(t.get("likes") or 0), "bookmarks": int(t.get("bookmarks") or 0),
            "replies": int(t.get("replies") or 0), "reposts": int(t.get("retweets") or 0)}


def kind_of(post: dict[str, Any]) -> str:
    if post.get("hot"):
        return "热点长帖"
    if not post.get("long"):
        return "短帖"
    return "长帖" if post.get("format") == "post" else "长文"


class Perf:
    """最近 7 天发出去的每一条，各读一次数，半小时内不重读。"""

    def __init__(self, fetch: Fetch, ttl: float = PERF_TTL, clock: Callable[[], float] = time.monotonic) -> None:
        self.fetch, self.ttl, self.clock, self._lock, self._cache = fetch, ttl, clock, threading.Lock(), {}

    def summary(self, days: dict[str, Any], today: date) -> dict[str, Any]:
        since = (today - timedelta(days=PERF_DAYS)).isoformat()
        rows = []
        for key, d in sorted(days.items()):
            if key < since:
                continue
            for p in d.get("posts", []):
                m = re.search(r"/status/(\d+)", str(p.get("url") or ""))
                if p.get("state") != "sent" or not m:
                    continue
                rows.append({"day": key, "kind": kind_of(p), "title": str(p.get("text") or "").split("\n", 1)[0].lstrip("# ")[:40],
                             "id": m.group(1), **(self._stats(m.group(1)) or {})})
        by: dict[str, dict[str, Any]] = {}
        for r in rows:
            if "views" not in r:
                continue
            b = by.setdefault(r["kind"], {"n": 0, "views": 0, "bookmarks": 0, "likes": 0})
            b["n"] += 1
            for k in ("views", "bookmarks", "likes"):
                b[k] += r[k]
        for b in by.values():
            b["avg_views"] = b["views"] // b["n"] if b["n"] else 0
        best = sorted((r for r in rows if "views" in r), key=lambda r: r["views"], reverse=True)[:5]
        return {"by_kind": by, "best": best, "count": len(rows)}

    def _stats(self, tid: str) -> dict[str, int] | None:
        with self._lock:
            hit = self._cache.get(tid)
            if hit and self.clock() - hit[0] < self.ttl:
                return hit[1]
        value = tweet_stats(tid, self.fetch)
        with self._lock:
            self._cache[tid] = (self.clock(), value)
        return value


# -- 每一轮带上的资料 --------------------------------------------------------------------------------


def context(*, queue: dict[str, Any], counts: dict[str, Any], perf: dict[str, Any], rising: list[dict[str, Any]], beliefs: str) -> str:
    def day_line(t: dict[str, Any]) -> str:
        posts = [p for p in t.get("posts", []) if not p.get("swapped")]
        by = {}
        for p in posts:
            k = kind_of(p)
            by.setdefault(k, {"排着等勾": 0, "勾了": 0, "发了": 0, "不发": 0})
            s = {"pending": "排着等勾", "approved": "勾了", "sent": "发了", "rejected": "不发"}.get(p.get("state"))
            if s:
                by[k][s] += 1
        return "；".join(f"{k} " + "、".join(f"{s} {n}" for s, n in v.items() if n) for k, v in by.items()) or "还没排"

    perf_lines = [f"- {k}：{b['n']} 条，平均浏览 {b['avg_views']}，收藏共 {b['bookmarks']}，赞共 {b['likes']}"
                  for k, b in (perf.get("by_kind") or {}).items()] or ["- 最近 7 天还没有读到数"]
    best = [f"- {r['day']} {r['kind']}《{r['title']}》浏览 {r['views']} 收藏 {r['bookmarks']}" for r in perf.get("best") or []]
    hot = [f"{i + 1}. [{x.get('category') or ''}] {(x.get('title') or x.get('text') or '')[:60].strip()}（{x.get('author') or ''}，近 10 小时 +{x.get('gained', 0)} 阅读，{x.get('url')}）"
           for i, x in enumerate(rising[:10])]
    today, tomorrow = queue.get("today") or {}, queue.get("tomorrow") or {}
    return f"""## 每天发多少（设置）
长的 {counts.get('long')} 篇，其中长帖占 {counts.get('post_share')}；热点短帖最多 {counts.get('hot')} 条；原话短帖 {counts.get('own_short')} 条

## 队列
今天 {today.get('day', '')}：{day_line(today)}
明天 {tomorrow.get('day', '')}：{day_line(tomorrow)}

## 最近 {PERF_DAYS} 天发出去的结果（长帖 / 长文 / 短帖对比）
{chr(10).join(perf_lines)}
最好的几条：
{chr(10).join(best) or '（还没有）'}

## 持续在涨（过去 10 小时一直有人看的）
{chr(10).join(hot) or '（没读到）'}

## 主人的世界观和原则（判断他对一条热点有没有真实观点，只用这里有的）
{beliefs[:6000] or '（没有）'}"""


def parse_reply(text: str) -> dict[str, Any]:
    """[引用] 链接、[改数量] long=… 变成按钮，其余是话。"""
    actions, kept = [], []
    for line in text.strip().splitlines():
        q, c = QUOTE_RE.match(line), COUNTS_RE.match(line)
        if q:
            if not any(a.get("url") == q.group(1) for a in actions):
                actions.append({"kind": "quote", "url": q.group(1)})
            continue
        if c:
            change = {}
            for k, v in re.findall(r"(\w+)\s*=\s*([\d.]+)", c.group(1)):
                if k in COUNT_KEYS:
                    try:
                        change[k] = COUNT_KEYS[k](float(v)) if COUNT_KEYS[k] is int else float(v)
                    except ValueError:
                        pass
            if change:
                actions.append({"kind": "counts", "change": change})
            continue
        kept.append(line)
    return {"text": "\n".join(kept).strip(), "actions": actions[:6]}


RULES = """---

# 工作台里的规矩

- 你在内容工作台的 X 页上，主人看得到下面这些资料，你也看得到；每一轮都是最新的。
- 你只读不动手。想让主人点一下的写成单独一行：`[引用] 帖子链接`（打开引用帖草稿）或 `[改数量] long=数字 post_share=0到1 hot=数字`。
- 讲数据时说清是哪几条、多少；资料里没有的数，就说没有，不要编。"""


def system_prompt(soul_text: str) -> str:
    return f"{soul_text}\n\n{RULES}"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_turn(*, ctx_text: str, message: str, session_id: str | None, turn_fn: Callable[[str, str, str | None], dict],
             screen: str = "") -> dict[str, Any]:
    from ..team import anna

    s = soul()
    user = f"<X 运营的资料>\n{ctx_text}\n</X 运营的资料>{anna.screen_block(screen)}\n\n主人：{message.strip()}"
    result = turn_fn(system_prompt(s["text"]), user, session_id)
    parsed = parse_reply(result["text"])
    return {"role": "xops", "text": parsed["text"], "actions": parsed["actions"], "at": now_iso(), "session_id": result.get("session_id")}

