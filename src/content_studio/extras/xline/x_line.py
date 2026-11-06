"""X 单独一条线：素材从 作者自己的三处来，他挑、他改、他点了才发。

作者 10/4：X 要单独运营——内容自由、长短随意、一天可以发很多条，不等抖音两三天一条的节奏；
视频主线照旧也发 X。素材「all I have」就三处：他的 GitHub（自己做的）、他的网站（原则、预测、
Good Product 里测评别人的）、他的 Obsidian（自己写的原始输出、进项里收的）。

规矩：
- 只列他自己的东西。GitHub 只读公开仓库（不带密钥的公开接口，私有仓库根本拿不到）；
  Obsidian 不碰「对标内容」（那是别人的视频转写）。
- 不自动处理（他先看原始的）：卡片上是原文，原则、预测本来就是一句话，直接填进去；
  别人的东西（Good Product、进项）只填标题和链接，正文不当成他的话。
- AI 只在他点「整理」时跑，规矩和写文章是同一份：writer.original_words_rules()。
- 发帖只在他点过的时候调用，用他自己的密钥（x_post）。10/5 作者 定：每日短帖（x_daily.py）他一条条打了勾的，
  当天排着发（「排着发，先 10 条」）；没打勾的永远不发。除此之外不自动发。
- KPI 还没拍板：这里只数今天发了几条，不进「今天」的计分。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.request

from ... import conf, vault, writer
from ...paths import config_dir

GITHUB_USER_ENV = "CONTENT_STUDIO_X_GITHUB"
SITE_ENV = "CONTENT_STUDIO_X_SITE"
STATE_FILE = "x_line.json"
CACHE_SECONDS = 30 * 60
OBSIDIAN_DAYS = 7  # 进项只看最近一周；自己写的原始输出不限时间
# 原始输出里不是「想说的话」的文件：客户咨询记录（客户的隐私）、工作台自己的追踪表。
PRIVATE_NOTE = re.compile(r"客户|咨询|追踪表")
POST_BLOCK = re.compile(r"<<<POST>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)

Fetch = Callable[[str], Any]


class XLineError(RuntimeError):
    """Shown to 作者 as-is."""


# 10/6：不再默认是 作者 的 GitHub 和网站。没在 profile 里填（me.github / me.site，老的 x_line.* 也认）就是没有这两路素材。
def github_user() -> str:
    return conf.github_login(os.environ.get(GITHUB_USER_ENV))


def site() -> str:
    return conf.site_url(os.environ.get(SITE_ENV))


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "content-studio"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise XLineError(f"{url} 返回 {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise XLineError(f"读不到 {url}：{exc}") from exc


# -- sources -------------------------------------------------------------------


def _card(kind: str, key: str, title: str, body: str, *, url: str | None = None, at: str | None = None,
          prefill: str = "", own: bool = True, long: bool = False, tag: str = "") -> dict[str, Any]:
    return {"id": f"{kind}:{key}", "kind": kind, "title": title, "body": body, "url": url, "at": at,
            "prefill": prefill, "own": own, "long": long, "tag": tag}


GH_PATHS = ("/opt/homebrew/bin/gh", "/usr/local/bin/gh")


def github_repos(user: str, fetch: Fetch = fetch_json) -> Any:
    """先用本机已登录的 gh（不吃匿名额度：匿名每小时 60 次，同一出口的人共用，常常是 0）；没有 gh 再走匿名接口。
    两条路都是 /users/<user>/repos，只返回公开仓库。"""
    import shutil
    import subprocess

    path = f"users/{user}/repos?sort=pushed&per_page=100&type=owner"
    gh = shutil.which("gh") or next((p for p in GH_PATHS if Path(p).is_file()), None)
    if gh and fetch is fetch_json:
        try:
            done = subprocess.run([gh, "api", path], capture_output=True, text=True, timeout=30, check=False)
            if done.returncode == 0:
                return json.loads(done.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    return fetch(f"https://api.github.com/{path}")


def github_cards(fetch: Fetch = fetch_json, user: str | None = None) -> list[dict[str, Any]]:
    who = user or github_user()
    if not who:
        return []
    repos = github_repos(who, fetch)
    cards = []
    for r in repos if isinstance(repos, list) else []:
        # 公开接口本来只给公开仓库；再挡一道，免得哪天换成带密钥的接口把私有仓库发出去。
        if r.get("private") or r.get("fork") or r.get("archived"):
            continue
        desc = (r.get("description") or "").strip()
        cards.append(_card("github", r["name"], r["name"], desc, url=r.get("html_url"), at=r.get("pushed_at"),
                           prefill="\n".join(x for x in (desc, r.get("html_url") or "") if x),
                           tag=f"★ {r['stargazers_count']}" if r.get("stargazers_count") else ""))
    return cards


# 和网站上的叫法一样（park-ai-intel scripts/reading-interactions.ts）
CATEGORY = {"universal": "万物逻辑", "trading": "交易", "content": "做内容", "agent_harness": "Agent harness", "relationships": "做人",
            "ai": "AI", "employment": "就业", "society": "社会", "company": "公司", "markets": "金融市场"}


def principle_cards(fetch: Fetch = fetch_json) -> list[dict[str, Any]]:
    if not site():
        return []
    state = (fetch(f"{site()}/api/principles") or {}).get("state") or {}
    return [_card("principle", p["id"], CATEGORY.get(p.get("primaryCategory"), p.get("primaryCategory") or "原则"), p["quote"],
                  prefill=p["quote"], url=f"{site()}/principles") for p in state.get("principles") or [] if p.get("quote")]


HORIZON = {"short": "短期", "medium": "中期", "long": "长期"}
STATUS = {"open": "待验证", "hit": "说中了", "miss": "没说中"}


def prediction_cards(fetch: Fetch = fetch_json) -> list[dict[str, Any]]:
    if not site():
        return []
    state = (fetch(f"{site()}/api/predictions") or {}).get("state") or {}
    return [_card("prediction", p["id"], f"{HORIZON.get(p.get('horizon'), p.get('horizon') or '')}预测 · {CATEGORY.get(p.get('topic'), p.get('topic') or '')}".rstrip(" ·"), p["quote"],
                  prefill=p["quote"], url=f"{site()}/principles#predictions",
                  tag=STATUS.get(p.get("status"), p.get("status") or ""))
            for p in state.get("predictions") or [] if p.get("quote")]


def goodproduct_cards(fetch: Fetch = fetch_json) -> list[dict[str, Any]]:
    if not site():
        return []
    entries = fetch(f"{site()}/goodproduct/manifest.json")
    cards = []
    for e in reversed(entries if isinstance(entries, list) else []):
        link = e.get("source_url") or f"{site()}/goodproduct/"
        cards.append(_card("goodproduct", e["id"], e.get("title") or e["id"], (e.get("note") or "").strip(), url=link,
                           at=e.get("collected_at"), prefill=f"{e.get('title') or ''}\n{link}".strip(), own=False,
                           tag={"tool": "工具", "inspiration": "参考"}.get(e.get("kind"), "")))
    return cards


def obsidian_cards(vault_raw: str, *, keys: tuple[str, ...], own: bool, days: int = OBSIDIAN_DAYS) -> list[dict[str, Any]]:
    if not vault_raw:
        raise XLineError("设置里还没填 Obsidian 库路径")
    since = vault.window_start(days)
    out = []
    for item in vault.inbox(vault_raw, since=since, sources=keys):
        if own and PRIVATE_NOTE.search(item["path"]):
            continue
        try:
            note = vault.read_note(vault_raw, item["path"])
        except vault.VaultError:
            continue
        body = (note.get("body") or "").strip()
        url = note["meta"].get("source") or note["meta"].get("url")
        out.append(_card("obsidian" if own else "inbox", item["path"], item["title"], body[:4000], url=url,
                         at=item.get("modified_at"), own=own, long=len(body) > 400,
                         # 自己写的短笔记直接填进去；长的点「整理」拆成几条。别人的只填标题和链接。
                         prefill=(plain(body) if len(body) <= 400 else "") if own else f"{item['title']}\n{url or ''}".strip()))
    return out


SOURCES: tuple[tuple[str, str, str], ...] = (
    # (key, 标签, 一句话)
    ("obsidian", "我写的", "Obsidian 里你自己的原始输出"),
    ("github", "我做的", "GitHub 公开仓库，最近动过的在前"),
    ("principle", "原则", "网站上的原则，一句就是一条"),
    ("prediction", "预测", "网站上的预测，带状态"),
    ("goodproduct", "我测评的", "网站 Good Product：别人的产品"),
    ("inbox", "选题", "Obsidian 选题里最近一周收的（别人的东西，只填标题和链接）"),
)


class Cache:
    """远程素材（GitHub、网站）半小时读一次；Obsidian 在本机，每次现读。"""

    def __init__(self, ttl: float = CACHE_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self.clock, self._data, self._lock = ttl, clock, {}, threading.Lock()

    def get(self, key: str, load: Callable[[], list[dict[str, Any]]], *, fresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            hit = self._data.get(key)
            if hit and not fresh and self.clock() - hit[0] < self.ttl:
                return hit[1]
        value = load()
        with self._lock:
            self._data[key] = (self.clock(), value)
        return value


def gather(vault_raw: str, *, cache: Cache, fetch: Fetch = fetch_json, fresh: bool = False) -> list[dict[str, Any]]:
    loaders: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "obsidian": lambda: obsidian_cards(vault_raw, keys=("raw",), own=True, days=3650),
        "github": lambda: cache.get("github", lambda: github_cards(fetch), fresh=fresh),
        "principle": lambda: cache.get("principle", lambda: principle_cards(fetch), fresh=fresh),
        "prediction": lambda: cache.get("prediction", lambda: prediction_cards(fetch), fresh=fresh),
        "goodproduct": lambda: cache.get("goodproduct", lambda: goodproduct_cards(fetch), fresh=fresh),
        "inbox": lambda: obsidian_cards(vault_raw, keys=("clipping", "saved"), own=False),
    }
    out = []
    for key, label, hint in SOURCES:
        try:
            items, error = loaders[key](), None
        except (XLineError, vault.VaultError) as exc:
            items, error = [], str(exc)
        out.append({"key": key, "label": label, "hint": hint, "items": items, "error": error})
    return out


# -- state: what was posted / set aside ----------------------------------------


def state_path(root: Path | None = None) -> Path:
    return (root or config_dir()) / STATE_FILE


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"posts": data.get("posts") or [], "skipped": data.get("skipped") or []}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".x_line-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


_LOCK = threading.Lock()


def record_post(path: Path, *, text: str, source_id: str | None, how: str, url: str | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    row = {"at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "text": text.strip(),
           "source_id": source_id or None, "how": how, "url": url}
    with _LOCK:
        data = load_state(path)
        data["posts"].append(row)
        _save(path, data)
    return row


def skip(path: Path, source_id: str, *, undo: bool = False) -> list[str]:
    with _LOCK:
        data = load_state(path)
        skipped = [s for s in data["skipped"] if s != source_id]
        if not undo:
            skipped.append(source_id)
        data["skipped"] = skipped
        _save(path, data)
    return skipped


def today_count(posts: list[dict[str, Any]], now: datetime | None = None) -> int:
    """北京时间的今天（和日结一样，一天是北京时间 0–24 点）。"""
    from datetime import timedelta

    bj = timezone(timedelta(hours=8))
    today = (now or datetime.now(timezone.utc)).astimezone(bj).date()
    return sum(1 for p in posts if datetime.fromisoformat(p["at"]).astimezone(bj).date() == today)


# -- 整理 ------------------------------------------------------------------------


def organize_prompt(text: str, error: str | None = None) -> str:
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    return f"""下面是 作者自己的一段原话（他随口说的、写的，或者他的笔记）。把它整理成可以直接发 X 的帖子。

