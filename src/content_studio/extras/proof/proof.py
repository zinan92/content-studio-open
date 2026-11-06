"""拍之前的证据（10/5 作者）：骨架里每个论点配真东西，录的时候能指着讲，视频、文章用的是同一批。

作者：以前很多图是直接生成的，没有真实感，非常减分。证据要真——新闻、数据都算，拍之前就找。
骨架 28 条证据里 14 条是「要补」，以前没人补，最后只能拿 AI 图凑。

证据分两种：
  - 能找的：新闻报道、公开数据、名人原推、公开的真实案例。claude -p 只读搜网页给候选，这里逐条核对：
    网页真打得开、引的那句话 / 那个数真在页面上，再截页面上那一段（高亮）；推文走 X 公开嵌入接口核对、截官方卡片。
    对不上、打不开、要付费的一律扔掉。一篇里同一个人 / 同一家媒体只用一次（不要每篇都是 Naval）。
  - 只有他能拿的：他的后台、他的录屏、他的聊天记录。不替他补、绝不编，写成一行具体的待办；
    他截好了传上来（OCR 查隐私），也进同一个池子。
都只是候选：他在骨架页一张张点「要」才算数。后面视频动效（park-video-v2 的截图卡）和文章配图只用他点过「要」的。

10/9 证据单（作者 在流程板上拍的）：两篇讲工作台的文章发出去才发现，插图本该是工作台截图。所以每个论点先定
「用什么证明」，按顺序问，第一个答「是」就停：① 讲的是他自己的东西 → 他的截图（工作台的页面也是他自己截，
这里只写待办）；② 外面有能逐字核对的原话、数字（引别人的文章也算这一种）→ 外面的证据；③ 都没有、是讲概念
打比方 → 才给画插图。整篇讲他自己的产品、做法时标「截图优先」。他能改每条的定法，也能定「这条不要证据」。
定了「截图」又没传的，X、公众号先不让发（卡发不卡拍，见 missing_shots）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse

from .evidence import EvidenceError, lookup_tweet, ocr, private_hit, shoot_tweet, verify_tweet, TWEET_ID

FOLDER = "proof"
STATE = "proof.json"
PER_POINT = 2          # 每个论点最多几条候选
MIN_QUOTE = 8          # 引的原话（去掉标点空格）至少这么长，太短的「对上了」不算数
MIN_PAGE = 400         # 页面正文少于这么多字：没打开、要登录或者要付费
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
KINDS = {"news": "新闻", "data": "数据", "tweet": "原推", "post": "公开帖子", "mine": "你的截图"}
USES = {"mine": "你的截图", "outside": "外面的证据", "illustration": "插图", "none": "不要证据"}
PROOF_COMMAND = (
    "claude -p --model opus --output-format text "
    '--allowedTools "WebSearch WebFetch" '
    '--disallowedTools "Bash Edit Write NotebookEdit Read Glob"'
)

LLM = Callable[[str], str]
# 打开网页、核对原话、截那一段：(url, quote, 存到哪) -> {"title", "site", "date"}；对不上返回 None
Page = Callable[[str, str, Path], dict[str, Any] | None]
Lookup = Callable[[str], dict[str, Any] | None]
Shot = Callable[[str, Path], None]


# -- 骨架里的论点 -------------------------------------------------------------------------

POINT = re.compile(r"^###\s*论点\s*([A-Za-z0-9一二三四五六七八九十]+)\s*[：:]\s*(.+?)\s*$")


def points(skeleton: str) -> list[dict[str, str]]:
    """「## 中间骨架」下面每个「### 论点 X：…」和它的「证据：…」。"""
    m = re.search(r"^##\s*中间骨架\s*\n(.+?)(?=^##\s|\Z)", skeleton, flags=re.MULTILINE | re.DOTALL)
    out: list[dict[str, str]] = []
    for line in (m.group(1) if m else "").splitlines():
        hit = POINT.match(line.strip())
        if hit:
            out.append({"key": hit.group(1), "title": hit.group(2), "line": ""})
        elif out and re.match(r"^[-*]?\s*证据\s*[：:]", line.strip()):
            out[-1]["line"] = re.sub(r"^[-*]?\s*证据\s*[：:]\s*", "", line.strip())
    return out


