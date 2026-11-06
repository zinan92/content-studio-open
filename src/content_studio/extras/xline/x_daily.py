"""X 每日短帖：Wendy 前一晚排好，作者 早上打勾，勾了的当天排着发（10/5 作者）。

作者：「每天我要发 10 条、20 条短帖，这些内容都是提前规划好的，每一条都有一个勾和叉。早上起来一看，
可能在一分钟之内，我就把每一条都打了勾（代表 approve），或者有一两条我不说这个，就打个叉，这样就完了。」
「排着发，先 10 条。」

规矩：
- 只用他自己的话：原始输出（不含客户咨询）、网站上的原则和预测。整理只删口语、可调顺序、不改词
  （writer.original_words_rules），每条单独核对能在它的来源里找到（posts_fidelity），对不上的扔掉，不凑数。
- 他打了勾才会发；没打勾的当天结束就作废，不会发。打叉的那条来源记成「放一边」，Wendy 以后不再排它。
- 排着发：北京时间 9:00–22:00，按剩下的条数把时间平均摊开，两条之间至少 20 分钟。22:00 没发完的挪到第二天最前面。
- 发之前先在盘上记「正在发」，发完记「发了」和链接。服务重启时还停在「正在发」的，绝不再发一遍，
  标成「不确定发没发」，让他去 X 看一眼（#390 / #392 的教训：先记结果再放手）。
- 遇到 429（额度用完）当天停下，剩下的不再试；他可以复制去 X 自己发，再点「我发了」。

长帖（10/7 作者，#505）：「直接把 obsidian 里面的 park 原始输出搬进来，但是需要我每天早上 review，我确认了才能发，
每天 2-3 个长文。」每晚同一时间再排 3 篇：一篇笔记整篇原文（去 Markdown 记号，第一行是笔记标题），不经过模型、
一个字不改。和短帖同一个队列：一样打勾才发、一样隔开发，打叉的那篇放一边。
10/7 作者：「每次排未来7天的吧」（#507）——长帖随时补满明天起 7 天，短帖还是每晚排第二天。
10/8 作者（#525）：「今天这几篇都是我要拍视频的……要换一篇吧。」拍成视频的笔记（选题用了它）不进长帖，
已经排进去还没勾的自动换掉；每篇长帖能「换一篇」：这篇不发、放一边，下一篇顶在原位置。
10/8 作者（#535）：「其实拍成视频的也可以发，但是要过一段时间。」——从最近一个用到它的选题建起压 VIDEO_HOLD_DAYS 天。
10/8 作者（#537）：长帖改叫长文，发成 X 图文文章：park-writing 改一遍、配个人形象插图，他看过勾了才发（x_long.py）。
10/9 作者：每天发多少不写死（store 的 x_counts）；长的分两种测一周——长文（上面那种）和长帖：他的短句（原则、预测、
笔记里的段落）按一个主题挑 6–12 条合并成一条纯文字长帖（format="post"），只用原话，每条单独核对。他自己原话的
短帖曾停用；10/11 起 own_short 默认 10，短帖和引用帖通过 QA 后按开关自动放行。
代码里还叫 long；帖子多一个 prep：None 等着做 → running 在做 → ready 做好了 / failed 没做成。只做今天和明天的，
做好了才能打勾，没做好的勾不上、也不会发。
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable

from ... import writer
from . import write_flow, write_patch, write_steps
from ...paths import config_dir
from ...x_post import CREDITS_OUT, MAX_LONG, MAX_WEIGHTED, weighted_length

FILE = "x_daily.json"
BJ = timezone(timedelta(hours=8))
PER_DAY = 10
PER_DAY_LONG = 3
LONG_AHEAD = 7                     # 长帖提前排几天
VIDEO_HOLD_DAYS = 30               # 拍成视频的笔记，从选题建起压这么多天再进长帖
LONG_MIN_CHARS = 300               # 太短的不算长帖，留给短帖
# 不整篇搬的：客户的事、过时的每日盘面、给 AI 的 prompt、清单类草稿
LONG_SKIP = re.compile(r"客户|咨询|追踪表|每日交易分析|README|prompt|问卷|idea dump", re.IGNORECASE)
TITLE_NOISE = re.compile(r"^(已发\s*)?(\d{4}-\d{2}-\d{2}_+|\d{6,8}[-_\s]*)?(口播稿[_\s]*)?")
START, HOURS = dtime(0, 0), 24      # 10/13 作者「改成 24 小时，全天的」：以前 9:00–22:00
PLAN_AT = dtime(21, 0)            # 每晚这个点排第二天的
ARTICLE_HELD = "X 没让直接发，已存草稿"  # routes._x_send / x_article.publish_article：草稿建好了、发布被拒
MIN_GAP = timedelta(minutes=3)   # 10/13 短帖 100 + Repost 100：9:00–22:00 共 780 分钟，平均 3.9 分钟一条；5 分钟一条一天最多 156，到不了
CREDITS_RETRY = timedelta(hours=1)  # X API 余额用完（402）：停发，每小时拿一条试一次，充值了就自己接着发
RECENT_DAYS = 14                   # 两周内排过的来源不再排
OWN_KINDS = ("obsidian", "principle", "prediction")
NOTE_CHARS = 1500
MAX_NOTES, MAX_LINES = 25, 30
PER_SOURCE = 3                     # 10/12：一天 50 条短帖，一篇笔记可以出几条（不同段落）
SHORT_BATCH = 25                   # 一次模型调用最多写这么多条
SHORT_TOPUP_UNTIL = dtime(23, 0)   # 今天的短帖不够数，23:00 前补（10/13 起全天发，夜里也要有得发）
SHORT_TOPUP_FROM = dtime(0, 0)
POST = re.compile(r"<<<POST\s+source=(\d+)\s*>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)

_LOCK = threading.RLock()


class DailyError(RuntimeError):
    """Shown to 作者 as-is."""


def now_bj(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(BJ)


def day_key(d: datetime | date) -> str:
    return (d.date() if isinstance(d, datetime) else d).isoformat()


def path(root: Path | None = None) -> Path:
    return (root or config_dir()) / FILE


def load(p: Path) -> dict[str, Any]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("days", {})
    return data


def save(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".x_daily-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def day(data: dict[str, Any], key: str) -> dict[str, Any]:
    return data["days"].setdefault(key, {"posts": [], "planned_at": None, "halted": None})


# -- 排：Wendy 从他自己的话里挑 -------------------------------------------------------


def candidates(sources: list[dict[str, Any]], *, avoid: set[str]) -> list[dict[str, Any]]:
    """他自己的话里，没发过、没放一边、两周内没排过的。原始输出老的在前（积压的先清），原则 / 预测都是一句。"""
    notes, lines = [], []
    for group in sources:
        if group["key"] not in OWN_KINDS:
            continue
        for c in group["items"]:
            if c["id"] in avoid or not (c.get("body") or "").strip():
                continue
            row = {"id": c["id"], "kind": group["key"], "label": group["label"], "title": c["title"], "text": c["body"].strip()}
            (notes if group["key"] == "obsidian" else lines).append((c.get("at") or "", row))
    notes.sort(key=lambda x: x[0])
    return [r for _, r in notes[:MAX_NOTES]] + [r for _, r in lines[:MAX_LINES]]


def plan_prompt(cands: list[dict[str, Any]], n: int, error: str | None = None, recent: list[str] | None = None,
                per_source: int = PER_SOURCE) -> str:
    listed = "\n\n".join(f"### 来源 {i}（{c['label']}：{c['title']}）\n{c['text'][:NOTE_CHARS]}" for i, c in enumerate(cands))
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    seen = ("\n\n## 最近两周已经发过的短帖（意思别重复）\n" + "\n".join(f"- {t[:60]}" for t in recent[:80])) if recent else ""
    return f"""你是 Wendy，替 作者 排明天要发在 X 上的 {n} 条短帖。他早上会一条条打勾或打叉，勾了的才发。

只能用下面 作者自己的话，规矩不能破：
{writer.original_words_rules()}

怎么挑：
- 一条帖子只用一个来源；一个来源最多 {per_source} 条，而且是讲不同事情的不同段落。挑最有判断、最能单独成立的那一句或那一小段。
- 每条单独拿出来也看得懂；长短随内容，50 字到 140 字最好，中文算两个字，整条不超过 {MAX_WEIGHTED}。
- 题目错开，不要几条讲同一件事。不加话题标签、不加表情、不加「关注我」。
- 原话里没有的东西一个字都不要加。凑不够 {n} 条就少给，不要硬凑。

{listed}{seen}

