"""Read-only access to 作者's Obsidian vault.

Only the folders listed in DAILY_SOURCES and INBOX_SOURCES are visible; every other
folder in the vault (including secrets) is unreachable through this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import re
from typing import Any


@dataclass(frozen=True)
class DailySource:
    key: str
    label: str
    folder: str
    suffixes: tuple[str, ...]
    # Where the newsletter pipeline keeps each item's full text (<items>/<YY-MM-DD>/…/*.md).
    # Only then can 作者 take a single 快讯 into 选题池 with its original text.
    items: str | None = None
    # A shared folder (2026-09-28: 财经日报 and 财经周报 live in one folder, K 线周报 sits next to
    # K 线日报) — only file names containing this belong to the daily.
    match: str = ""


@dataclass(frozen=True)
class InboxSource:
    key: str
    label: str
    folder: str
    # 主动 vs 被动。Clippings / 我收藏的 是 作者自己放进去的，「新」看他什么时候放。
    # 对标内容是工作台替他收的：一个新账号第一次同步会一次性写进几十篇，按写入时间算它们
    # 全是「今天的」。所以被动来源的时间以作者的发布时间为准。
    passive: bool = False
    # 无时效：作者自己写的东西是素材库，不是新闻流。两个月前写的一段想法，只要还没拍，
    # 今天照样可以拍——时间窗会把它挡在外面，而它本来就该一直等在那儿。
    # 「还没处理过」由 triage / used_by 负责过滤，不靠时间。
    timeless: bool = False


# 作者 reads all three dailies in the morning (2026-09-19: he asked for 财经 and K 线 back).
# 晨报 is a digest of these three, so it stays out to avoid showing the same thing twice.
DAILY_SOURCES = (
    DailySource("ai_daily", "AI 日报", "006_ai daily newsletter", (".md",), "~/park-io/_inbox/processed"),
    DailySource("finance_daily", "财经日报", "007_finance newsletter", (".md",), match="finance-daily-newsletter"),
    DailySource("kline_daily", "K 线日报", "007_kline daily newsletter", (".md",), match="kline-daily-newsletter"),
)

INBOX_SOURCES = (
    # 对标内容 is the one folder the workbench writes to: transcripts of what the accounts 作者
    # follows just posted, so he can read them in 进项 and attach them to a topic as 素材.
    InboxSource("benchmark", "对标内容", "002_对标内容", passive=True),
    InboxSource("clipping", "Clippings", "002_clippings"),
    InboxSource("saved", "我收藏的", "002_个人收藏"),
    InboxSource("raw", "我的原始输出", "003_原始输出", timeless=True),
)

READABLE_SUFFIXES = (".md", ".html")
SERIES_INDEX = "系列.md"  # 系列的目录（series.py）：一行一集标题，不是他说的一段话，进项和 X 素材都跳过

# 默认值单独冻结：configure() 每次都从这里重建，不从「当前值」重建。
# 否则跑过一次配置之后（比如某个测试、或者改了 profile 再热加载），被去掉的可选来源
# 就再也找不回来了——而且 _allowed_folders() 的白名单会跟着缩，读笔记直接被拒。
_DEFAULT_INBOX_SOURCES = INBOX_SOURCES
_DEFAULT_DAILY_SOURCES = DAILY_SOURCES


def configure(vault_cfg: dict | None) -> None:
    """让 profile.yaml 里的文件夹名真正生效，而不是只校验一遍。

    INBOX_SOURCES / DAILY_SOURCES 原来是写死的常量——那是 作者 一个人库的目录名。
    别人的库叫别的名字，这两个元组就得由配置生成。没给的项保留默认值，
    所以 作者自己不配 profile 也和以前一样。传 None 就复位成默认。
    """
    global INBOX_SOURCES, DAILY_SOURCES
    INBOX_SOURCES, DAILY_SOURCES = _DEFAULT_INBOX_SOURCES, _DEFAULT_DAILY_SOURCES
    if not vault_cfg:
        return
    folders = vault_cfg.get("folders") or {}
    by_key = {s.key: s for s in _DEFAULT_INBOX_SOURCES}
    rebuilt = []
    for key, folder_key in (("benchmark", "benchmark_transcripts"), ("clipping", "clippings"), ("saved", "saved"), ("raw", "my_writing")):
        base = by_key[key]
        name = str(folders.get(folder_key) or "").strip()
        if not name and key in ("clipping", "saved"):
            # 可选来源没配就不列——列一个不存在的文件夹只会让进项多一个永远空的 tab
            continue
        rebuilt.append(InboxSource(key, base.label, name or base.folder, passive=base.passive, timeless=base.timeless))
    INBOX_SOURCES = tuple(rebuilt)
    dailies = vault_cfg.get("dailies")
    if isinstance(dailies, list):
        DAILY_SOURCES = tuple(
            DailySource(str(d["key"]), str(d.get("label") or d["key"]), str(d["folder"]), (".md",), str(d["items"]) if d.get("items") else None, str(d.get("match") or ""))
            for d in dailies if isinstance(d, dict) and d.get("key") and d.get("folder")
        )

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class VaultError(ValueError):
    """The vault path is missing or a requested file is outside the allowed folders."""


def _allowed_folders() -> tuple[str, ...]:
    return tuple(s.folder for s in DAILY_SOURCES) + tuple(s.folder for s in INBOX_SOURCES)


def vault_root(raw: str) -> Path:
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise VaultError(f"找不到 Obsidian 库：{raw}")
    return root.resolve()


def safe_path(root: Path, relative: str) -> Path:
    """Resolve a vault-relative path, refusing anything outside the allowed folders."""
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise VaultError("文件路径无效")
    candidate = (root / relative).resolve()
    for folder in _allowed_folders():
        base = (root / folder).resolve()
        if candidate == base or base in candidate.parents:
            if candidate.suffix.lower() not in READABLE_SUFFIXES or not candidate.is_file():
                raise VaultError("文件不存在")
            return candidate
    raise VaultError("文件不存在")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        found = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if found:
            value = found.group(2).strip()
            decoded = None
            if value.startswith('"') and value.endswith('"'):
                try:
                    decoded = json.loads(value)
                except ValueError:
                    pass  # 旧笔记不一定是 JSON 字符串，沿用原来的宽松读取。
            meta[found.group(1)] = decoded if isinstance(decoded, str) else value.strip('"').strip("'")
    return meta, text[match.end():]


def plain_summary(body: str, limit: int = 120) -> str:
    text = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|!\[\[[^\]]*\]\]", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^[#>\-*+\s]+|[*_`~]", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


TITLE_PREFIX = re.compile(r"^文章标题[:：]\s*")


def _title(path: Path, meta: dict[str, str], body: str) -> str:
    if meta.get("title"):
        return TITLE_PREFIX.sub("", meta["title"])
    heading = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if heading:
        return TITLE_PREFIX.sub("", heading.group(1).strip())
    return path.stem


def _card_body(body: str, title: str) -> str:
    """卡片摘要只要正文：X 收藏的笔记开头是「# 文章标题：…」+「source: 我的 X 收藏 · link」+ 再来一遍标题，
    直接截前 120 字，卡片上全是这些。笔记本身不改（日报、索引都读这个格式）。"""
    key = re.sub(r"\W", "", title)
    kept = []
    for line in body.splitlines():
        bare = TITLE_PREFIX.sub("", re.sub(r"^#+\s*", "", line.strip()))
        if re.match(r"^source:\s", bare) or (key and re.sub(r"\W", "", bare) == key):
            continue
        kept.append(line)
    return "\n".join(kept)


def _created(path: Path, meta: dict[str, str]) -> datetime:
    raw = meta.get("created") or ""
    try:
        if raw:
            return datetime.fromisoformat(raw[:19]) if "T" in raw else datetime.combine(date.fromisoformat(raw[:10]), datetime.min.time())
    except ValueError:
        pass
    stat = path.stat()
    return datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime))


def _published(meta: dict[str, str]) -> datetime | None:
    raw = (meta.get("published") or "").strip()
    try:
        return datetime.fromisoformat(raw[:19]) if "T" in raw else datetime.combine(date.fromisoformat(raw[:10]), datetime.min.time())
    except ValueError:
        return None


def date_tokens(day: date) -> tuple[str, ...]:
    return (day.isoformat(), day.strftime("%y-%m-%d"))


def dailies(raw_root: str, day: date) -> list[dict[str, Any]]:
    """Today's newsletter files, found by the date in their file name."""
    root = vault_root(raw_root)
    results = []
    for source in DAILY_SOURCES:
        folder = root / source.folder
        found = None
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() in source.suffixes and source.match in path.name and any(path.name.startswith(t) or t in path.name for t in date_tokens(day)):
                    found = path
                    break
        results.append(
            {
                "key": source.key,
                "label": source.label,
                "path": str(found.relative_to(root)) if found else None,
                "kind": found.suffix.lstrip(".") if found else None,
            }
        )
    return results