def missing(line: str) -> bool:
    """骨架里写着「要补」的证据。"""
    return bool(re.match(r"^\s*(要补|待补|需要补)", line or ""))


def signature(skeleton: str) -> str:
    """论点变了，以前找的对不上：只看论点和证据那几行，开头候选改了不算。"""
    pts = points(skeleton)
    return hashlib.sha1(json.dumps(pts, ensure_ascii=False).encode()).hexdigest()[:12]


# -- 让模型找 -----------------------------------------------------------------------------

def build_prompt(title: str, skeleton: str, pts: list[dict[str, str]], *, avoid: list[str] | None = None) -> str:
    listing = "\n".join(f"- 论点 {p['key']}：{p['title']}\n  骨架里的证据：{p['line'] or '（没写）'}" for p in pts)
    skip = f"\n这些来源已经用过了，别再给：{'、'.join(avoid)}" if avoid else ""
    return f"""你在帮 作者 给一条还没拍的口播视频找证据。他对着骨架讲，讲到某个论点时，画面上要放一张真东西证明他说的是真的。
以前用的是 AI 画的图，观众一眼看出是假的，非常减分。所以这里只要**真实存在、能查到出处**的东西。

每个论点分两种情况：

一、外面能找到的证据：新闻报道、公开数据（统计局、财报、研究报告、平台官方数字）、名人原推、公开的真实案例。
   用 WebSearch / WebFetch 去找，**每条都必须是你在网页上亲眼看到的**：
   - url：原网页（推文用 x.com/<账号>/status/<数字>）。
   - quote：页面上的一句原话或一个数，**逐字照抄**（中文不少于 10 个字，英文不少于 6 个词）。程序会打开网页逐字核对，对不上就扔。
   - 优先新闻和数据，其次真实案例，名人推文排最后；观众是中文观众，同样分量的中文来源优先。一个论点最多 {PER_POINT} 条，宁缺毋滥。
   - 同一个人、同一家媒体整篇只用一次。要付费、要登录才能看的不要。找不到就不给，**绝不编**。

二、只有 作者自己能拿的证据：他的工作台和产品页面、后台数据、收入、他的工作流录屏、他和客户的聊天。你找不到，也不许替他编。
   写成一行他照着就能做的待办（哪个软件哪一页哪个页签、截哪一块、圈出什么），放在 mine 里。骨架里已经写了「要补」的，照它改得更具体。
   工作台的页面也是他自己截，你只写待办。

三、先给每个论点定「用什么证明」（use），按顺序问，第一个答「是」就停：
   ① 这个论点讲的是 作者自己的东西（他的工作台、产品、后台、收入、录屏、聊天、他自己的做法）？→ "mine"，mine 里必须写待办。
   ② 外面有能逐字核对的原话或数字（新闻、公开数据、原推、别人文章里的一段）？→ "outside"
   ③ 都没有，这个论点是在讲概念、打比方 → "illustration"（只有这种论点后面才会画插图）
   use 是 "mine" 时，外面的证据只当补充，找到了也可以给。
   整篇主要讲 作者自己的产品、工作台、做法时，own 填 true：能用他截图证明的论点一律 "mine"。
{skip}
选题：{title}

论点：
{listing}

骨架全文：
<skeleton>
{skeleton}
</skeleton>

只回一个 JSON 代码块，不要别的话：
```json
{{"own": false, "points": [{{"key": "A", "use": "mine|outside|illustration", "why": "一句话：为什么这样定",
  "found": [{{"kind": "news|data|tweet|post", "url": "https://…", "source": "谁说的 / 哪家媒体或机构", "date": "发布日期 YYYY-MM-DD，页面上没写就空", "quote": "页面原话，逐字", "claim": "它证明论点里的哪句话", "caption": "画面上那一行字：一句话说这是什么，带上来源"}}],
  "mine": "只有 作者 能拿的那张：去哪截什么；不需要就空字符串"}}]}}
```
"""