## 输出
每条放在单独一行的 <<<POST source=来源编号>>> 和单独一行的 <<<END>>> 之间，前后不要有其他说明。{retry}"""


def build(cands: list[dict[str, Any]], *, n: int, write_fn: Callable[[str], str], attempts: int = 2,
          recent: list[str] | None = None, per_source: int = PER_SOURCE) -> list[dict[str, Any]]:
    """模型挑、代码核对：来源编号要对、不超长、每条能在它的来源里找到（只删、只挪）、和最近发过的不重复。对不上的扔掉。
    10/12 作者 要每天 50 条：一个来源最多 PER_SOURCE 条（不同段落），一次最多 SHORT_BATCH 条。"""
    from .x_line import plain, posts_fidelity

    if not cands:
        raise DailyError("没有能排的了：你的原始输出、原则、预测都发过或放一边了")
    n = min(n, SHORT_BATCH)
    recent = list(recent or [])
    error, kept = None, []
    for _ in range(attempts):
        raw = str(write_fn(plan_prompt(cands, n, error, recent, per_source)) or "")
        found = POST.findall(raw)
        if not found:
            error = "没有按 <<<POST source=编号>>> 格式返回"
            continue
        kept, used, dropped = [], {}, 0
        for idx, text in found:
            i, text = int(idx), text.strip()
            if not (0 <= i < len(cands)) or used.get(i, 0) >= per_source or not text or weighted_length(text) > MAX_WEIGHTED:
                dropped += 1
                continue
            if posts_fidelity([text], plain(cands[i]["text"])) < writer.MIN_FIDELITY:
                dropped += 1
                continue
            if any(writer.fidelity(text, old) >= 0.6 for old in recent + [k["text"] for k in kept]):  # 和发过的、这一批的撞了
                dropped += 1
                continue
            used[i] = used.get(i, 0) + 1
            c = cands[i]
            # 和 X 单独一条线素材卡的 id 一样：发过、放一边的记录对得上
            kept.append({"text": text, "source_id": c["id"], "source_kind": c["label"], "source_title": c["title"]})
            if len(kept) >= n:
                break
        if kept:
            return kept
        error = f"{dropped} 条都没过核对（改了他的词、超长或来源不对）"
    raise DailyError(f"没排出来：{error}")


def long_title(title: str) -> str:
    """笔记标题当第一行：去掉「已发」、日期前缀这些他自己归档用的记号，字不动。"""
    cleaned = re.sub(r"[_\s-]*\d{4}-\d{2}-\d{2}$", "", TITLE_NOISE.sub("", title.strip())).strip()  # 末尾的归档日期也去掉
    cleaned = cleaned.lstrip("：:、，,_-—· ").strip()  # 「口播稿：半年前的…」去掉记号后别留个冒号开头
    return cleaned or title.strip()


_DANGLING = re.compile(r"^(最后|然后|接下来|还有|再就是|其次|另外|第[一二三四五六七八九十\d]+)")


def unfinished_tail(text: str) -> bool:
    """笔记停在没写完的地方：最后一段只是个「最后就是 X。」的小标题，或者停在冒号 / 逗号 / 省略号上。
    10/12 作者 的「复杂的工作流」那篇就是录前提纲，最后一点只有标题，发出去读者看到的是讲到一半。"""
    paras = [x.strip() for x in re.split(r"\n\s*\n", text or "") if x.strip()]
    if not paras:
        return False
    last = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", paras[-1]).strip()
    if last and last[-1] in "：:，,、…—":
        return True
    return len(last) <= 24 and bool(_DANGLING.match(last))


def long_candidates(sources: list[dict[str, Any]], *, avoid: set[str], read_full: Callable[[str], str],
                    n: int = PER_DAY_LONG) -> list[dict[str, Any]]:
    """原始输出里能整篇搬的，新写的在前。素材卡里的正文截过断，这里按路径读整篇。"""
    from .x_line import plain

    notes = [c for g in sources if g["key"] == "obsidian" for c in g["items"]
             if c["id"] not in avoid and not LONG_SKIP.search(f"{c['id']} {c['title']}")]
    notes.sort(key=lambda c: c.get("at") or "", reverse=True)
    out = []
    for c in notes:
        try:
            body = plain(read_full(c["id"]) or "")
        except Exception:  # noqa: BLE001 - 读不到这篇就跳过，不拖累别的
            continue
        title = long_title(c["title"])
        text = f"{title}\n\n{body}" if title and body.split("\n", 1)[0].strip() != title else body
        if len(body) < LONG_MIN_CHARS or weighted_length(text) > MAX_LONG or unfinished_tail(body):
            continue
        out.append({"text": text, "long": True, "source_id": c["id"], "source_kind": "我写的", "source_title": c["title"]})
        if len(out) >= n:
            break
    return out


def interleave(posts: list[dict[str, Any]], longs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """长帖插进还没发的那一段里，平均隔开，不扎堆。"""
    start = next((i for i, x in enumerate(posts) if x["state"] in ("pending", "approved")), len(posts))
    head, rest = posts[:start], list(posts[start:])
    step = len(rest) / (len(longs) + 1) if longs else 0
    for j, x in enumerate(longs):
        rest.insert(round(step * (j + 1)) + j, x)
    return head + rest


def recent_sources(data: dict[str, Any], today: str) -> set[str]:
    """两周内排过的：整篇用过的笔记，和合进长帖的每一条短句。"""
    since = (date.fromisoformat(today) - timedelta(days=RECENT_DAYS)).isoformat()
    out = set()
    for k, d in data["days"].items():
        if k >= since:
            for p in d["posts"]:
                if p.get("source_id"):
                    out.add(p["source_id"])
                out.update(p.get("items") or [])
    return out


def has_short(d: dict[str, Any]) -> bool:
    return any(not x.get("long") for x in d["posts"])


def short_count(d: dict[str, Any]) -> int:
    """今天还算数的短帖（打叉、作废的不算）。"""
    return sum(1 for x in d["posts"] if not x.get("long") and not x.get("quote_url") and x["state"] not in ("rejected", "expired", "moved"))


def recent_short_texts(data: dict[str, Any], today: str) -> list[str]:
    """两周内排过的短帖正文（新的在前）：给模型看「别重复这些意思」，代码也拿它查重。"""
    since = (date.fromisoformat(today) - timedelta(days=RECENT_DAYS)).isoformat()
    out = []
    for k in sorted(data["days"], reverse=True):
        if since <= k <= today:
            out += [x["text"] for x in data["days"][k]["posts"] if not x.get("long") and not x.get("quote_url") and x.get("text")]
    return out


def short_avoid(data: dict[str, Any], today: str) -> set[str]:
    """短帖不按来源两周回避（一天 50 条，笔记不够用）；只避开今天、昨天已经出过 PER_SOURCE 条的来源。"""
    since = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    used: dict[str, int] = {}
    for k, d in data["days"].items():
        if k >= since:
            for x in d["posts"]:
                if not x.get("long") and x.get("source_id"):
                    used[x["source_id"]] = used.get(x["source_id"], 0) + 1
    return {sid for sid, n in used.items() if n >= PER_SOURCE}


def short_topup_due(p: Path, target: int, now: datetime | None = None) -> int:
    """今天的短帖还差几条要补（20:00 前；今天连续两轮没补出来就不补了）。"""
    now = now_bj(now)
    if target <= 0 or now.time() >= SHORT_TOPUP_UNTIL:
        return 0
    with _LOCK:
        d = load(p)["days"].get(day_key(now))
    if now.time() < SHORT_TOPUP_FROM or (d and (d.get("short_topup_fails") or 0) >= 2):
        return 0
    d = d or {"posts": []}
    last = d.get("short_topup_at")
    if last and now - datetime.fromisoformat(last) < timedelta(minutes=10):
        return 0
    return max(0, target - short_count(d))


# -- 10/12 晚 作者：短帖 = 反常识暴论 ---------------------------------------------------------------------------
# 「短帖：一天 20 个，内容直接发反常识暴论，不用管火不火……用我的 principles 和 predictions，不一定非得是原话，用这些理念。」
TAKE_KINDS = ("principle", "prediction")
TAKE_POOL = 40


def take_candidates(sources: list[dict[str, Any]], *, avoid: set[str]) -> list[dict[str, Any]]:
    """他网站上的原则、预测，一条一句；最近用过的往后放（不扔，原则就那么多条）。"""
    rows = [{"id": c["id"], "kind": g["key"], "label": g["label"], "title": c.get("title") or "", "text": (c.get("body") or "").strip()}
            for g in sources if g["key"] in TAKE_KINDS for c in g["items"] if (c.get("body") or "").strip()]
    rows.sort(key=lambda r: r["id"] in avoid)
    return rows[:TAKE_POOL]


def takes_prompt(cands: list[dict[str, Any]], n: int, *, style: str, recent: list[str], error: str | None = None) -> str:
    listed = "\n".join(f"[{i}]（{c['label']}）{c['text'][:300]}" for i, c in enumerate(cands))
    seen = ("\n\n## 最近两周发过的短帖（意思别重复）\n" + "\n".join(f"- {t[:60]}" for t in recent[:80])) if recent else ""
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    return f"""你替 作者 写 {n} 条 X 短帖，每条一句「反常识暴论」。

## 他的说话方式（park-writing）
{style.strip()[:3000]}

## 怎么写
- 每条从下面他的一条原则或预测出发：可以就用那句原话（说得更狠一点），也可以按那个理念说一个大多数人不同意、但他认为对的判断。
- 第一句就是判断，说满，不铺垫；20–140 字；口语、短、sharp。
- 不问句结尾，不写「你怎么看」「评论区」「关注我」；不编他的经历（不写「我试了」「我客户」），不编数字（数字只能来自原句）。
- 一条只讲一件事，几条之间不要讲同一件事。凑不够就少给。

## 他的原则和预测
{listed}{seen}

## 输出
每条放在单独一行的 <<<POST source=编号>>> 和单独一行的 <<<END>>> 之间，前后不要有其他说明。{retry}"""


def build_takes(cands: list[dict[str, Any]], *, n: int, style: str, write_fn: Callable[[str], str],
                check_fn: Callable[[str, dict[str, Any]], str | None], recent: list[str] | None = None, attempts: int = 2) -> list[dict[str, Any]]:
    """模型写、代码核对：编号对、不超长、不引战结尾、不编经历数字（check_fn = x_suggest.check）、和发过的不重复。"""
    if not cands or n <= 0:
        return []
    n, recent, error = min(n, SHORT_BATCH), list(recent or []), None
    for _ in range(attempts):
        found = POST.findall(str(write_fn(takes_prompt(cands, n, style=style, recent=recent, error=error)) or ""))
        if not found:
            error = "没有按 <<<POST source=编号>>> 格式返回"
            continue
        out = []
        for idx, text in found:
            i, text = int(idx), text.strip()
            if not (0 <= i < len(cands)) or not text or weighted_length(text) > MAX_WEIGHTED or HOT_BAIT.search(text):
                continue
            if check_fn(text, {"title": cands[i]["title"], "text": cands[i]["text"]}):
                continue
            if any(writer.fidelity(text, old) >= 0.6 for old in recent + [o["text"] for o in out]):
                continue
            c = cands[i]
            out.append({"text": text, "source_id": c["id"], "source_kind": c["label"], "source_title": c["text"][:60], "take": True})
            if len(out) >= n:
                break
        if out:
            return out
        error = "一条都没过核对（太长、引战结尾、编了数字或经历、和发过的重复）"
    raise DailyError(f"暴论没写出来：{error}")


def topup_shorts(p: Path, key: str, *, sources: list[dict[str, Any]], skipped: set[str], posted: set[str],
                 write_fn: Callable[[str], str], n: int, now: datetime | None = None,
                 style: str = "", check_fn: Callable[[str, dict[str, Any]], str | None] | None = None) -> int:
    """今天的短帖补到设定的条数：一次最多 SHORT_BATCH 条，加在队列后面，等 QA 过了自动发。返回补了几条。
    10/12 晚起短帖是反常识暴论（他的原则、预测出发）；没有原则、预测可用时才退回从原始输出摘原话。"""
    with _LOCK:
        data = load(p)
        avoid = skipped | short_avoid(data, key)  # 发过的来源不整篇回避：靠正文查重，不同段落还能再出
        recent = recent_short_texts(data, key)
    takes = take_candidates(sources, avoid={x.get("source_id") for d in data["days"].values() for x in d["posts"] if x.get("take")})
    try:
        if takes and check_fn is not None:
            shorts = build_takes(takes, n=n, style=style, write_fn=write_fn, check_fn=check_fn, recent=recent)
        else:
            shorts = build(candidates(sources, avoid=avoid), n=n, write_fn=write_fn, recent=recent)
    except DailyError:
        shorts = []
    with _LOCK:
        data = load(p)
        d = day(data, key)
        stamp = now_bj(now).isoformat(timespec="seconds")
        start = sum(1 for x in d["posts"] if str(x.get("id", "")).startswith(f"{key}-S"))
        d["posts"] += [{**x, "id": f"{key}-S{start + i}", "state": "pending", "planned_at": stamp} for i, x in enumerate(shorts)]
        d["short_topup_at"] = stamp
        d["short_topup_fails"] = 0 if shorts else (d.get("short_topup_fails") or 0) + 1
        save(p, data)
    return len(shorts)


# -- 长帖：他的短句按主题合并成一条（10/9 作者）---------------------------------------------------------

POST_THEME = re.compile(r"<<<THEME\s+title=(.+?)\s*>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)
POST_ITEM = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
POST_MIN, POST_MAX = 5, 12
PARA_MIN, PARA_MAX = 40, 400


def split_counts(counts: dict[str, Any] | None) -> tuple[int, int]:
    """长的总数拆成（长文篇数, 长帖条数）。"""
    c = counts or {}
    total = max(0, int(c.get("long", PER_DAY_LONG)))
    posts = round(total * float(c.get("post_share", 0)))
    return total - posts, posts


def post_items(sources: list[dict[str, Any]], *, avoid: set[str], limit: int = 160) -> list[dict[str, Any]]:
    """能合进长帖的短句：网站上的原则、预测（一条一句），笔记里单独成立的段落。id 记到段落，发过的段落两周内不再用。"""
    from .x_line import plain

    items = []
    for g in sources:
        if g["key"] in ("principle", "prediction"):
            items += [{"id": c["id"], "text": c["body"].strip(), "label": g["label"], "title": c["title"]}
                      for c in g["items"] if c["id"] not in avoid and (c.get("body") or "").strip()]
        elif g["key"] == "obsidian":
            for c in g["items"]:
                if LONG_SKIP.search(f"{c['id']} {c['title']}"):
                    continue
                for i, para in enumerate(re.split(r"\n\s*\n", plain(c.get("body") or ""))):
                    pid = f"{c['id']}#p{i}"
                    if pid not in avoid and PARA_MIN <= len(para.strip()) <= PARA_MAX:
                        items.append({"id": pid, "text": para.strip(), "label": "我写的", "title": c["title"]})
    return items[:limit]


def long_post_prompt(items: list[dict[str, Any]], k: int, error: str | None = None) -> str:
    listed = "\n".join(f"[{i}]（{x['label']}·{x['title'][:20]}）{x['text'][:PARA_MAX]}" for i, x in enumerate(items))
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    return f"""你是 作者 的 X 运营。把下面 作者自己说过的话，按主题合并成 {k} 条 X 长帖（一条纯文字的长 post）。

