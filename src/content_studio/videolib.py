"""本机新出的视频归档到 SSD 上的视频库（`视频/`），按内容分好类。

剪辑工程本来就写在 SSD（`视频/exports`），散在本机的是宣传片成品、会议录像、下载的咨询录音。
以前本机快满就整批搬进 `Mac-offload/Videos-日期/`，按「哪天满了」分、照抄本机路径，找不到东西。
这里按 `视频/00 命名规范.md` 落进分类文件夹，「YYYY-MM-DD 名字」（10/7 作者 定了三类）：

- `宣传片/`：产品宣传片、流水线演示
- `录音与会议/`：腾讯会议录像、咨询录音
- `_收件箱/`：认不出来的，看一眼再挪

只在 SSD 真插着时跑：库根目录要在挂载的卷上、里面有 `00 命名规范.md`，否则 mkdir 会在本机建个假目录。
先复制、SHA-256 核对、才删本机原件；每一步追加写 `视频/.归档记录.jsonl`。库里已有同内容的不再复制。
不碰：工作台自己读的 `~/.config/content-studio`、剪映草稿、各 App 的 Library、已经是链接的文件、
工程文件夹（有 package.json / .git 的，要搬得整个搬，单独确认）。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Iterable

MARKER = "00 命名规范.md"
MANIFEST = ".归档记录.jsonl"
PROMO, TALK, INBOX = "宣传片", "录音与会议", "_收件箱"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
AUDIO_EXT = {".m4a", ".wav", ".mp3", ".aac"}
MIN_BYTES = 1 << 20  # 1 MB 以下的是音效、占位文件，不值得搬
MIN_AGE_MINUTES = 30  # 半小时内改过的可能还在录、还在导出
SKIP_DIRS = {"node_modules", ".git", "JianyingPro", "TV", "Music", "__pycache__"}
SKIP_SUFFIXES = (".app", ".photoslibrary", ".fcpbundle", ".imovielibrary", ".tvlibrary", ".lvpro")
PROJECT_FILES = ("package.json", ".git", "pyproject.toml", "remotion.config.ts")
SF_DATALESS = 0x40000000  # iCloud 只留了个壳，读它会去下载
PROMO_WORDS = re.compile(r"宣传片|宣传|promo|流水线|trailer", re.I)
TALK_WORDS = re.compile(r"会议|咨询|录音|访谈|meeting|\bzoom\b|\bcall\b", re.I)
LEAD_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ _T-]*\d{2}[.:]\d{2}(?:[.:]\d{2})?)?[\s_-]*")
INNER_DATE = re.compile(r"(?<!\d)(20\d{2})-?(\d{2})-?(\d{2})(?!\d)")


class VideoLibError(RuntimeError):
    """说给人听的一句话。"""


@dataclass(frozen=True)
class Source:
    """本机一处会冒出视频的地方。

    whole=True：这一处整个是一个作品的产出（比如 Remotion 工程的 out/），所有文件进同一个文件夹，名字取工程名。
    whole=False：杂物堆（下载、影片）——直接放着的文件一个一个归；第一层子文件夹一个归一组。
    """

    pattern: str
    category: str | None = None
    whole: bool = False


DEFAULT_SOURCES = (
    Source("~/Movies"),
    Source("~/Downloads"),
    Source("~/Desktop"),
    Source("~/Documents/TencentMeeting", TALK),
    Source("~/work/*promo*/out", PROMO, whole=True),
)


@dataclass
class Move:
    source: Path
    dest: Path  # 库里的相对路径
    size: int
    root: Path  # 本机这一处的根：搬空的子目录往上删到它为止，它自己不删
    duplicate_of: Path | None = None  # 库里已有同内容的文件（相对路径）：不复制，只删本机这份


# -- 库在不在 -------------------------------------------------------------------

def library_from(projects_root: str | Path | None) -> Path | None:
    """工作台的 video_projects_root 是 `视频/exports`，视频库是它上一层。"""
    if not projects_root:
        return None
    root = Path(str(projects_root)).expanduser()
    return root.parent if root.name == "exports" else root


def check_library(library: Path) -> Path:
    """确认库真在一块插着的盘上。没插时 /Volumes/<名字> 不是挂载点，往里 mkdir 会写进本机。"""
    library = library.expanduser()
    if not (library / MARKER).is_file():
        raise VideoLibError(f"{library} 里没有「{MARKER}」——视频库那块 SSD 没插，或者路径不对")
    parts = library.resolve().parts
    if len(parts) >= 3 and parts[1] == "Volumes" and not os.path.ismount(os.path.join("/", parts[1], parts[2])):
        raise VideoLibError(f"/Volumes/{parts[2]} 没挂载（SSD 没插？），不往里写")
    return library


# -- 认文件 ---------------------------------------------------------------------

def category_of(text: str, suffix: str) -> str:
    if PROMO_WORDS.search(text):
        return PROMO
    if TALK_WORDS.search(text) or suffix.lower() in AUDIO_EXT:
        return TALK
    return INBOX


def dated_name(name: str, fallback: float) -> str:
    """「YYYY-MM-DD 名字」：名字开头的日期（可带时分秒）拿出来当日期；名字里夹着 20261004 也认；都没有用文件时间。"""
    lead = LEAD_DATE.match(name)
    if lead:
        rest = name[lead.end():].strip() or name
        return f"{lead.group(1)}-{lead.group(2)}-{lead.group(3)} {rest}"
    inner = INNER_DATE.search(name)
    if inner and 1 <= int(inner.group(2)) <= 12 and 1 <= int(inner.group(3)) <= 31:
        return f"{inner.group(1)}-{inner.group(2)}-{inner.group(3)} {name}"
    return f"{datetime.fromtimestamp(fallback):%Y-%m-%d} {name}"


def _is_media(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXT | AUDIO_EXT


def _skip_dir(path: Path) -> bool:
    return path.name.startswith(".") or path.name in SKIP_DIRS or path.name.endswith(SKIP_SUFFIXES)


def _is_project(path: Path) -> bool:
    return any((path / name).exists() for name in PROJECT_FILES)


def _walk(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _skip_dir(Path(dirpath) / d)]
        for name in filenames:
            if not name.startswith("."):
                yield Path(dirpath) / name


def expand(sources: Iterable[Source], home: Path) -> list[tuple[Source, Path]]:
    found: list[tuple[Source, Path]] = []
    for src in sources:
        pattern = src.pattern.replace("~", str(home), 1) if src.pattern.startswith("~") else src.pattern
        anchor = Path(pattern)
        if any(ch in pattern for ch in "*?["):
            base = Path(anchor.anchor)
            rel = str(anchor.relative_to(base))
            found += [(src, p) for p in sorted(base.glob(rel)) if p.is_dir() and not p.is_symlink()]
        elif anchor.is_dir() and not anchor.is_symlink():
            found.append((src, anchor))
    return found


def _groups(src: Source, root: Path, skipped: list[tuple[Path, str]]) -> list[tuple[str, list[Path], Path | None]]:
    """[(组名, 文件, 组目录)]：组目录为 None 的是散文件，一个文件一组。"""
    if src.whole:
        name = root.parent.name if root.name in {"out", "exports", "renders", "output"} else root.name
        return [(name, list(_walk(root)), root)]
    groups: list[tuple[str, list[Path], Path | None]] = []
    for child in sorted(root.iterdir()):
        if child.is_symlink():
            continue
        if child.is_dir():
            if _skip_dir(child):
                continue
            if _is_project(child):
                if any(_is_media(p) for p in _walk(child)):
                    skipped.append((child, "工程文件夹，要搬得整个搬，单独确认"))
                continue
            groups.append((child.name, list(_walk(child)), child))
        elif child.is_file():
            groups.append((child.stem, [child], None))
    return groups


def plan(
    library: Path,
    sources: Iterable[Source] = DEFAULT_SOURCES,
    *,
    home: Path | None = None,
    now: float | None = None,
    min_age_minutes: float = MIN_AGE_MINUTES,
    open_files: Callable[[list[Path]], set[Path]] | None = None,
) -> tuple[list[Move], list[tuple[Path, str]]]:
    """列出要搬的（不动任何文件）和跳过的（带原因）。"""
    home = home or Path.home()
    now = time.time() if now is None else now
    library = library.resolve()
    moves: list[Move] = []
    skipped: list[tuple[Path, str]] = []
    taken: set[Path] = set()
    for src, root in expand(sources, home):
        if root.resolve().is_relative_to(library):
            continue
        for group, files, group_dir in _groups(src, root, skipped):
            media: list[tuple[Path, os.stat_result]] = []
            for path in files:
                if not _is_media(path) or path.is_symlink():
                    continue
                st = path.stat()
                if getattr(st, "st_flags", 0) & SF_DATALESS:
                    skipped.append((path, "还在 iCloud 上没下载到本机"))
                elif st.st_size < MIN_BYTES:
                    continue
                elif now - st.st_mtime < min_age_minutes * 60:
                    skipped.append((path, f"{min_age_minutes:g} 分钟内改过，可能还在录或导出"))
                else:
                    media.append((path, st))
            if not media:
                continue
            first = min(st.st_mtime for _, st in media)
            for path, st in media:
                cat = src.category or category_of(f"{group} {path.name}", path.suffix)
                if group_dir is None:
                    dest = Path(cat) / f"{dated_name(group, st.st_mtime)}{path.suffix}"
                else:
                    dest = Path(cat) / dated_name(group, first) / path.relative_to(group_dir)
                dest = _free_name(library, dest, taken)
                taken.add(dest)
                moves.append(Move(path, dest, st.st_size, root))
    busy = {p.resolve() for p in (open_files or lsof_open)([m.source for m in moves])}
    if busy:
        skipped += [(m.source, "有程序正开着") for m in moves if m.source.resolve() in busy]
        moves = [m for m in moves if m.source.resolve() not in busy]
    _mark_duplicates(library, moves)
    return moves, skipped


def _free_name(library: Path, dest: Path, taken: set[Path]) -> Path:
    """库里、这一趟里同名的都不覆盖：后面加「 2」「 3」。同内容的靠 _mark_duplicates 按哈希认，跟名字无关。"""
    candidate, n = dest, 2
    while candidate in taken or (library / candidate).exists():
        candidate = dest.with_name(f"{dest.stem} {n}{dest.suffix}")
        n += 1
    return candidate


def _mark_duplicates(library: Path, moves: list[Move]) -> None:
    """库里已有同内容的（按大小筛、SHA-256 定）：只删本机这份。只比 `视频/` 里的，不翻 Mac-offload。"""
    sizes = {m.size for m in moves}
    if not sizes:
        return
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in _walk(library):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size in sizes and _is_media(path):
            by_size[size].append(path)
    digests: dict[Path, str] = {}

    def digest(path: Path) -> str:
        if path not in digests:
            digests[path] = sha256(path)
        return digests[path]

    for move in moves:
        same = by_size.get(move.size, [])
        if same:
            mine = digest(move.source)
            hit = next((p for p in same if digest(p) == mine), None)
            if hit:
                move.duplicate_of = hit.relative_to(library)


def lsof_open(paths: list[Path]) -> set[Path]:
    if not paths or not shutil.which("lsof"):
        return set()
    done = subprocess.run(["lsof", "-F", "n", "--", *map(str, paths)], capture_output=True, text=True, timeout=60)
    return {Path(line[1:]) for line in done.stdout.splitlines() if line.startswith("n")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


# -- 真搬 -----------------------------------------------------------------------

def apply(library: Path, moves: list[Move], *, log: Callable[[str], None] = print) -> dict[str, Any]:
    """复制 → 核对 → 删本机原件。一个文件出错只停这一个，其余照搬；记录追加进 `.归档记录.jsonl`。"""
    library = check_library(library)
    need = sum(m.size for m in moves if not m.duplicate_of)
    free = shutil.disk_usage(library).free
    if need > free - (2 << 30):
        raise VideoLibError(f"SSD 只剩 {_gb(free)}，要搬 {_gb(need)}，先腾地方")
    done = {"moved": 0, "duplicate": 0, "failed": 0, "bytes": 0}
    with (library / MANIFEST).open("a", encoding="utf-8") as manifest:
        for move in moves:
            try:
                record = _move_one(library, move)
            except (OSError, VideoLibError) as exc:
                done["failed"] += 1
                log(f"  没搬：{move.source}（{exc}）")
                continue
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()
            done[record["action"]] += 1
            done["bytes"] += move.size if record["action"] == "moved" else 0
            _prune_empty(move.source.parent, move.root)
    return done


def _move_one(library: Path, move: Move) -> dict[str, Any]:
    digest = sha256(move.source)
    base = {"time": datetime.now().isoformat(timespec="seconds"), "source": str(move.source), "bytes": move.size, "sha256": digest}
    if move.duplicate_of:
        if sha256(library / move.duplicate_of) != digest:
            raise VideoLibError("库里那份内容变了，这次不删")
        move.source.unlink()
        return {**base, "action": "duplicate", "dest": str(move.duplicate_of)}
    target = library / move.dest
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise VideoLibError(f"{move.dest} 已经有了")
    partial = target.with_name(target.name + ".copying")
    shutil.copy2(move.source, partial)
    if sha256(partial) != digest:
        partial.unlink()
        raise VideoLibError("复制完核对不上，本机原件没动")
    partial.rename(target)
    move.source.unlink()
    return {**base, "action": "moved", "dest": str(move.dest)}


def _prune_empty(folder: Path, root: Path) -> None:
    """搬空的子目录往上删到本机那一处的根为止（根不删）；只剩 .DS_Store 也算空。"""
    while folder != root and folder.is_relative_to(root):
        try:
            if any(p.name != ".DS_Store" for p in folder.iterdir()):
                return
            (folder / ".DS_Store").unlink(missing_ok=True)
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


# -- 给人看 ---------------------------------------------------------------------

def _gb(n: float) -> str:
    return f"{n / (1 << 30):.1f} GB" if n >= 1 << 30 else f"{n / (1 << 20):.0f} MB"


def _home(path: Path, home: Path) -> str:
    text = str(path)
    return "~" + text[len(str(home)):] if text.startswith(str(home)) else text


def describe(library: Path, moves: list[Move], skipped: list[tuple[Path, str]], *, home: Path | None = None) -> list[str]:
    home = home or Path.home()
    lines = [f"视频库：{library}"]
    copy = [m for m in moves if not m.duplicate_of]
    dup = [m for m in moves if m.duplicate_of]
    if copy:
        lines.append(f"要搬 {len(copy)} 个文件，共 {_gb(sum(m.size for m in copy))}：")
        folders: dict[str, list[Move]] = defaultdict(list)
        for m in copy:
            key = f"{Path(*m.dest.parts[:2])}/" if len(m.dest.parts) > 2 else str(m.dest)
            folders[key].append(m)
        for dest, items in sorted(folders.items()):
            where = _home(Path(os.path.commonpath([i.source.parent for i in items])), home)
            lines.append(f"  {dest}  ← {where}（{len(items)} 个，{_gb(sum(i.size for i in items))}）")
    if dup:
        lines.append(f"库里已经有同内容的 {len(dup)} 个（不复制，只删本机这份）：")
        lines += [f"  {_home(m.source, home)}  = {m.duplicate_of}" for m in dup]
    if skipped:
        lines.append(f"跳过 {len(skipped)} 个：")
        lines += [f"  {_home(p, home)} —— {why}" for p, why in skipped]
    if not moves and not skipped:
        lines.append("本机没有要归档的视频。")
    return lines