def _answer(output: str) -> dict[str, Any]:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", output, re.S) or re.search(r"(\{.*\})", output, re.S)
    if not m:
        raise EvidenceError("模型没按格式回 JSON")
    try:
        data = json.loads(m.group(1))
    except ValueError as exc:
        raise EvidenceError("模型回的 JSON 坏了") from exc
    return data if isinstance(data, dict) else {}


def parse(output: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in _answer(output).get("points") or []:
        if isinstance(p, dict) and p.get("key"):
            use = str(p.get("use") or "").strip()
            out[str(p["key"])] = {"found": [f for f in p.get("found") or [] if isinstance(f, dict)], "mine": str(p.get("mine") or "").strip(),
                                  "use": use if use in USES else "", "why": str(p.get("why") or "").strip()}
    return out


def own(output: str) -> bool:
    """模型说这篇整篇讲的是 作者自己的产品、做法：截图优先。"""
    return _answer(output).get("own") is True


def decide(got: dict[str, Any]) -> str:
    """模型没给 use（或给错了）时按同一个顺序补：有「你来截」的待办 → 截图；找到外面的 → 外面；都没有 → 插图。"""
    if got.get("use") in USES:
        return got["use"]
    if got.get("mine"):
        return "mine"
    return "outside" if got.get("found") else "illustration"


# -- 核对 ---------------------------------------------------------------------------------

def norm(text: str) -> str:
    """只留字和数：大小写、空格、标点、换行都不算。"""
    return re.sub(r"[\W_]+", "", (text or "").lower())


def locate(quote: str, body: str) -> str | None:
    """引的原话在页面上：逐字对上，只容忍夹在中间的脚注号（「market,2 we」）——只跳数字，
    跳字母会把页面上的 not 跳过去，意思就反了。
    对上了返回页面上那一段（去掉标点空格后的），截图时高亮它；对不上返回 None。"""
    q, b = norm(quote), norm(body)
    if len(q) < MIN_QUOTE:
        return None
    if q in b:
        return q
    budget = max(3, len(q) // 20)
    start = b.find(q[:MIN_QUOTE])
    while start != -1:
        i, j, skipped = MIN_QUOTE, start + MIN_QUOTE, 0
        while i < len(q) and j < len(b) and skipped <= budget:
            if b[j] == q[i]:
                i += 1
            elif b[j].isdigit():
                skipped += 1
            else:
                break
            j += 1
        if i == len(q) and skipped <= budget:
            return b[start:j]
        start = b.find(q[:MIN_QUOTE], start + 1)
    return None


# 平台：一个域名下是成千上万个不同的作者，按域名算「同一家」会让一篇只能用一篇公众号文章
PLATFORMS = ("weixin.qq.com", "zhihu.com", "weibo.com", "weibo.cn", "36kr.com", "xiaohongshu.com", "douyin.com", "bilibili.com",
             "toutiao.com", "sohu.com", "163.com", "sina.com.cn", "baidu.com", "medium.com", "substack.com", "youtube.com",
             "reddit.com", "linkedin.com", "github.com")


def source_key(item: dict[str, Any]) -> str:
    """一篇里同一个人 / 同一家只用一次：推文认账号，网页认域名；平台上的文章认「平台 + 谁写的」。"""
    m = TWEET_ID.search(str(item.get("url") or ""))
    if m:
        return "x:" + m.group(1).lower()
    host = re.sub(r"^(www|m|mp)\.", "", urlparse(str(item.get("url") or "")).netloc.lower())
    if any(host == d or host.endswith("." + d) for d in PLATFORMS):
        return f"{host}:{norm(str(item.get('source') or ''))}"
    return host


# 在页面上找到那一段原话本身（不是包着它的整块），只高亮这几句；返回它在视口里的位置和页面的日期、站名。
# 只认字和数（\p{L}\p{N}，和 Python 的 norm 一致）——JS 的 \W 不认汉字，用它中文页面永远对不上。
FIND_JS = r"""(q) => {
  const keep = /[\p{L}\p{N}]/u;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {acceptNode: (n) => {
    const tag = n.parentElement ? n.parentElement.tagName : 'SCRIPT';
    return ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(tag) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
  }});
  let flat = '';
  const map = [];
  for (let n; (n = walker.nextNode());) {
    const t = n.nodeValue;
    for (let i = 0; i < t.length; i++) if (keep.test(t[i])) { flat += t[i].toLowerCase(); map.push([n, i]); }
  }
  for (let k = flat.indexOf(q); k >= 0; k = flat.indexOf(q, k + 1)) {
    const [sn, so] = map[k];
    const [en, eo] = map[k + q.length - 1];
    const range = document.createRange();
    range.setStart(sn, so);
    range.setEnd(en, eo + 1);
    if (!range.getBoundingClientRect().width) continue;  // 藏起来的那份（菜单、折叠）不算
    // 盖在上面的东西（Cookie 同意框、半透明遮罩、吸顶栏）都收起来，不然截出来是灰的或被挡住
    for (const el of document.querySelectorAll('body *')) {
      const pos = getComputedStyle(el).position;
      if ((pos === 'fixed' || pos === 'sticky') && !el.contains(sn)) el.style.setProperty('display', 'none', 'important');
    }
    document.documentElement.style.overflow = 'visible';
    document.body.style.overflow = 'visible';
    document.documentElement.style.scrollBehavior = 'auto';  // 有的页面平滑滚动：一滚就停在半路
    sn.parentElement.scrollIntoView({block: 'center', behavior: 'instant'});
    const style = document.createElement('style');
    style.textContent = '::highlight(proof){background-color:rgba(255,214,0,.6)}';
    document.head.appendChild(style);
    CSS.highlights.set('proof', new Highlight(range));
    const r = range.getBoundingClientRect();
    // 左右按那一整段算：原话从一行中间开始时，只按原话截会把行首切掉
    const block = sn.parentElement.closest('p,li,blockquote,td,dd,figcaption,h1,h2,h3,h4,div') || sn.parentElement;
    const col = block.getBoundingClientRect();
    const meta = (n) => (document.querySelector(`meta[property="${n}"],meta[name="${n}"],meta[itemprop="${n}"]`) || {}).content || '';
    const time = document.querySelector('time[datetime]');
    return {left: Math.min(r.left, col.left) + scrollX, right: Math.max(r.right, col.right) + scrollX, top: r.top + scrollY, bottom: r.bottom + scrollY, title: document.title, site: meta('og:site_name'),
            date: meta('article:published_time') || meta('datePublished') || meta('pubdate') || meta('publishdate') || (time && time.getAttribute('datetime')) || ''};
  }
  return null;
}"""


def look_page(url: str, quote: str, out: Path) -> dict[str, Any] | None:
    """无头浏览器打开网页：正文里真有这句话才截——那一段高亮，上下留一点上下文。"""
    from playwright.sync_api import Error as PwError, sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 1400}, device_scale_factor=2, locale="zh-CN", user_agent=UA)
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2500)
                body = page.inner_text("body")
                q = locate(quote, body) if len(norm(body)) >= MIN_PAGE else None
                if not q:
                    return None
                hit = page.evaluate(FIND_JS, q)
                if not hit:
                    return None
                page.wait_for_timeout(300)
                # 只截那一栏正文：高亮那几句上下各留几行，左右留一点边，不带侧栏。坐标是整页的（不靠滚到哪）
                left = max(0, hit["left"] - 32)
                right = min(1000, max(hit["right"] + 32, left + 560))
                top = max(0, hit["top"] - 140)
                bottom = min(top + 1400, max(hit["bottom"] + 140, top + 320))
                page.screenshot(path=str(out), full_page=True, clip={"x": left, "y": top, "width": right - left, "height": bottom - top})
                return {"title": hit["title"], "site": hit["site"], "date": str(hit["date"])[:10]}
            finally:
                browser.close()
    except PwError:
        return None