- 每条长帖一个主题：挑 {POST_MIN}–{POST_MAX} 条讲同一件事、能互相接上的话，排成读得顺的顺序。
- 只用他的原话：
{writer.original_words_rules()}
- 每条话用一次，不同长帖不重复用同一条。主题之间错开。
- 每条长帖一个标题：10–20 个字，尽量用原话里的词，说清这一条在讲什么；不要问句、不要「你知道吗」「评论区」这类引互动的话。

{listed}

## 输出
每条长帖：单独一行 <<<THEME title=标题>>>，下面每行一条「[编号] 这条话（可以只删口语）」，最后单独一行 <<<END>>>。
前后不要有其他说明。{retry}"""


def build_long_posts(items: list[dict[str, Any]], *, k: int, write_fn: Callable[[str], str], attempts: int = 2) -> list[dict[str, Any]]:
    """模型挑主题和顺序，代码核对：每条话都能在它的来源里找到、不重复、条数够、不超 X 长帖上限。对不上的那条长帖扔掉。"""
    from .x_line import posts_fidelity

    if k <= 0:
        return []
    if len(items) < POST_MIN:
        raise DailyError("能合进长帖的短句不够了：原则、预测、笔记段落都用过了")
    error = None
    for _ in range(attempts):
        raw = str(write_fn(long_post_prompt(items, k, error)) or "")
        themes = POST_THEME.findall(raw)
        if not themes:
            error = "没有按 <<<THEME title=…>>> 格式返回"
            continue
        out, used = [], set()
        for title, body in themes:
            title = title.strip().strip("「」\"'")
            picked = []
            for line in body.splitlines():
                m = POST_ITEM.match(line)
                if not m:
                    continue
                i, text = int(m.group(1)), m.group(2).strip()
                if not (0 <= i < len(items)) or i in used or not text:
                    continue
                if posts_fidelity([text], items[i]["text"]) < writer.MIN_FIDELITY:
                    continue
                picked.append((i, text))
            text = f"{title}\n\n" + "\n\n".join(t for _, t in picked)
            if not (2 <= len(title) <= 30) or len(picked) < POST_MIN or weighted_length(text) > MAX_LONG:
                continue
            used |= {i for i, _ in picked}
            out.append({"text": text, "long": True, "format": "post", "prep": "ready", "items": [items[i]["id"] for i, _ in picked],
                        "source_kind": "我的短句合并", "source_title": title})
            if len(out) >= k:
                break
        if out:
            return out
        error = "每条长帖都没过核对（条数不够、改了他的词或超长）"
    raise DailyError(f"长帖没排出来：{error}")


def plan(p: Path, key: str, *, sources: list[dict[str, Any]], posted: set[str], skipped: set[str],
         write_fn: Callable[[str], str], read_full: Callable[[str], str] | None = None, short: bool = True,
         long_avoid: set[str] = frozenset(),
         n: int = PER_DAY, n_long: int = PER_DAY_LONG, n_post: int = 0, now: datetime | None = None) -> dict[str, Any]:
    """排 key 这一天的：短帖和长的各排一次，排过的不重排（他可能已经打了勾）。
    长的 = n_long 篇长文（笔记整篇，后面再改写配图）+ n_post 条长帖（短句合并，这里就排好）。
    长文先挑（不经过模型，不会失败），长帖、短帖再避开它用过的；哪样没排出来，别的照样留着。"""
    with _LOCK:
        data = load(p)
        d = day(data, key)
        need_short, need_long = short and n > 0 and not has_short(d), read_full is not None and not d.get("long_planned_at")
        if not need_short and not need_long:
            return d
        avoid = posted | skipped | recent_sources(data, key)
    longs = long_candidates(sources, avoid=avoid | long_avoid, read_full=read_full, n=n_long) if need_long else []
    shorts, error = [], None
    if need_long and n_post > 0:
        used = {x["source_id"] for x in longs}
        try:
            longs += build_long_posts(post_items(sources, avoid=avoid | used), k=n_post, write_fn=write_fn)
        except DailyError as exc:
            error = exc
    if need_short:
        try:
            with _LOCK:
                data = load(p)
                short_skip, recent = short_avoid(data, key), recent_short_texts(data, key)
            shorts = build(candidates(sources, avoid=skipped | short_skip | {x.get("source_id") for x in longs}),
                           n=n, write_fn=write_fn, recent=recent)
        except DailyError as exc:
            error = error or exc
    with _LOCK:
        data = load(p)
        d = day(data, key)
        stamp = now_bj(now).isoformat(timespec="seconds")
        if shorts and not has_short(d):
            d["posts"] = [{**x, "id": f"{key}-{i}", "state": "pending", "planned_at": stamp} for i, x in enumerate(shorts)] + d["posts"]
            d["planned_at"] = stamp
        if need_long and not d.get("long_planned_at"):
            rows = [{**x, "id": f"{key}-{'P' if x.get('format') == 'post' else 'L'}{i}", "state": "pending", "planned_at": stamp}
                    for i, x in enumerate(longs)]
            d["posts"] = interleave(d["posts"], rows)
            d["long_planned_at"] = stamp
            d["long_target"] = [n_long, n_post]
        save(p, data)
    if error is not None:
        raise error
    return d


def held_video_notes(topics: list[dict[str, Any]], now: datetime | None = None, days: int = VIDEO_HOLD_DAYS) -> set[str]:
    """还在压着的视频笔记：最近一个用到它的选题建起不到 days 天。选题的建立时间读不出来就当刚建。"""
    cutoff = now_bj(now) - timedelta(days=days)
    held = set()
    for t in topics:
        try:
            made = datetime.fromisoformat(str(t.get("created_at")))
            made = made if made.tzinfo else made.replace(tzinfo=timezone.utc)
        except ValueError:
            made = None
        if made is None or made > cutoff:
            held |= {f"obsidian:{n}" for n in (t.get("note_paths") or [])}
    return held


def _find(d: dict[str, Any] | None, post_id: str) -> dict[str, Any] | None:
    return next((x for x in (d or {}).get("posts", []) if x["id"] == post_id), None)


def swap_long(p: Path, key: str, post_id: str, *, sources: list[dict[str, Any]], avoid: set[str],
              read_full: Callable[[str], str], reason: str | None = None, allow_empty: bool = False,
              now: datetime | None = None) -> dict[str, Any] | None:
    """「换一篇」：这篇长帖不发，从笔记池里拿下一篇顶在它后面。打过叉的也能换。
    池子空了：报「没有能换的了」；allow_empty（自动换拍成视频的那种）时照样把这篇撤下，返回 None。"""
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None or not post.get("long"):
            raise DailyError("找不到这篇长文")
        if post["state"] not in ("pending", "approved", "rejected") or post.get("swapped"):
            raise DailyError("这一篇已经在发、发过或换过了")
        avoid = avoid | recent_sources(data, key)
    new = long_candidates(sources, avoid=avoid, read_full=read_full, n=1)
    if not new and not allow_empty:
        raise DailyError("没有能换的了：原始输出里能整篇搬的都排过、发过、放一边或拍成视频了")
    with _LOCK:
        data = load(p)
        d = day(data, key)
        post = _find(d, post_id)
        if post is None or post["state"] not in ("pending", "approved", "rejected"):
            raise DailyError("这一篇刚刚开始发了，换不了")
        stamp = now_bj(now).isoformat(timespec="seconds")
        row = None
        if new:
            ids = {x["id"] for x in d["posts"]}
            i = sum(1 for x in d["posts"] if x.get("long"))
            while f"{key}-L{i}" in ids:
                i += 1
            row = {**new[0], "id": f"{key}-L{i}", "state": "pending", "planned_at": stamp, **({"note": reason} if reason else {})}
            d["posts"].insert(d["posts"].index(post) + 1, row)
        post.update(state="rejected", swapped=True, decided_at=stamp, **({"swap_reason": reason} if reason else {}))
        save(p, data)
        return row


def video_note_posts(p: Path, video_notes: set[str], now: datetime | None = None) -> list[tuple[str, str]]:
    """今天和以后排着、还没勾的长帖里，笔记已经被拍成视频的（他勾过的不动：那是他自己选的）。"""
    today = day_key(now_bj(now))
    with _LOCK:
        days = load(p)["days"]
    return [(k, x["id"]) for k, d in sorted(days.items()) if k >= today for x in d["posts"]
            if x.get("long") and x["state"] == "pending" and x.get("source_id") in video_notes]


# -- 他打勾 / 打叉 / 改字 -------------------------------------------------------------


def mark(p: Path, key: str, post_id: str, *, state: str | None = None, text: str | None = None,
         post_cap: int | None = None) -> dict[str, Any]:
    """打勾 / 打叉 / 改字。post_cap：这一天最多勾几篇长帖（10/9 作者：热点长帖和短句合并的长帖一共 5 篇）。"""
    with _LOCK:
        data = load(p)
        d = data["days"].get(key)
        post = next((x for x in (d or {}).get("posts", []) if x["id"] == post_id), None)
        if post is None:
            raise DailyError("找不到这一条")
        if post["state"] not in ("pending", "approved", "rejected"):
            raise DailyError("这一条已经在发或发过了，改不了")
        if post.get("swapped"):
            raise DailyError("这一篇已经换掉了")
        if text is not None:
            text = text.strip()
            if not text:
                raise DailyError("不能是空的")
            if not post.get("long") and weighted_length(text) > MAX_WEIGHTED:
                raise DailyError(f"太长了（{weighted_length(text)}，上限 {MAX_WEIGHTED}，中文算两个）")
            if post["text"] != text and (not post.get("long") or post.get("quote_url")):
                post.update(qa=None, auto=False, auto_reason=None)
                if post["state"] == "approved":
                    post.update(state="pending", decided_at=None)
            post["text"] = text
        if state is not None:
            if state not in ("pending", "approved", "rejected"):
                raise DailyError("只能打勾、打叉或者撤回")
            if state == "approved" and post.get("long") and post.get("prep") != "ready":
                raise DailyError("这篇长文还在改写、配图，做好了才能勾")
            if state == "approved" and post.get("format") == "post" and post_cap is not None and post["state"] != "approved":
                taken = sum(1 for x in d["posts"] if x.get("format") == "post" and x["state"] in ("approved", "sending", "sent", "unsure"))
                if taken >= post_cap:
                    raise DailyError(f"今天的 {post_cap} 篇长帖已经勾满了：先把一篇撤回或打叉，再勾这一篇")
            if state == "approved":
                for gate, flag in (("qa_complete", "qa_complete"), ("qa_value_ok", "qa_value")):
                    if post.get(gate) is False:
                        post[f"{flag}_override"] = True
                        post.pop(f"{flag}_held", None)
            post.update(auto=False, auto_reason=None)
            post["state"] = state
            post["decided_at"] = now_bj().isoformat(timespec="seconds") if state != "pending" else None
        save(p, data)
        return post


# -- 排着发 ------------------------------------------------------------------------


def roll(data: dict[str, Any], today: str) -> bool:
    """过了一天：昨天勾了没发的挪到今天最前面；没打勾的作废。返回有没有改动。"""
    changed = False
    for key in sorted(k for k in data["days"] if k < today):
        old = data["days"][key]
        # 他自己点了「发文」、还没存进草稿的长文也跟着挪到今天（做长文要时间，不能过夜就作废）
        carry = [x for x in old["posts"] if (x["state"] == "approved" and not x.get("hot"))
                 or (x["state"] == "pending" and x.get("manual_publish"))]
        for x in old["posts"]:
            # 热点隔夜就凉了：勾了没发完的也不挪到第二天
            if x["state"] in ("pending", "ready_manual") or (x["state"] == "approved" and x.get("hot")):
                x["state"], changed = "expired", True
        if carry:
            d = day(data, today)
            for x in carry:
                x["state"] = "moved"
            d["posts"] = [{**x, "state": "pending" if x.get("manual_publish") else "approved", "id": f"{today}-c{x['id']}", "carried_from": key}
                          for x in carry] + d["posts"]
            changed = True
    t = data["days"].get(today)
    if t and str(t.get("halted") or "").startswith(ARTICLE_HELD):  # 10/10 之前长文被限也停了一整天：改成只停长文
        t["articles_paused"], t["halted"], changed = t["halted"], None, True
    return changed


def unsure_after_restart(data: dict[str, Any]) -> bool:
    """服务起来时还停在「正在发」的：不知道 X 那边收到没有，绝不重发。"""
    changed = False
    for d in data["days"].values():
        for x in d["posts"]:
            if x["state"] == "sending":
                x["state"], x["error"], changed = "unsure", "发的时候服务重启了，不确定发没发：去 X 看一眼", True
    return changed


def last_sent(d: dict[str, Any]) -> datetime | None:
    stamps = [datetime.fromisoformat(x["sent_at"]) for x in d["posts"] if x.get("sent_at")]
    return max(stamps) if stamps else None


def window(d: date) -> tuple[datetime, datetime]:
    """这一天能发的时段（北京时间）：START 起 HOURS 小时；24 小时 = 当天 0 点到第二天 0 点。"""
    start = datetime.combine(d, START, tzinfo=BJ)
    return start, start + timedelta(hours=HOURS)


def gap(last: datetime, left: int) -> timedelta:
    """从上一条发出算起，剩下 left 条平均摊到时段结束之前（最后一条也落在结束前），两条之间至少 MIN_GAP。"""
    end = window(last.astimezone(BJ).date())[1]
    return max(MIN_GAP, (end - last) / (left + 1))


def is_article(x: dict[str, Any]) -> bool:
    """发成 X 图文文章的那种（长文、合集）；长帖、热点长帖是普通帖子。"""
    return bool(x.get("long")) and x.get("format") != "post" and not x.get("quote_url")


def auto_decide(d: dict[str, Any], *, auto_send: dict[str, bool] | None = None,
                now: datetime | None = None) -> bool:
    """只裁决仍待确认且 QA 成功完成的短帖和引用帖。人工打叉、发送中和回执不动。"""
    changed = False
    switches = {"short": True, "quote": True, **(auto_send or {})}
    for post in d["posts"]:
        if post.get("from_pick") and post.get("format") == "post" and post["state"] == "pending" and post.get("qa") == "ready":
            # 他在候选里点了「长帖」就是要发：QA 完整就排着发（价值关不拦他自己选的）；不完整留给他看
            if post.get("qa_complete") is not False:
                post.update(state="approved", auto=True, decided_at=now_bj(now).isoformat(timespec="seconds"))
                changed = True
            continue
        kind = "quote" if post.get("quote_url") else "short" if not post.get("long") else None
        if kind == "short" and switches[kind] and post["state"] == "pending" and not post.get("swapped"):
            post.update(state="approved", auto=True, decided_at=now_bj(now).isoformat(timespec="seconds"))  # 短帖不过 QA
            changed = True
            continue
        if not kind or not switches[kind] or post["state"] != "pending" or post.get("qa") != "ready" or post.get("swapped"):
            continue
        issues = []
        if post.get("qa_complete") is False:
            issues = post.get("qa_issues") or ["内容不完整"]
        elif kind == "quote" and post.get("qa_value_ok") is False:
            issues = post.get("qa_value_issues") or ["价值关未通过"]
        post.update(state="rejected" if issues else "approved", auto=True,
                    auto_reason=f"没过 QA：{issues[0]}" if issues else None,
                    decided_at=now_bj(now).isoformat(timespec="seconds"))
        changed = True
    return changed


def hold_qa(d: dict[str, Any]) -> bool:
    """发送前兜底；人工看过结果再单独勾选才放行。"""
    changed = False
    for post in d["posts"]:
        if post["state"] != "approved" or not post.get("long"):
            continue
        for gate, flag in (("qa_complete", "qa_complete"), ("qa_value_ok", "qa_value")):
            if post.get(gate) is False and not post.get(f"{flag}_override"):
                post.update(state="pending", decided_at=None)
                post[f"{flag}_held"] = True
                changed = True
    return changed


def sendable(d: dict[str, Any]) -> list[dict[str, Any]]:
    """勾过、能发的：长文要改写配图做好了（老的没做过的长帖勾了也等着，不发纯文字）。
    长文当天被 X 限了（articles_paused），长文挪到明天，长帖照发（10/10：X 文章发布接口单独限额）。"""
    hold_qa(d)
    return [x for x in d["posts"] if x["state"] == "approved" and (not x.get("long") or x.get("prep") == "ready")
            and not x.get("manual_publish")  # 10/12 作者：长文他自己发，工作台只存进 X 草稿
            and not (d.get("articles_paused") and is_article(x))]


def left_today(d: dict[str, Any], queue: list[dict[str, Any]], target: int) -> int:
    """还要发几条：按每天的目标（短帖 + Repost）减去今天发出去的算，排着的比这个多就按排着的。
    10/13：以前只按「现在排着几条」摊，短帖、Repost 是白天陆续写出来的，早上排着的少，间隔拉得很长（9 点发完 10 点才发）。"""
    sent = sum(1 for x in d["posts"] if x["state"] == "sent")
    return max(len(queue), target - sent)


def due(d: dict[str, Any], now: datetime, target: int = 0) -> dict[str, Any] | None:
    """现在该发哪一条（纯函数，好测）：在 9:00–22:00 里、没被 429 停下、离上一条够久了，就发排第一的那条勾过的。"""
    now = now.astimezone(BJ)
    queue = sendable(d)
    start, end = window(now.date())
    if not queue or d.get("halted") or not (start <= now < end):
        return None
    last = last_sent(d)
    if last and last.astimezone(BJ).date() == now.date() and now - last < gap(last, left_today(d, queue, target)):
        return None
    return queue[0]


def next_at(d: dict[str, Any], now: datetime, target: int = 0) -> str | None:
    """页面上「下一条大约几点」。"""
    now = now.astimezone(BJ)
    queue = sendable(d)
    if not queue or d.get("halted"):
        return None
    start, end = window(now.date())
    if now < start:
        return start.strftime("%H:%M")
    if now >= end:
        return f"明天 {START.strftime('%H:%M')}"
    last = last_sent(d)
    at = max(now, last + gap(last, left_today(d, queue, target))) if last and last.astimezone(BJ).date() == now.date() else now
    return at.strftime("%H:%M")


# -- 10/12 作者：长文长帖价值、完整度不够的不给他看，2–3 篇找一个共同主题拼一篇顶上 ------------------------------
MERGE_PER_DAY = 6   # 每天最多拼几次（每次一次模型选组 + 一次排段落）


def hide_failed(post: dict[str, Any]) -> bool:
    """QA 说价值不够或不完整、他也没说「照发」的待勾长文长帖：藏起来（不删），等着拼合并稿。"""
    if (not post.get("long") or post.get("quote_url") or post.get("hidden") or post["state"] != "pending"
            or post.get("qa") != "ready" or post.get("from_pick")):  # 他自己从候选里点的：不藏
        return False
    weak = [why for gate, flag, why in (("qa_value_ok", "qa_value_override", "价值不够"), ("qa_complete", "qa_complete_override", "不完整"))
            if post.get(gate) is False and not post.get(flag)]
    if not weak:
        return False
    post.update(hidden=True, hidden_reason="、".join(weak))
    return True


def merge_next(p: Path, now: datetime | None = None) -> tuple[str, list[dict[str, Any]]] | None:
    """今天、明天各有 2 篇以上藏起来、还没拼过的单篇（拼出来的合并稿再不过就不再拼）：拿去拼。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    for key in (day_key(now), day_key(now + timedelta(days=1))):
        d = days.get(key) or {"posts": []}
        if (d.get("merge_count") or 0) >= MERGE_PER_DAY:
            continue
        pool = [x for x in d["posts"] if x.get("hidden") and not x.get("merged_into") and not x.get("merged_from")
                and (x.get("merge_tries") or 0) < 2 and x["state"] == "pending"]
        pool.sort(key=lambda x: x.get("merge_tries") or 0)  # 没试过的先拼
        batch = pool[:6]
        if len(batch) >= 2 and sorted(x["id"] for x in batch) != d.get("merge_last_failed"):  # 同一组刚拼不出来，不原样再试
            return key, batch
    return None