整理规矩（不能破）：
{writer.original_words_rules()}

怎么拆：
- 一个意思一条。原话只有一个意思就只出一条；有几个独立的判断就拆成几条，每条单独拿出来也看得懂。
- 长短跟着内容走，不凑字数，不硬压到 140 字；不加话题标签、不加表情、不加「关注我」。
- 原话里没有的东西一个字都不要加。

## 原话
{text.strip()}

## 输出
每条帖子放在单独一行的 <<<POST>>> 和单独一行的 <<<END>>> 之间，按你建议的发帖先后排；前后不要有其他说明。{retry}"""


def posts_fidelity(posts: list[str], original: str) -> float:
    """每条单独核对、按长短加权。拼成一段再核对的话，挪过顺序的两条之间会凭空多出几个「跨条」的四字组，冤枉好整理。"""
    total = sum(len(writer._grams(p)) for p in posts)
    if not total:
        return 1.0
    return sum(writer.fidelity(p, original) * len(writer._grams(p)) for p in posts) / total


def plain(md: str) -> str:
    """笔记要发到 X：去掉 Markdown 的标题行和符号（# ** ` > 列表符），字不动。"""
    lines = []
    for line in md.splitlines():
        if re.match(r"^\s*#", line) or re.match(r"^\s*(---|\*\*\*)\s*$", line):
            continue
        line = re.sub(r"^\s*(>\s*|[-*+]\s+)", "", line)
        lines.append(re.sub(r"\*\*|__|`", "", line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def organize(text: str, *, write_fn: Callable[[str], str] = writer.cli_write, attempts: int = 2) -> list[str]:
    text = text.strip()
    if not text:
        raise XLineError("先贴一段你的原话")
    error = None
    for _ in range(attempts):
        posts = [p.strip() for p in POST_BLOCK.findall(write_fn(organize_prompt(text, error))) if p.strip()]
        if not posts:
            error = "没有按 <<<POST>>> 格式返回"
            continue
        score = posts_fidelity(posts, text)
        if score < writer.MIN_FIDELITY:
            error = f"改动太多：只有 {score:.0%} 能在原话里找到，要只删口语、调顺序，不改词"
            continue
        return posts
    raise XLineError(f"连续 {attempts} 次没整理好：{error}")