def check(found: dict[str, Any], dest: Path, *, page: Page, lookup: Lookup, shot: Shot) -> tuple[dict[str, Any] | None, str]:
    """一条候选：核对过、截好图返回 (证据, "")；不行返回 (None, 为什么)。"""
    url = str(found.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None, "没有原网页链接"
    keep = {k: str(found.get(k) or "").strip() for k in ("source", "date", "quote", "claim", "caption")}
    if TWEET_ID.search(url):
        ok = verify_tweet({**found, "screen_name": found.get("screen_name") or ""}, lookup)
        if not ok:
            return None, "查不到这条推文，或者不是这个人发的、原话对不上"
        dest = dest.with_suffix(".png")
        try:
            shot(ok["id"], dest)
        except EvidenceError as exc:
            return None, str(exc)
        return {**keep, "kind": "tweet", "file": dest.name, "url": ok["url"], "source": keep["source"] or "@" + ok["screen_name"],
                "date": (ok.get("created_at") or keep["date"])[:10], "quote": ok["text"]}, ""
    if len(norm(keep["quote"])) < MIN_QUOTE:
        return None, "没给页面原话，没法核对"
    dest = dest.with_suffix(".png")
    got = page(url, keep["quote"], dest)
    if not got or not dest.is_file():
        return None, "网页打不开、要付费，或者页面上找不到这句原话"
    kind = str(found.get("kind") or "news")
    return {**keep, "kind": kind if kind in KINDS else "news", "file": dest.name, "url": url,
            "source": keep["source"] or got.get("site") or urlparse(url).netloc,
            "date": got.get("date") or keep["date"], "page_title": got.get("title") or ""}, ""


# -- 状态 ---------------------------------------------------------------------------------

def folder(base: Path) -> Path:
    return base / FOLDER


def load(base: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder(base) / STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save(base: Path, data: dict[str, Any]) -> None:
    folder(base).mkdir(parents=True, exist_ok=True)
    (folder(base) / STATE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def view(base: Path, skeleton: str) -> dict[str, Any]:
    """骨架页要画的：按现在骨架的论点排，每个论点下面是找到的、他传的、他要去截的。
    以前找的、现在骨架里没有这个论点了，放在「别的」下面，不丢。"""
    data = load(base) or {}
    pts = points(skeleton)
    found = {p["key"]: p for p in data.get("points") or []}
    out = []
    for p in pts:
        old = found.pop(p["key"], {})
        items = [i for i in old.get("items") or [] if (folder(base) / str(i.get("file") or "")).is_file()]
        out.append({**p, "missing": missing(p["line"]), "mine": old.get("mine") or "", "items": items,
                    "use": old.get("use") or "", "why": old.get("why") or "", "use_by": old.get("use_by") or "",
                    "short": old.get("use") == "mine" and not _has_shot(items)})
    for key, old in found.items():
        items = [i for i in old.get("items") or [] if (folder(base) / str(i.get("file") or "")).is_file()]
        if items:
            out.append({"key": key, "title": old.get("title") or f"论点 {key}", "line": "", "missing": False, "mine": "", "items": items, "gone": True})
    chosen = [i for p in out for i in p["items"] if i.get("pick")]
    return {"searched": bool(data.get("points")), "searched_at": data.get("searched_at"),
            "sheet": bool(data.get("sheet")), "own": bool(data.get("own")), "uses": USES,
            "stale": bool(data.get("skeleton")) and data.get("skeleton") != signature(skeleton),
            "points": out, "chosen": len(chosen), "rejected": len(data.get("rejected") or [])}


def _has_shot(items: list[dict[str, Any]]) -> bool:
    return any(i.get("kind") == "mine" and i.get("pick") for i in items)


def missing_shots(base: Path, skeleton: str) -> list[dict[str, str]]:
    """证据单定了「你的截图」、他还没传的论点（按现在骨架的论点算）。卡发用：没有证据单的老选题一律不卡。"""
    st = view(base, skeleton)
    if not st["sheet"]:
        return []
    return [{"key": p["key"], "title": p["title"], "todo": p["mine"]} for p in st["points"] if not p.get("gone") and p["short"]]


def illustration_plan(base: Path, skeleton: str) -> dict[str, list[str]] | None:
    """配图照证据单：只画定了「插图」的论点，别的论点不画。没有证据单就 None（照旧整篇配）。"""
    st = view(base, skeleton)
    if not st["sheet"]:
        return None
    pts = [p for p in st["points"] if not p.get("gone")]
    return {"draw": [p["title"] for p in pts if p["use"] == "illustration"],
            "skip": [p["title"] for p in pts if p["use"] != "illustration"]}


def set_use(base: Path, key: str, title: str, use: str) -> None:
    """他改某个论点用什么证明（含「这条不要证据」）。再找一遍也不改回去。"""
    if use not in USES:
        raise EvidenceError("不认识这种证据")
    data = load(base) or {}
    p = _point(data, key, title)
    p["use"], p["use_by"] = use, "park"
    data["sheet"] = 1
    save(base, data)


def chosen(base: Path) -> list[dict[str, Any]]:
    """他点过「要」的（带论点和本机路径）：视频动效、文章配图都从这里拿。"""
    data = load(base) or {}
    out = []
    for p in data.get("points") or []:
        for i in p.get("items") or []:
            path = folder(base) / str(i.get("file") or "")
            if i.get("pick") and path.is_file():
                out.append({**i, "point": p.get("key"), "point_title": p.get("title") or "", "path": str(path)})
    return out


def _point(data: dict[str, Any], key: str, title: str = "") -> dict[str, Any]:
    for p in data.setdefault("points", []):
        if p.get("key") == key:
            return p
    p = {"key": key, "title": title, "mine": "", "items": [], "use": "", "why": ""}
    data["points"].append(p)
    return p


def pick(base: Path, file: str, want: bool) -> None:
    data = load(base)
    for p in (data or {}).get("points") or []:
        for i in p.get("items") or []:
            if i.get("file") == file:
                i["pick"] = bool(want)
                save(base, data)
                return
    raise EvidenceError("这张不在证据里了，刷新一下")


def to_png(src: Path, dest: Path) -> None:
    """macOS 自带的 sips 转格式。"""
    try:
        done = subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(dest)], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        done = None
    if done is None or done.returncode != 0 or not dest.is_file():
        raise EvidenceError("这张 HEIC 转不成 PNG：在相册里导出成 PNG / JPG 再传")


def add_mine(base: Path, key: str, title: str, name: str, content: bytes, *, now: str, read: Callable[[list[Path]], dict[Path, str]] | None = None) -> dict[str, Any]:
    """他自己截的图传上来：读一遍字，有 AppID、密钥、手机号、邮箱就不收（让他裁掉再传）。传了就是「要」。"""
    suffix = Path(name).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".heic"):
        raise EvidenceError(f"只收图片（png、jpg），这是 {suffix or '没有扩展名'}")
    if not content:
        raise EvidenceError("没收到图")
    folder(base).mkdir(parents=True, exist_ok=True)
    stem = f"mine-{key}-{hashlib.sha1(content).hexdigest()[:8]}"
    if suffix == ".heic":  # iPhone 照片：视频、公众号都不认 HEIC，进来就转成 PNG
        raw = folder(base) / f"{stem}.heic"
        raw.write_bytes(content)
        dest = folder(base) / f"{stem}.png"
        try:
            to_png(raw, dest)
        finally:
            raw.unlink(missing_ok=True)
    else:
        dest = folder(base) / f"{stem}{suffix}"
        dest.write_bytes(content)
    hit = private_hit((read or ocr)([dest]).get(dest) or "")
    if hit:
        dest.unlink()
        raise EvidenceError(f"图里像是有隐私（{hit[:4]}…）：裁掉那块再传")
    data = load(base) or {}
    p = _point(data, key, title)
    p["items"] = [i for i in p.get("items") or [] if i.get("file") != dest.name]
    item = {"kind": "mine", "file": dest.name, "url": "", "source": "我自己的截图", "date": now[:10], "quote": "",
            "claim": title, "caption": p.get("mine") or title, "pick": True}
    p["items"].append(item)
    save(base, data)
    return item


def remove(base: Path, file: str) -> None:
    """只删他自己传的；找来的不要就取消「要」。"""
    data = load(base) or {}
    for p in data.get("points") or []:
        for i in p.get("items") or []:
            if i.get("file") == file:
                if i.get("kind") != "mine":
                    raise EvidenceError("找来的证据不删，不要就取消「要」")
                p["items"].remove(i)
                (folder(base) / file).unlink(missing_ok=True)
                save(base, data)
                return
    raise EvidenceError("这张不在证据里了，刷新一下")


# -- 跑一遍 -------------------------------------------------------------------------------

def run(base: Path, title: str, skeleton: str, *, now: str, llm: LLM | None = None,
        page: Page = look_page, lookup: Lookup = lookup_tweet, shot: Shot = shoot_tweet) -> dict[str, Any]:
    """按骨架的论点找一遍。他点过「要」的、他自己传的留着，其余换成这次找到的。"""
    from ...writer import cli_write

    pts = points(skeleton)
    if not pts:
        raise EvidenceError("骨架里没有「### 论点」，不知道给哪儿找证据")
    data = load(base) or {}
    kept = {p.get("key"): [i for i in p.get("items") or [] if i.get("pick") or i.get("kind") == "mine"] for p in data.get("points") or []}
    used = {source_key(i) for items in kept.values() for i in items if i.get("kind") != "mine"}
    prompt = build_prompt(title, skeleton, pts, avoid=sorted(used))
    folder(base).mkdir(parents=True, exist_ok=True)
    (folder(base) / "prompt.md").write_text(prompt, encoding="utf-8")
    raw = (llm or (lambda p: cli_write(p, command=PROOF_COMMAND, timeout=1800)))(prompt)
    (folder(base) / "answer.txt").write_text(raw, encoding="utf-8")
    plan = parse(raw)
    # 模型跑了几分钟，这期间他可能点了「要」、传了自己的截图：按现在的 proof.json 重新算要留的，别拿开跑前的快照覆盖
    data = load(base) or {}
    kept = {p.get("key"): [i for i in p.get("items") or [] if i.get("pick") or i.get("kind") == "mine"] for p in data.get("points") or []}
    used = {source_key(i) for items in kept.values() for i in items if i.get("kind") != "mine"}
    his = {p.get("key"): p.get("use") for p in data.get("points") or [] if p.get("use_by") == "park" and p.get("use") in USES}
    whole = own(raw)

    keep_files = {i["file"] for items in kept.values() for i in items}
    for f in folder(base).glob("*"):
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".heic") and f.name not in keep_files:
            f.unlink()
    out, rejected = [], []
    for p in pts:
        got = plan.get(p["key"], {"found": [], "mine": ""})
        items = list(kept.get(p["key"], []))
        n = 0
        for f in got["found"]:
            if n >= PER_POINT:
                break
            key = source_key(f)
            if key in used:
                rejected.append({**f, "point": p["key"], "why": "同一个人 / 同一家这篇已经用过了"})
                continue
            stem = f"{p['key']}-{hashlib.sha1(str(f.get('url')).encode()).hexdigest()[:8]}"
            if any(Path(i["file"]).stem == stem for i in items):
                continue
            item, why = check(f, folder(base) / stem, page=page, lookup=lookup, shot=shot)
            if item is None:
                rejected.append({**f, "point": p["key"], "why": why})
                continue
            used.add(key)
            items.append({**item, "pick": None})
            n += 1
        todo = got["mine"] if got["mine"] or not missing(p["line"]) else p["line"]
        use = his.get(p["key"]) or decide({**got, "mine": todo})
        out.append({"key": p["key"], "title": p["title"], "mine": todo, "items": items, "use": use, "why": got.get("why", ""),
                    "use_by": "park" if p["key"] in his else ""})
    result = {"skeleton": signature(skeleton), "searched_at": now, "sheet": 1, "own": whole, "points": out, "rejected": rejected}
    save(base, result)
    return result