def add_merged(p: Path, key: str, tried: list[str], group: dict[str, Any] | None, *, reason: str = "",
               now: datetime | None = None) -> dict[str, Any] | None:
    """拼好了：一篇合并长帖进队列（等 QA，过了给他勾）；用掉的单篇记 merged_into，没用上的留着。没拼成：这几篇各记一次，最多试两次。"""
    with _LOCK:
        data = load(p)
        d = day(data, key)
        d["merge_count"] = (d.get("merge_count") or 0) + 1
        by_id = {x["id"]: x for x in d["posts"]}
        row = None
        if group:
            out = group["outputs"][0]
            used = {str(s["path"]).removeprefix("obsidian:") for s in group["sources"]}
            n = sum(1 for x in d["posts"] if x.get("merged_from"))
            row = {"id": f"{key}-M{n}", "text": f"# {out['title']}\n\n{out['body'].strip()}\n", "long": True, "format": "post",
                   "prep": "ready", "state": "pending", "planned_at": now_bj(now).isoformat(timespec="seconds"),
                   "merged_from": sorted(used), "source_kind": "合并", "source_title": out["title"],
                   "mainline": group.get("mainline", "")}
            d["posts"].append(row)
            for pid in tried:  # 这一组没用上的，留着下一次接着拼
                x = by_id.get(pid)
                if x is not None and str(x.get("source_id") or x["id"]).removeprefix("obsidian:") in used:
                    x["merged_into"] = row["id"]
        else:
            for pid in tried:
                if pid in by_id:
                    by_id[pid].update(merge_tries=(by_id[pid].get("merge_tries") or 0) + 1, merge_error=reason[:200])
            d["merge_last_failed"] = sorted(tried)
        save(p, data)
        return row