def daily_history(raw_root: str, key: str, limit: int = 30) -> list[dict[str, Any]]:
    """Recent issues of one newsletter, newest first — one tab per daily in 进项."""
    source = next((s for s in DAILY_SOURCES if s.key == key), None)
    if source is None:
        raise VaultError(f"没有这份日报：{key}")
    root = vault_root(raw_root)
    folder = root / source.folder
    if not folder.is_dir():
        return []
    # Only dated issues: the folder also holds a README and the tooling's scratch files, and a
    # README listed as if it were an issue is noise in a list 作者 reads every morning.
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in source.suffixes and source.match in p.name and not p.name.startswith(".") and _daily_day(p.name)
    ]
    # Newest first, and a day's second issue (…-晚) above that day's first one — sorting on the
    # raw file name puts them the other way round, because '.' sorts after '-'.
    files.sort(key=lambda p: (_daily_day(p.name) or "", _edition(p.name)), reverse=True)
    return [
        {"key": source.key, "label": source.label, "path": str(p.relative_to(root)),
         "kind": p.suffix.lstrip("."), "title": f"{source.label} · {_daily_day(p.name)}{_edition(p.name)}",
         "day": _daily_day(p.name), "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")}
        for p in files[:limit]
    ]


_DAILY_DAY = re.compile(r"(20\d{2})-(\d{2})-(\d{2})|(\d{2})-(\d{2})-(\d{2})")