# -- 10/12 作者：每天从原始输出挑 10 篇候选，他点「发文 / 长帖 / 拆解 / 不发」 ---------------------------------
# 「长文还是我自己发。你每天帮我从 作者 的原始输出里选 10 个 candidates。」
# 发文 = 改写配图封面 QA 之后存进 X 文章草稿，他自己去发；长帖 = 整篇原话一条纯文字长帖，QA 完整就自动发；
# 拆解 = 拆成几条短帖，进自动发；不发 = 放一边，不再推。
PICKS_PER_DAY = 10
PICK_ACTIONS = {"article": "发文", "post": "长帖", "split": "拆解", "skip": "不发"}
SPLIT_MAX = 8


def picks_due(p: Path, now: datetime | None = None) -> str | None:
    """今天还没有候选就排今天的；21:00 以后明天还没有就排明天的。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    today, tomorrow = day_key(now), day_key(now + timedelta(days=1))
    if "picks" not in (days.get(today) or {}):
        return today
    if now.time() >= PLAN_AT and "picks" not in (days.get(tomorrow) or {}):
        return tomorrow
    return None


def picked_sources(data: dict[str, Any]) -> set[str]:
    """候选里出现过的笔记（不管他点了什么，不再推），加上两周内整篇发过长文 / 长帖的。
    短帖用过的不算：一天 70 条短帖几乎每篇笔记都摘过句子，整篇还没发过。"""
    since = (now_bj().date() - timedelta(days=RECENT_DAYS)).isoformat()
    out = {pk["source_id"] for d in data["days"].values() for pk in d.get("picks") or []}
    for k, d in data["days"].items():
        if k >= since:
            out |= {x["source_id"] for x in d["posts"] if x.get("long") and x.get("source_id") and x["state"] in ACTIVE + ("drafted",)}
    return out


def add_picks(p: Path, key: str, notes: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        data = load(p)
        d = day(data, key)
        if "picks" in d:
            return d["picks"]
        d["picks"] = [{"id": f"{key}-K{i}", "source_id": x["source_id"], "title": long_title(x.get("source_title") or ""),
                       "text": x["text"], "chars": len(x["text"]), "choice": None} for i, x in enumerate(notes[:PICKS_PER_DAY])]
        d["picks_at"] = now_bj(now).isoformat(timespec="seconds")
        save(p, data)
        return d["picks"]


def choose(p: Path, key: str, pick_id: str, action: str, now: datetime | None = None) -> dict[str, Any]:
    """他点了一个按钮：发文 / 长帖 进长文区（发文走改写配图，长帖整篇原话）；拆解交给后台拆；不发只记下。"""
    if action not in PICK_ACTIONS:
        raise DailyError("只能选发文、长帖、拆解或不发")
    with _LOCK:
        data = load(p)
        d = data["days"].get(key) or {}
        pick = next((x for x in d.get("picks") or [] if x["id"] == pick_id), None)
        if pick is None:
            raise DailyError("找不到这篇候选")
        if pick.get("choice"):
            raise DailyError(f"这篇已经选了「{PICK_ACTIONS[pick['choice']]}」")
        stamp = now_bj(now).isoformat(timespec="seconds")
        pick.update(choice=action, chosen_at=stamp)
        base = {"text": pick["text"], "long": True, "source_id": pick["source_id"], "source_kind": "我写的",
                "source_title": pick["title"], "state": "pending", "planned_at": stamp, "from_pick": pick_id}
        if action == "article":
            row = {**base, "id": f"{key}-A{pick_id.rsplit('K', 1)[-1]}", "manual_publish": True}
            d["posts"].append(row)
            pick["made"] = [row["id"]]
        elif action == "post":
            row = {**base, "id": f"{key}-P{pick_id.rsplit('K', 1)[-1]}", "format": "post", "prep": "ready"}
            d["posts"].append(row)
            pick["made"] = [row["id"]]
        elif action == "split":
            pick["split"] = "running"
        save(p, data)
        return pick


def split_next(p: Path, now: datetime | None = None) -> tuple[str, dict[str, Any]] | None:
    """点了「拆解」、还没拆的（拆到一半服务重启了的也接着拆）。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    for key in (day_key(now), day_key(now + timedelta(days=1))):
        for pk in (days.get(key) or {}).get("picks") or []:
            if pk.get("choice") == "split" and pk.get("split") == "running":
                return key, pk
    return None


def split_pick(p: Path, key: str, pick_id: str, *, write_fn: Callable[[str], str], now: datetime | None = None) -> int:
    """把这一篇拆成几条能单独成立的短帖（只删、只挪，四字组核对，和最近发过的查重），排进今天的短帖，过 QA 自动发。"""
    with _LOCK:
        data = load(p)
        pick = next(x for x in data["days"][key]["picks"] if x["id"] == pick_id)
        recent = recent_short_texts(data, key)
    note = {"id": pick["source_id"], "kind": "obsidian", "label": "我写的", "title": pick["title"], "text": pick["text"]}
    try:
        shorts, error = build([note], n=SPLIT_MAX, write_fn=write_fn, recent=recent, per_source=SPLIT_MAX), None
    except DailyError as exc:
        shorts, error = [], str(exc)
    with _LOCK:
        data = load(p)
        d = data["days"][key]
        pick = next(x for x in d["picks"] if x["id"] == pick_id)
        stamp = now_bj(now).isoformat(timespec="seconds")
        rows = [{**x, "id": f"{pick_id}-S{i}", "state": "pending", "planned_at": stamp, "from_pick": pick_id} for i, x in enumerate(shorts)]
        d["posts"] += rows
        pick.update(split="done" if rows else "failed", made=[r["id"] for r in rows], split_error=error)
        save(p, data)
    return len(rows)


VALUE_PER_DAY = 2  # 10/12 晚 作者：价值线每天工作台做 2 篇长文，他自己 1 篇（或者发视频）


def value_articles(d: dict[str, Any]) -> list[dict[str, Any]]:
    """价值线今天的长文：从候选里做的、还在做或者等他存草稿、已经存了草稿的。"""
    return [x for x in d["posts"] if x.get("manual_publish") and x["state"] in ("pending", "approved", "drafted") and not x.get("swapped")]


def fill_articles(p: Path, key: str, want: int = VALUE_PER_DAY, now: datetime | None = None) -> int:
    """价值线不够 want 篇（设置里「长文每天几篇」）就从候选里按顺序补（工作台挑，不用他点），补了几篇。"""
    made = 0
    while True:
        with _LOCK:
            d = load(p)["days"].get(key) or {"posts": []}
            nxt = next((pk for pk in d.get("picks") or [] if not pk.get("choice")), None)
            if len(value_articles(d)) >= want or nxt is None:
                return made
        choose(p, key, nxt["id"], "article", now=now)
        made += 1


def value_action(p: Path, key: str, post_id: str, action: str, now: datetime | None = None) -> dict[str, Any]:
    """价值线卡片上的「拆成短帖」「不发」：这篇撤下（原话不丢），拆的交给后台拆；然后从候选里补一篇顶上。"""
    if action not in ("split", "skip"):
        raise DailyError("只能拆成短帖或不发")
    with _LOCK:
        data = load(p)
        d = data["days"].get(key) or {}
        post = _find(d, post_id)
        if post is None or not post.get("manual_publish") or post["state"] not in ("pending", "approved"):
            raise DailyError("这一篇不能再改了")
        post.update(state="rejected", swapped=True, decided_at=now_bj(now).isoformat(timespec="seconds"))
        pick = next((x for x in d.get("picks") or [] if x["id"] == post.get("from_pick")), None)
        if pick is not None:
            pick.update(choice=action, chosen_at=now_bj(now).isoformat(timespec="seconds"), **({"split": "running"} if action == "split" else {}))
        save(p, data)
    fill_articles(p, key, now=now)
    return {"post": post, "pick": pick}


def set_own(p: Path, key: str, **flags: bool) -> dict[str, Any]:
    """他自己那篇：今天自己发了长文 / 发了视频，勾一下。"""
    with _LOCK:
        data = load(p)
        d = day(data, key)
        d["own"] = {**(d.get("own") or {}), **{k: bool(v) for k, v in flags.items() if k in ("article", "video")}}
        save(p, data)
        return d["own"]


def mark_drafted(p: Path, key: str, post_id: str, url: str | None, now: datetime | None = None) -> dict[str, Any]:
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None:
            raise DailyError("找不到这一篇")
        post.update(state="drafted", drafted_at=now_bj(now).isoformat(timespec="seconds"), url=url or "https://x.com/compose/articles")
        data.pop("credits_out", None)  # 草稿存进去了 = X API 有余额了，短帖、Repost 不用等一小时
        save(p, data)
        return post


QUOTE_BLOCK = re.compile(r"403.*(quote|mention|author)|(quote|mention|author).*403", re.I | re.S)


def quote_text(post: dict[str, Any]) -> str:
    """引用帖发出去的正文：他的判断 + 空一行 + 原帖链接。"""
    return f"{post['text'].rstrip()}\n\n{post['quote_url']}"


def park_quotes(data: dict[str, Any]) -> bool:
    """X 不让工作台发引用：排着的引用帖改成「等他点去 X 发」，不再走 API。"""
    if not data.get("quotes_blocked"):
        return False
    changed = False
    for d in data["days"].values():
        for x in d["posts"]:
            if x.get("quote_url") and x["state"] == "approved":
                x["state"], changed = "ready_manual", True
    return changed


def quote_intent(post: dict[str, Any]) -> str:
    from urllib.parse import urlencode

    return "https://x.com/intent/post?" + urlencode({"text": post["text"].rstrip(), "url": post["quote_url"]})


def quote_handed(p: Path, key: str, post_id: str, now: datetime | None = None) -> dict[str, Any]:
    """他点了「去 X 发」：记一笔，下一张卡上来（发没发以 X 的数为准）。"""
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None or not post.get("quote_url") or post["state"] != "ready_manual":
            raise DailyError("这一条不用去 X 发")
        post.update(state="handed", handed_at=now_bj(now).isoformat(timespec="seconds"))
        save(p, data)
        return post


def retry_quotes(p: Path) -> None:
    with _LOCK:
        data = load(p)
        data.pop("quotes_blocked", None)
        for d in data["days"].values():
            for x in d["posts"]:
                if x.get("quote_url") and x["state"] == "ready_manual":
                    x["state"] = "approved"
        save(p, data)


def credits_wait(data: dict[str, Any], now: datetime) -> bool:
    """X API 余额用完了、离上次试还不到一小时：先不发（不然一分钟一条，排着的全记成「没发成」）。"""
    out = data.get("credits_out")
    return bool(out) and now - datetime.fromisoformat(out["at"]) < CREDITS_RETRY


def set_credits_out(p: Path, error: str, now: datetime | None = None) -> None:
    """存长文草稿也会撞上 402：记一笔，页面上同一句话告诉他去充值。"""
    with _LOCK:
        data = load(p)
        data["credits_out"] = {"at": now_bj(now).isoformat(timespec="seconds"), "error": error[:300]}
        save(p, data)


def resume(p: Path, now: datetime | None = None) -> None:
    """他点了「充值好了，接着发」：清掉余额用完的标记和今天的停发，下一分钟就发。"""
    with _LOCK:
        data = load(p)
        data.pop("credits_out", None)
        t = data["days"].get(day_key(now_bj(now)))
        if t:
            t["halted"] = None
        save(p, data)


def tick(p: Path, *, post_fn: Callable[[str], dict[str, Any]], record_fn: Callable[[dict[str, Any]], None],
         now: datetime | None = None, auto_send: dict[str, bool] | None = None, target: int = 0) -> dict[str, Any] | None:
    """一分钟一次：过天、该发就发一条。先在盘上记「正在发」，发完记结果；429 当天停（长文被限只停长文）；
    402 余额用完：这条放回去，停到他充值（每小时试一条）。target = 每天要发的短帖 + Repost，按它摊间隔。"""
    from ...x_post import XError

    now = now_bj(now)
    key = day_key(now)
    with _LOCK:
        data = load(p)
        changed = roll(data, key)
        d = data["days"].get(key)
        if d:
            changed = auto_decide(d, auto_send=auto_send, now=now) or changed
            changed = hold_qa(d) or changed
            changed = park_quotes(data) or changed
        post = due(d, now, target) if d and not credits_wait(data, now) else None
        if post is not None:
            post["state"], post["sending_at"] = "sending", now.isoformat(timespec="seconds")
            changed = True
        if changed:
            save(p, data)
    if post is None:
        return None
    try:
        if post.get("quote_url"):
            # 10/12：X API 连 quote_tweet_id 也拦（只许引用 @ 了你的帖子）。原帖链接贴在正文最后，当普通帖发，X 显示成卡片
            result = post_fn(quote_text(post), long=True, post={**post, "format": "post"})
        elif post.get("long"):
            result = post_fn(post["text"], long=True, post=post)
        else:
            result = post_fn(post["text"])
        error, quota = None, False
    except XError as exc:
        result, error, quota = None, str(exc), "429" in str(exc)
    with _LOCK:
        data = load(p)
        d = data["days"][key]
        row = next(x for x in d["posts"] if x["id"] == post["id"])
        if result is None and row.get("quote_url") and QUOTE_BLOCK.search(error or ""):
            data["quotes_blocked"] = {"at": now.isoformat(timespec="seconds"), "reason": (error or "")[:200]}
            row.update(state="approved", error=None)
            park_quotes(data)
        elif result is not None:
            row.update(state="sent", sent_at=now.isoformat(timespec="seconds"), url=result.get("url"), error=None)
            data.pop("credits_out", None)
        elif CREDITS_OUT in (error or ""):  # 不是这条的问题：放回去排第一，充值了接着发
            row.update(state="approved", error=None)
            data["credits_out"] = {"at": now.isoformat(timespec="seconds"), "error": (error or "")[:300]}
        else:
            row.update(state="failed", error=error)
            if quota and is_article(row):  # X 文章接口限额：今天不再发长文（别一遍遍建草稿），长帖照发
                d["articles_paused"] = error
            elif quota:
                d["halted"] = error
        save(p, data)
    if result is not None:
        record_fn(row)
    return row


def manual(p: Path, key: str, post_id: str) -> dict[str, Any]:
    """没发成 / 不确定的那条，他复制去 X 自己发了。"""
    with _LOCK:
        data = load(p)
        post = next((x for x in data["days"].get(key, {}).get("posts", []) if x["id"] == post_id), None)
        if post is None or post["state"] not in ("failed", "unsure", "approved"):
            raise DailyError("这一条不用手动记")
        post.update(state="sent", sent_at=now_bj().isoformat(timespec="seconds"), how="manual")
        save(p, data)
        return post


def daily_target(counts: dict[str, Any] | None) -> int:
    """每天自动发几条：短帖 + Repost（长文他自己发，不算）。"""
    c = counts or {}
    return int(c.get("own_short") or 0) + int(c.get("hot") or 0)