def _edition(name: str) -> str:
    """Some days have a second issue (26-09-16-晚.md); without this both rows read the same."""
    tail = _DAILY_DAY.sub("", Path(name).stem, count=1).strip("-_ ")
    return f" {tail}" if tail else ""


def _daily_day(name: str) -> str | None:
    """The issue date from the file name — both 2026-09-20-… and 26-09-20… are in use."""
    m = _DAILY_DAY.search(name)
    if not m:
        return None
    y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else ("20" + m.group(4), m.group(5), m.group(6))
    return f"{y}-{mo}-{d}"


def _item(path: Path, root: Path, source: InboxSource, meta: dict[str, str], body: str,
          created: datetime, modified: datetime, since: datetime) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "source": source.key,
        "source_label": source.label,
        "title": _title(path, meta, body),
        "summary": plain_summary(_card_body(body, _title(path, meta, body))),
        "url": meta.get("source") or meta.get("url") or None,
        "author": str(meta.get("author") or "").strip() or None,
        "created_at": created.isoformat(timespec="minutes"),
        "modified_at": modified.isoformat(timespec="minutes"),
        "is_new": created >= since,
        "chars": len(body),
    }


def inbox(raw_root: str, *, since: datetime, sources: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Notes created or modified since `since`, newest first."""
    root = vault_root(raw_root)
    items = []
    for source in INBOX_SOURCES:
        if sources and source.key not in sources:
            continue
        folder = root / source.folder
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.md"):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            if path.name == SERIES_INDEX:  # 系列的目录（series.py），不是他说的一段话
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = parse_frontmatter(text)
            created = _created(path, meta)
            if source.timeless:
                items.append(_item(path, root, source, meta, body, created, modified, since))
                continue
            if source.passive:
                # The author's publish time is the event; when the file landed is irrelevant.
                published = _published(meta)
                if published is None:
                    continue
                created = modified = published
            if max(created, modified) < since:
                continue
            items.append(_item(path, root, source, meta, body, created, modified, since))
    return sorted(items, key=lambda item: max(item["created_at"], item["modified_at"]), reverse=True)


def read_note(raw_root: str, relative: str) -> dict[str, Any]:
    root = vault_root(raw_root)
    path = safe_path(root, relative)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".html":
        return {"path": relative, "kind": "html", "title": path.stem, "meta": {}, "body": None}
    meta, body = parse_frontmatter(text)
    return {"path": relative, "kind": "md", "title": _title(path, meta, body), "meta": meta, "body": body}


def window_start(days: int, now: datetime | None = None) -> datetime:
    """Start of the window. `days` = 1 is the last 24 hours, on the clock — 作者 asked for
    「1 天」 to mean exactly that, not "since yesterday 00:00" (which is up to 48 h at night).
    Longer windows keep starting at midnight so a "7 天" list does not shift mid-day."""
    now = now or datetime.now()
    if days <= 1:
        return now - timedelta(hours=24)
    return datetime.combine(now.date() - timedelta(days=days), datetime.min.time())