def view(p: Path, now: datetime | None = None, counts: dict[str, Any] | None = None,
         auto_send: dict[str, bool] | None = None, flow_now: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now_bj(now)
    today, tomorrow = day_key(now), day_key(now + timedelta(days=1))
    with _LOCK:
        data = load(p)
        changed = roll(data, today)
        for key, d in data["days"].items():
            if key >= today:
                changed = auto_decide(d, auto_send=auto_send, now=now) or changed
                changed = any([hide_failed(x) for x in d["posts"]]) or changed
            changed = hold_qa(d) or changed
        changed = park_quotes(data) or changed
        if changed:
            save(p, data)
    for d in data["days"].values():
        for post in d["posts"]:
            post.setdefault("auto", False)
            post.setdefault("auto_reason", None)
            if post.get("quote_url") and post.get("text"):
                post["intent_url"] = quote_intent(post)
            if flow_now is not None:
                write_flow.attach(post, flow_now)
                if post.get("trk"):  # 页面上显示的预算上限：这一篇自己改过的，否则是设置里的默认
                    post["trk"]["pct_effective"] = post["trk"].get("max_pct") or flow_now.get("pct") or 20
    t = data["days"].get(today) or {"posts": [], "planned_at": None, "halted": None}
    nxt = data["days"].get(tomorrow) or {"posts": [], "planned_at": None, "halted": None}
    later = [day_key(now + timedelta(days=i)) for i in range(2, LONG_AHEAD + 1)]
    ahead = [{"day": k, **data["days"][k]} for k in later if (data["days"].get(k) or {}).get("posts")]
    count = lambda d, s: sum(1 for x in d["posts"] if x["state"] == s)  # noqa: E731
    return {"today": {"day": today, **t, "next_at": next_at(t, now, daily_target(counts)), "sent": count(t, "sent"), "queued": count(t, "approved"),
                      "pending": count(t, "pending"),
                      "visible_long": sum(1 for x in t["posts"] if x.get("long") and not x.get("quote_url") and not x.get("hidden") and not x.get("swapped") and x["state"] not in ("moved", "expired")),
                      "hidden_long": sum(1 for x in t["posts"] if x.get("hidden")),
                      "merge": {"count": t.get("merge_count") or 0, "max": MERGE_PER_DAY,
                                "waiting": sum(1 for x in t["posts"] if x.get("hidden") and not x.get("merged_into") and not x.get("merged_from")
                                               and (x.get("merge_tries") or 0) < 2 and x["state"] == "pending")},
                      "auto_sent": sum(bool(p.get("auto")) and p["state"] == "sent" and
                                       str(p.get("sent_at") or "").startswith(today)
                                       for d in data["days"].values() for p in d["posts"]),
                      "auto_dropped": sum(bool(p.get("auto")) and p["state"] == "rejected" and
                                          str(p.get("decided_at") or "").startswith(today)
                                          for d in data["days"].values() for p in d["posts"])},
            "quotes_mode": "manual" if data.get("quotes_blocked") else "api", "quotes_blocked": data.get("quotes_blocked"),
            "credits_out": data.get("credits_out"),
            "tomorrow": {"day": tomorrow, **nxt}, "ahead": ahead, "per_day": int((counts or {}).get("own_short", PER_DAY)),
            "per_day_long": sum(split_counts(counts)) if counts else PER_DAY_LONG, "counts": counts or {},
            "long_ahead": LONG_AHEAD,
            "window": f"{START.strftime('%H:%M')}–{START.hour + HOURS:02d}:{START.minute:02d}", "plan_at": PLAN_AT.strftime("%H:%M")}


def plan_due(p: Path, now: datetime | None = None, *, own_short: int = PER_DAY) -> str | None:
    """每晚 21:00 以后，第二天的短帖或长的还没排：该排了。返回要排的那一天。（长的平时也由 long_days_due 提前补）
    own_short 默认 10；用户设为 0 时不排原话短帖，只看长的。"""
    now = now_bj(now)
    if now.time() < PLAN_AT:
        return None
    key = day_key(now + timedelta(days=1))
    with _LOCK:
        d = load(p)["days"].get(key) or {"posts": []}
        return None if (has_short(d) or own_short <= 0) and d.get("long_planned_at") else key


def topup_due(p: Path, target: list[int], now: datetime | None = None) -> list[str]:
    """今天起 LONG_AHEAD 天里，排过但数量和现在的设置不一样的日子：要按新数量补齐。"""
    now = now_bj(now)
    keys = [day_key(now + timedelta(days=i)) for i in range(0, LONG_AHEAD + 1)]
    with _LOCK:
        days = load(p)["days"]
    return [k for k in keys if (days.get(k) or {}).get("long_planned_at") and (days.get(k) or {}).get("long_target") != target]


def long_days_due(p: Path, now: datetime | None = None) -> list[str]:
    """明天起 LONG_AHEAD 天里，还没排过长帖的日子（排过但没东西可排的也算排过，不会每分钟重试）。"""
    now = now_bj(now)
    keys = [day_key(now + timedelta(days=i)) for i in range(1, LONG_AHEAD + 1)]
    with _LOCK:
        days = load(p)["days"]
    return [k for k in keys if not (days.get(k) or {}).get("long_planned_at")]


# -- 长文：改写、配图（x_long.py 干活，这里只管挑哪篇、记状态）---------------------------------------


def prep_next(p: Path, now: datetime | None = None) -> tuple[str, dict[str, Any]] | None:
    """下一篇该做的长文：今天的先、明天的后；还没做的，或者做到一半服务重启了的（running）。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    for key in (day_key(now), day_key(now + timedelta(days=1))):
        for x in (days.get(key) or {}).get("posts", []):
            if x.get("long") and x["state"] in ("pending", "approved") and not x.get("swapped") \
                    and x.get("format") != "post" and x.get("prep") in (None, "running"):
                return key, x
    return None


def cover_next(p: Path, now: datetime | None = None) -> tuple[str, dict[str, Any]] | None:
    """今天、明天做好了的长文（含合集），还没出封面的：出一张 作者 形象 + 红色 + 点击率标题的封面（10/10 作者）。
    做到一半服务重启了的（running）接着做；没出成的等他点「重做封面」。发出去的、换掉的不管。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    for key in (day_key(now), day_key(now + timedelta(days=1))):
        for x in (days.get(key) or {}).get("posts", []):
            if x.get("long") and x.get("format") != "post" and x["state"] in ("pending", "approved") \
                    and x.get("prep") == "ready" and not x.get("swapped") and x.get("cover") in (None, "running"):
                return key, x
    return None


def qa_next(p: Path, now: datetime | None = None, qa_version: int = 4,
            rules_hash: str | None = None) -> tuple[str, dict[str, Any]] | None:
    """今天、明天未发的长文长帖（需 prep ready）和 pending 短帖，没过 QA 或旧版本的再过一遍。
    做到一半服务重启了的（running）接着做；已还原或失败的不自动重试。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    for key in (day_key(now), day_key(now + timedelta(days=1))):
        for x in (days.get(key) or {}).get("posts", []):
            if not x.get("long") and not x.get("quote_url"):
                continue  # 10/12 作者：短帖不要 QA，直接发
            eligible = (x["state"] in ("pending", "approved") and x.get("prep") == "ready") if x.get("long") else x["state"] == "pending"
            if eligible and not x.get("swapped") \
                    and (x.get("qa") in (None, "running")
                         or (x.get("qa") in ("ready", "skipped") and (x.get("qa_v") or 1) < qa_version)
                         or (x.get("qa") == "ready" and rules_hash is not None and x.get("qa_rules")
                             and x["qa_rules"] != rules_hash)):
                return key, x
    return None


def apply_qa(p: Path, key: str, post_id: str, *, seen: str, result: dict[str, Any] | None = None, error: str | None = None,
             version: int = 4, rules_hash: str | None = None, auto_send: dict[str, bool] | None = None,
             now: datetime | None = None, complete_on_fail: str = "swap-if-ending-unfinished", change_cap: int = 20) -> dict[str, Any]:
    """QA 做完写回未发的内容；他改了字就跳过，已勾选的改过或不完整则退回待确认。
    complete_on_fail 是 park-writing 清单里「完整度」这一步不过怎么办（10/12 他定的：结尾没写完的自动换下一篇，其他只标红）。"""
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None:
            raise DailyError("找不到这一条")
        if post["state"] not in ("pending", "approved"):
            return post
        current = post["trk"]["base"] if post.get("trk") else post["text"]
        if current != seen:
            post.update(qa="skipped", qa_v=version, qa_rules=rules_hash, qa_error="QA 做的时候你改了或这条已不待发，就没动")
        elif error:
            post.update(qa="failed", qa_error=error[:300])
            if post.get("auto") and post["state"] == "approved":
                post.update(state="pending", decided_at=None)
        elif post.get("trk"):  # 带修改清单的：QA 的改动并进同一份清单一起留痕，不直接改正文
            complete = result.get("complete", True) is not False
            write_patch.merge_qa(post["trk"], post["trk"]["base"], result.get("changes", []), change_cap)
            post["text"] = trk_render_text(post)
            post.update(qa="ready", qa_error=None, qa_v=version, qa_rules=rules_hash, qa_at=now_bj(now).isoformat(timespec="seconds"),
                        qa_changes=[], qa_dropped=result["dropped"], qa_before=None, qa_complete=complete,
                        qa_issues=result.get("issues", []), qa_value_ok=result.get("value_ok"), qa_value=result.get("value", {}),
                        qa_value_issues=result.get("value_issues", []))
            if result.get("intro"):
                post["intro"] = result["intro"]
            auto_decide({"posts": [post]}, auto_send=auto_send, now=now)
            hide_failed(post)
            _swap_unfinished(data["days"].get(key), post, complete_on_fail, now)
        else:  # 再过一遍的：原文还是第一次 QA 之前他自己的那版，改了什么接在后面
            was_approved = post["state"] == "approved"
            changed = result["text"] != seen
            complete = result.get("complete", True) is not False
            for field in ("qa_complete_override", "qa_value_override", "qa_complete_held", "qa_value_held"):
                post.pop(field, None)
            if post.get("long"):
                post.update(qa_value_ok=result.get("value_ok"), qa_value=result.get("value", {}),
                            qa_value_issues=result.get("value_issues", []))
            if post["state"] == "approved" and (changed or not complete):
                post.update(state="pending", decided_at=None, qa_note=("QA 觉得还不完整，你看一眼再决定" if not complete
                                                                     else "QA 改过，你再看一眼再勾"))
            post.update(qa="ready", qa_error=None, qa_v=version, qa_rules=rules_hash, qa_at=now_bj(now).isoformat(timespec="seconds"), qa_changes=[*(post.get("qa_changes") or []), *result["changes"]],
                        qa_complete=complete, qa_issues=result.get("issues", []),
                        qa_dropped=result["dropped"], qa_before=post.get("qa_before") or (seen if changed else None), text=result["text"])
            if was_approved and post.get("qa_value_ok") is False:
                post.update(state="pending", decided_at=None, qa_value_held=True)
            if result.get("intro"):
                post["intro"] = result["intro"]
            auto_decide({"posts": [post]}, auto_send=auto_send, now=now)
            hide_failed(post)
            _swap_unfinished(data["days"].get(key), post, complete_on_fail, now)
        save(p, data)
        return post


def _swap_unfinished(d: dict[str, Any] | None, post: dict[str, Any], mode: str, now: datetime | None) -> bool:
    """价值线上的文章完整度不过：结尾没写完的（或模式是 swap 时任何一项不过的）撤下，候选里的下一篇会顶上。"""
    if mode not in ("swap", "swap-if-ending-unfinished") or not post.get("manual_publish") or post["state"] != "pending" \
            or post.get("qa_complete") is not False or post.get("swapped"):
        return False
    issues = post.get("qa_issues") or []
    ending = unfinished_tail(post["text"]) or any(("末句" in i or "结尾" in i) and ("未展开" in i or "没讲完" in i or "不完整" in i or "收" in i) for i in issues)
    if mode == "swap-if-ending-unfinished" and not ending:
        return False
    stamp = now_bj(now).isoformat(timespec="seconds")
    post.update(state="rejected", swapped=True, decided_at=stamp, swap_reason="完整度没过（结尾没写完），工作台换了下一篇" if ending else "完整度没过，工作台换了下一篇")
    pick = next((x for x in (d or {}).get("picks") or [] if x["id"] == post.get("from_pick")), None)
    if pick is not None:
        pick.update(choice="skip", chosen_at=stamp, auto=True)
    return True


def trk_render_text(post: dict[str, Any]) -> str:
    """修改清单 + 原文 + 拆开的 summary 和配图 = 现在的文字（只含他接受的修改）。"""
    trk = post["trk"]
    parts = {"title": trk["parts"]["title"], "summary": trk["parts"]["summary"], "images": [tuple(x) for x in trk["parts"]["images"]]}
    return write_steps.join_article(parts, write_patch.render(trk["base"], trk["changes"]))


def trk_update(p: Path, key: str, post_id: str, fn: Callable[[dict[str, Any]], None], label: str | None = None) -> dict[str, Any]:
    """他在批注视图上处理修改（接受、改一改、不要、全部接受…）：改清单，正文跟着重新算。"""
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None or not post.get("trk"):
            raise DailyError("这一篇没有修改清单")
        if post["state"] not in ("pending", "approved"):
            raise DailyError("这一篇已经发了或不发了，改不了")
        trk = post["trk"]
        try:
            write_patch.mutate(trk, fn, label)
        except write_patch.PatchError as exc:
            raise DailyError(str(exc)) from exc
        text = trk_render_text(post)
        if text != post["text"]:
            if (trk.get("scores") or {}).get("after"):
                trk["scores"]["stale"] = True  # 改后的分是上一版文字打的
            post["text"] = text
            post["trk_saved_at"] = now_bj().isoformat(timespec="seconds")  # 卡片上写「你几点存的」，他才知道改动生效了（10/13）
            if post["state"] == "approved":
                post.update(state="pending", decided_at=None, qa_note="你改了修改清单，再看一眼再勾")
        save(p, data)
        return post


def rerun_qa(p: Path, key: str, post_id: str) -> dict[str, Any]:
    """检查用新规则重跑：清掉上次的检查结果让它重新排队，正文不动。已发的、在发的不能重跑。"""
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None:
            raise DailyError("找不到这一条")
        if post["state"] not in ("pending", "approved") or post.get("prep") not in (None, "ready"):
            raise DailyError("这一条现在不能重跑检查")
        post.update(qa=None, qa_error=None)
        save(p, data)
        return post


def revert_qa(p: Path, key: str, post_id: str) -> dict[str, Any]:
    """「还原原文」：回到 QA 之前他自己的那一版。"""
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None:
            raise DailyError("找不到这一条")
        if post["state"] not in ("pending", "approved", "rejected"):
            raise DailyError("这一条已经在发或发过了，改不了")
        if not post.get("qa_before"):
            raise DailyError("这一条 QA 没改过字")
        if post.get("auto") and post["state"] == "approved":
            post.update(state="pending", decided_at=None)
        post.update(text=post["qa_before"], qa="reverted", qa_before=None, intro=None, auto=False, auto_reason=None)
        for field in ("qa_complete", "qa_issues", "qa_note", "qa_complete_override", "qa_complete_held"):
            post.pop(field, None)
        save(p, data)
        return post


def summary_next(p: Path, now: datetime | None = None) -> tuple[str, dict[str, Any]] | None:
    """10/9 之前就做好、还没勾的长文：开头补一段 summary（勾过的不动，那是他看过的版本）。"""
    now = now_bj(now)
    with _LOCK:
        days = load(p)["days"]
    for key in (day_key(now), day_key(now + timedelta(days=1))):
        for x in (days.get(key) or {}).get("posts", []):
            if x.get("long") and x.get("format") != "post" and not x.get("compiled") and x["state"] == "pending" \
                    and x.get("prep") == "ready" and not x.get("swapped") and "summary" not in x:
                return key, x
    return None


def set_post(p: Path, key: str, post_id: str, **fields: Any) -> dict[str, Any]:
    with _LOCK:
        data = load(p)
        post = _find(data["days"].get(key), post_id)
        if post is None:
            raise DailyError("找不到这一条")
        post.update(fields)
        save(p, data)
        return post


# -- 热点短帖：X 运营从「持续在涨」里挑，用他的观点写引用帖草稿，他分批勾（10/9 作者）----------------------
# 作者 要「什么火我就说什么」，每天 100–200 条。X 的自动化规则禁止程序自己发热门话题，所以这里只写草稿：
# 他打了勾才发。不写引战、留问题让人回答的那种（X 新计划算互动诱导）；观点只能来自他自己说过的（世界观文件）。

HOT_BATCH = 20                      # 10/13 Repost 每天 100：一批 20、半小时一批（以前 10 条 2 小时，一天最多 70）
HOT_EVERY = timedelta(minutes=30)
HOT_START, HOT_END = dtime(0, 0), dtime(23, 30)  # 10/13 起全天发：Repost 也全天写（以前 8:00–21:30）
HOT_MIN_CHARS = 30    # 10/12 作者 要每天 100 条帖子：引用改回短的（一到三句判断），10/9 那版长帖一批常常一条都写不出来
HOT_BAIT = re.compile(r"你怎么看|你们怎么看|评论区|留言|告诉我你|你觉得呢|你们觉得|欢迎讨论|转发|点赞|关注我|[？?]\s*\Z")


def hot_due(p: Path, cap: int, now: datetime | None = None) -> int:
    """现在该写几条热点草稿：在 8:00–21:30 之间、离上一批够半小时、今天写的还没到上限。返回这一批写几条，0 = 不写。"""
    now = now_bj(now)
    if cap <= 0 or not (HOT_START <= now.time() < HOT_END):
        return 0
    with _LOCK:
        d = load(p)["days"].get(day_key(now)) or {"posts": []}
    last = d.get("hot_at")
    if last and now - datetime.fromisoformat(last) < HOT_EVERY:
        return 0
    made = sum(1 for x in d["posts"] if x.get("hot"))
    return max(0, min(HOT_BATCH, cap - made))


def hot_prompt(items: list[dict[str, Any]], n: int, *, style: str, beliefs: str, error: str | None = None) -> str:
    def mine(x):  # 10/12 晚 作者：repost = 别人的帖子 + 我的原话或暴论；原话是代码从原始输出里找的、和这条最贴的几句
        lines = x.get("park_lines") or []
        return ("\n他说过的相关原话：\n" + "\n".join(f"- {t}" for t in lines)) if lines else ""
    listed = "\n\n".join(f"### 帖子 {i}（{x.get('author') or ''}，近 10 小时 +{x.get('gained', 0)} 阅读）\n{(x.get('text') or x.get('title') or '')[:600]}{mine(x)}"
                         for i, x in enumerate(items))
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    return f"""你是 作者 的 X 运营。下面是 X 上过去 10 小时一直有人看的帖子。挑出 作者 能说出判断的，写 {n} 条引用帖（quote post）。尽量写满 {n} 条。
过了 QA 就自动发，原帖链接会贴在后面显示成卡片，稿子里不用贴链接、不用复述原帖。

## 他的写作风格
{style.strip()[:3000]}

## 他的世界观和原则（他的观点只能来自这里）
{beliefs[:6000] or '（没有）'}

## 规矩（不能破）
- 和 AI、工具、做产品、做内容、创业赚钱有关、他按自己的世界观能说出一个判断的，都可以写；八卦、社会新闻、政治、擦边的一律不写。
  （10/12：以前只挑「和他原则真有关系的」，一批 40 条一条都没写出来；他要每天几十条。）
- 短的：一到三句，60–200 字。第一句就是他的判断，说满；后面最多一两句用他世界观里的道理撑住。
- 有「他说过的相关原话」的，优先直接用原话（只删口语、调语序，不换词）；没有、或者原话不贴，就写一句反常识暴论。
- 只围绕一个判断展开，用他的话、他的原则；不复述原帖。
- 不写引战、不留问题让人回答（不写「你怎么看」「评论区」「欢迎讨论」，不以问号结尾），不写「关注我」「转发」。
- 不编他的经历（不写「我试了」「我用了」「我客户」），不编数字（数字只能来自原帖）。

{listed}

## 输出
每条放在单独一行的 <<<POST source=帖子编号>>> 和单独一行的 <<<END>>> 之间，前后不要有其他说明。{retry}"""


def build_hot(items: list[dict[str, Any]], *, n: int, style: str, beliefs: str, write_fn: Callable[[str], str],
              check_fn: Callable[[str, dict[str, Any]], str | None], attempts: int = 2,
              report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """模型挑、写，代码核对：编号对、够长（长帖）、不超长、最后一句不引战、不编经历和数字（check_fn = x_suggest.check）。没过的那条扔掉。"""
    if not items or n <= 0:
        return []
    error = None
    for _ in range(attempts):
        found = POST.findall(str(write_fn(hot_prompt(items, n, style=style, beliefs=beliefs, error=error)) or ""))
        if not found:
            error = "没有按 <<<POST source=编号>>> 格式返回"
            continue
        out, used, drops = [], set(), []
        for idx, text in found:
            i, text = int(idx), text.strip()
            if not (0 <= i < len(items)) or i in used or len(text) < HOT_MIN_CHARS or weighted_length(text) > MAX_LONG \
                    or HOT_BAIT.search(text):
                drops.append("编号不对 / 太短 / 太长 / 引战结尾")
                continue
            it = items[i]
            why = check_fn(text, {"title": it.get("title"), "text": f"{it.get('text') or ''}\n" + "\n".join(it.get("park_lines") or [])})
            if why:
                drops.append(why)
                continue
            used.add(i)
            out.append({"text": text, "hot": True, "quote_url": it["url"],
                        "source_kind": f"热点 · {it.get('author') or ''}",
                        "source_title": (it.get("title") or it.get("text") or "")[:60]})
            if len(out) >= n:
                break
        if report is not None:
            report.update(found=len(found), drops=drops)
        return out  # 一条都没挑出来也算这一批写过了：都和他无关
    raise DailyError(f"热点草稿没写出来：{error}")


def add_hot(p: Path, key: str, drafts: list[dict[str, Any]], seen: list[str], now: datetime | None = None,
            note: str | None = None) -> dict[str, Any]:
    """这一批草稿放进今天，排在短帖那一格；看过的原帖记下来，下一批不再看。"""
    with _LOCK:
        data = load(p)
        d = day(data, key)
        stamp = now_bj(now).isoformat(timespec="seconds")
        start = sum(1 for x in d["posts"] if x.get("hot"))
        d["posts"] += [{**x, "id": f"{key}-H{start + i}", "state": "pending", "planned_at": stamp} for i, x in enumerate(drafts)]
        d["hot_seen"] = list(dict.fromkeys((d.get("hot_seen") or []) + seen))
        d["hot_at"] = stamp
        d["hot_note"] = note  # 一条都没写的时候说清楚为什么（页面上「引用」那一格显示）
        save(p, data)
        return d


def hot_seen(p: Path, key: str) -> set[str]:
    with _LOCK:
        return set((load(p)["days"].get(key) or {}).get("hot_seen") or [])


# -- 10/9 作者：只留长帖和长文，每天 5 + 5，现在就生效；已经排好的也补齐 ---------------------------------------
# 「我的 principles 和 predictions 也可以用好。比如把 10 个 principles 串在一起，写成一篇关于做自媒体的 10 条心得，
# 发成一篇长文或长帖。」笔记不够整篇搬的时候，长文用主题合集补：他的短句按主题串成连续段落，只配图，不改写。
# 不管哪种，都要他勾了才发。

ACTIVE = ("pending", "approved", "sending", "sent", "unsure")


def as_compilation(post: dict[str, Any]) -> dict[str, Any]:
    """一条主题长帖改成一篇合集长文：标题 + 连续段落（他的原话，一条一段，不加编号），后面只配图。"""
    title, _, body = post["text"].partition("\n\n")
    lines = [b.strip() for b in body.split("\n\n") if b.strip()]
    text = f"# {title.strip()}\n\n" + "\n\n".join(lines)
    return {**post, "text": text, "format": "article", "compiled": True, "prep": None, "source_kind": "我的短句合集"}


def topup(p: Path, key: str, *, sources: list[dict[str, Any]], avoid: set[str], read_full: Callable[[str], str],
          write_fn: Callable[[str], str], n_article: int, n_post: int, now: datetime | None = None) -> dict[str, Any]:
    """这一天的长文、长帖按现在的数量补齐（已经有的、他勾过的都不动，打叉的不算数也不补）。
    长文：先整篇搬笔记，笔记不够用主题合集补；长帖：短句按主题合并。补过记一笔目标，同样的目标不再补。"""
    with _LOCK:
        data = load(p)
        d = day(data, key)
        if d.get("long_target") == [n_article, n_post]:
            return d
        live = [x for x in d["posts"] if x.get("long") and not x.get("swapped") and x["state"] in ACTIVE]
        need_a = max(0, n_article - sum(1 for x in live if x.get("format") != "post"))
        need_p = max(0, n_post - sum(1 for x in live if x.get("format") == "post" and not x.get("hot")))
        avoid = avoid | recent_sources(data, key)
    new: list[dict[str, Any]] = []
    error = None
    if need_a:
        new += long_candidates(sources, avoid=avoid, read_full=read_full, n=need_a)
    used = avoid | {x.get("source_id") for x in new}
    want_posts, want_comp = need_p, need_a - len(new)
    if want_posts + want_comp:
        try:
            built = build_long_posts(post_items(sources, avoid=used), k=want_posts + want_comp, write_fn=write_fn)
        except DailyError as exc:
            built, error = [], exc
        new += [as_compilation(x) for x in built[:want_comp]] + built[want_comp:]
    with _LOCK:
        data = load(p)
        d = day(data, key)
        stamp = now_bj(now).isoformat(timespec="seconds")
        ids = {x["id"] for x in d["posts"]}
        rows = []
        for x in new:
            tag = "P" if x.get("format") == "post" else "L"
            i = 0
            while f"{key}-{tag}{i}" in ids:
                i += 1
            ids.add(f"{key}-{tag}{i}")
            rows.append({**x, "id": f"{key}-{tag}{i}", "state": "pending", "planned_at": stamp})
        d["posts"] = interleave(d["posts"], rows)
        d["long_target"] = [n_article, n_post]
        d.setdefault("long_planned_at", stamp)
        save(p, data)
    if error is not None and not new:
        raise error
    return d


def set_target(p: Path, key: str, target: list[int]) -> None:
    with _LOCK:
        data = load(p)
        day(data, key)["long_target"] = target
        save(p, data)


def cancel_shorts(p: Path, today: str, note: str = "10/9 起只发长帖和长文，短帖不发了") -> int:
    """今天和以后还没发的短帖（他原话的短帖、热点短帖）都作废。返回作废了几条。"""
    n = 0
    with _LOCK:
        data = load(p)
        for k, d in data["days"].items():
            if k < today:
                continue
            for x in d["posts"]:
                if not x.get("long") and x["state"] in ("pending", "approved"):
                    x.update(state="expired", note=note)
                    n += 1
        if n:
            save(p, data)
    return n
