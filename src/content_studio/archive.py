"""作品库：自己发过的每条抖音视频一个文件夹，成片、中间产物、原始录像都在里面。

作者：视频本身应该存在本地；大部分原片本机本来就有，按时长和大致日期就能认出哪条是哪条。
作品库的结构（作者 定的）：

    作品库/
      00 总表.md
      originals.json              每条抖音视频 → 它的文件夹和成片（工作台读这个）
      2026-09-24 某某标题/            发布日期 + 抖音标题第一句
        info.md                   抖音链接、时长、每个文件从哪来
        1 成片/                    2026-09-24 某某标题.mp4（原片）
                                  2026-09-24 某某标题 抖音下载版.mp4（从抖音下的，码率低）
        2 中间产物/                项目文件夹原样放；单个文件叫「文件夹名 <N>秒版.ext」
        3 原始录像/                录制日期 + 录像标题，比如 2026-09-12 打造个人知识库….mp4
      _未发布/  _待确认/

命名规则（作者 9/27 定的）：文件夹和文件都是「日期 名字」，后缀只有「抖音下载版」和
「<N>秒版」两种，不让名字各写各的。成片是不是抖音下载的，看 originals.json 的 source，
不靠文件名猜。

同步发现新视频时：
1. 先在本机按时长找原片（差 1.5 秒以内、文件日期在发布前后 30 天内），找到就硬链接进
   「1 成片」——同一块盘上不占双倍空间，原位置照样能用。一个文件只给一条视频：它离谁的
   时长最近就是谁的，已经当过成片的（包括别处的同一份拷贝）不再给别人。从抖音下回来的
   文件（路径里有抖音作品号、或者旁边有 content_item.json）不算原片。只有抖音下载版的
   视频，本机出现原片时也会换上原片；
2. 找不到就标「缺」。作者 的原片不在这台电脑就在另一台电脑（不然他怎么传到抖音的），
   所以默认不从抖音下：9/26 实测抖音下载会截断、会下成别的视频、还会撞 403 风控。
   从抖音下（存成「1 成片/抖音下载版.mp4」）只在显式传 download=True 时才做，一次一条、
   有超时，时长对不上就删掉报错。

作品库通常在外接硬盘上。硬盘没插的时候整件事跳过，不往内部硬盘写。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable

DownloadFn = Callable[[str, Path, Path], Any]
ProbeFn = Callable[[Path], "float | None"]
DEFAULT_DELAY_SECONDS = 20
DOWNLOAD_TIMEOUT_SECONDS = 900
MATCH_SECONDS = 1.5
DOWNLOAD_TOLERANCE_SECONDS = 3.0
DATE_WINDOW_DAYS = 30
INDEX_FILE = "originals.json"
SCAN_CACHE = ".local-scan.json"
FINAL_DIR = "1 成片"
DOWNLOAD_SUFFIX = "抖音下载版"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv"}
FINAL_HINTS = re.compile(r"上传版|剪映导出|抖音视频|final|成片|导出", re.IGNORECASE)
MIN_BYTES = 3 * 1024 * 1024
AWEME_ID = re.compile(r"^\d{19}$")
DOWNLOADER_SIDECARS = ("content_item.json", "metadata.json")
SKIP_DIRS = {"node_modules", "__pycache__"}


def usable_root(raw: str | None) -> Path | None:
    """The library folder, or None when it is not configured or its disk is not there."""
    if not raw:
        return None
    root = Path(raw).expanduser()
    if root.is_dir():
        return root
    parts = root.parts
    if len(parts) > 2 and parts[1] == "Volumes":
        # 外接盘：盘挂着才建目录。没插的时候 /Volumes/<盘名> 不在，别在那儿凭空建一个。
        if not Path(*parts[:3]).is_dir():
            return None
    elif not root.parent.is_dir():
        return None
    root.mkdir(parents=True, exist_ok=True)
    return root


# -- index -------------------------------------------------------------------------

def read_index(root: Path | None) -> dict[str, dict[str, Any]]:
    if root is None:
        return {}
    try:
        return json.loads((root / INDEX_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_index(root: Path, index: dict[str, dict[str, Any]]) -> None:
    tmp = root / (INDEX_FILE + ".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(root / INDEX_FILE)


def video_file(root: Path | None, video_id: str) -> Path | None:
    """This video's final: what the index points at, else anything in its 「1 成片」 folder."""
    entry = read_index(root).get(video_id) if root is not None else None
    if not entry:
        return None
    if entry.get("path") and Path(entry["path"]).is_file():
        return Path(entry["path"])
    folder = Path(entry.get("folder") or "") / FINAL_DIR
    if folder.is_dir():
        files = sorted((p for p in folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES),
                       key=lambda p: (is_download(p), -p.stat().st_size))
        return files[0] if files else None
    return None


def is_download(path: Path) -> bool:
    return path.stem.endswith(DOWNLOAD_SUFFIX)


def final_name(folder: Path, suffix: str) -> str:
    """原片：和文件夹同名。"""
    return f"{folder.name}{suffix.lower()}"


def download_name(folder: Path) -> str:
    return f"{folder.name} {DOWNLOAD_SUFFIX}.mp4"


def source_of(root: Path | None, video_id: str) -> str | None:
    f = video_file(root, video_id)
    if f is None:
        return None
    entry = read_index(root).get(video_id) or {}
    if entry.get("source") in ("local", "douyin") and entry.get("path") == str(f):
        return entry["source"]
    return "douyin" if is_download(f) else "local"


def pending(videos: list[dict[str, Any]], root: Path | None) -> list[dict[str, Any]]:
    """Own videos (not image posts) with no final yet, newest first."""
    if root is None:
        return []
    own = [v for v in videos if not v.get("is_image_post")]
    own.sort(key=lambda v: v.get("published_at") or "", reverse=True)
    return [v for v in own if video_file(root, v["video_id"]) is None]


BEIJING = timezone(timedelta(hours=8))


def publish_day(video: dict[str, Any]) -> str:
    """发布日期按北京时间：库里存的是 UTC，凌晨发的会差一天（9/12 00:01 发的 FDE 被记成 9/11）。"""
    raw = str(video.get("published_at") or "")
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return raw[:10]
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(BEIJING).date().isoformat()


def folder_name(video: dict[str, Any]) -> str:
    from .backfill import split_douyin_title

    title = split_douyin_title(video.get("title") or "")["title"] or video["video_id"]
    title = "".join(c for c in title if c not in '/:\\?*"<>|').strip()[:40]
    return f"{publish_day(video)} {title}".strip()


def video_folder(root: Path, video: dict[str, Any], index: dict[str, dict[str, Any]]) -> Path:
    entry = index.get(video["video_id"])
    if entry and entry.get("folder"):
        return Path(entry["folder"])
    return root / folder_name(video)


def write_info(folder: Path, video: dict[str, Any], note: str) -> None:
    info = folder / "info.md"
    if info.exists():
        with info.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- {datetime.now().date()}：{note}\n")
        return
    info.write_text(
        f"# {folder.name[11:] or video['video_id']}\n\n- 抖音发布：{str(video.get('published_at') or '')[:10]}\n"
        f"- 抖音时长：{video.get('duration_seconds') or 0:.1f} 秒\n- 抖音链接：https://www.douyin.com/video/{video['video_id']}\n\n"
        f"## 这里的文件从哪来\n\n- {datetime.now().date()}：{note}\n", encoding="utf-8")


# -- step 1: the original on this machine ---------------------------------------------

def ffprobe_duration(path: Path) -> float | None:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip()) if r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def douyin_id_of(path: Path) -> str | None:
    """A file that came from a Douyin download: the aweme id in its path, or "?" when only the
    downloader's sidecar files give it away. None for everything else."""
    for part in reversed(path.parts[:-1]):
        if AWEME_ID.match(part):
            return part
    for folder in (path.parent, path.parent.parent):
        if any((folder / name).is_file() for name in DOWNLOADER_SIDECARS):
            return "?"
    return None


def scan_local(dirs: list[Path], *, root: Path, probe: ProbeFn = ffprobe_duration) -> list[dict[str, Any]]:
    """Every video under the search folders (outside the library) with its duration, cached.
    Copies of a Douyin download elsewhere (same size and length) are marked as downloads too."""
    cache_path = root / SCAN_CACHE
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    out, fresh = [], {}
    root_r = root.resolve()
    for base in dirs:
        base = base.expanduser()
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
            folder = Path(dirpath)
            try:
                if folder.resolve() == root_r or root_r in folder.resolve().parents:
                    dirnames[:] = []
                    continue
            except OSError:
                continue
            for name in filenames:
                p = folder / name
                if name.startswith(".") or p.suffix.lower() not in VIDEO_SUFFIXES:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size < MIN_BYTES:
                    continue
                key = f"{p}|{st.st_size}|{int(st.st_mtime)}"
                dur = cache[key] if key in cache else probe(p)
                fresh[key] = dur
                if dur:
                    out.append({"path": str(p), "dur": dur, "size": st.st_size, "mtime": st.st_mtime, "douyin": douyin_id_of(p)})
    try:
        cache_path.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    downloads = {(f["size"], round(f["dur"], 2)): f["douyin"] for f in out if f["douyin"]}
    for f in out:
        f["douyin"] = f["douyin"] or downloads.get((f["size"], round(f["dur"], 2)))
    return out


def _published(video: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(publish_day(video))
    except ValueError:
        return None


def _fits(video: dict[str, Any], f: dict[str, Any], seconds: float = MATCH_SECONDS) -> float | None:
    """How far this file's length is from the video's, or None when it cannot be this video."""
    dur = video.get("duration_seconds")
    if not dur:
        return None
    diff = abs(f["dur"] - dur)
    if diff > seconds:
        return None
    published = _published(video)
    if published is not None and abs((datetime.fromtimestamp(f["mtime"]).date() - published).days) > DATE_WINDOW_DAYS:
        return None
    return diff


def match_local(video: dict[str, Any], files: list[dict[str, Any]], *, rivals: list[dict[str, Any]] | None = None,
                taken: set[int] | None = None) -> dict[str, Any] | None:
    """The best local original for one video. A file only counts when this video is the one its
    length is closest to (among `rivals`, the other own videos) and nobody has it yet (`taken`:
    sizes of files already used as a final, so a copy elsewhere is the same file). Douyin
    downloads never count as originals."""
    hits = []
    for f in files:
        if f.get("douyin") or (taken and f["size"] in taken):
            continue
        diff = _fits(video, f)
        if diff is None:
            continue
        if any(r["video_id"] != video["video_id"] and (d := _fits(r, f)) is not None and d < diff for r in rivals or []):
            continue
        hits.append((0 if FINAL_HINTS.search(f["path"]) else 1, -(f["size"] / max(f["dur"], 1)), diff, f))
    if not hits:
        return None
    hits.sort(key=lambda h: h[:3])
    best = hits[0][3]
    return {"path": best["path"], "size": best["size"], "dur": best["dur"], "diff": round(hits[0][2], 2), "candidates": len(hits)}


def match_download(video: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A Douyin download of this very video that is already on disk somewhere."""
    for f in files:
        if f.get("douyin") == video["video_id"] and _fits(video, f, DOWNLOAD_TOLERANCE_SECONDS) is not None:
            return f
    return None


def link_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    try:
        os.link(src, dest)  # same disk: one file, two names
    except OSError:
        shutil.copy2(src, dest)


# -- step 2: download from Douyin ------------------------------------------------------

def douyin_download(url: str, cookies: Path, out: Path, timeout: int = DOWNLOAD_TIMEOUT_SECONDS) -> None:
    from .deps import subprocess_env

    try:
        done = subprocess.run([sys.executable, "-m", "content_downloader", "download", url, "--cookies", str(cookies), "--output-dir", str(out)],
                              capture_output=True, text=True, env=subprocess_env(), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"下载超过 {timeout // 60} 分钟没完成，停了") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(f"下载失败（退出码 {done.returncode}）{('：' + tail[-1][:160]) if tail else ''}")


def fetch(video: dict[str, Any], *, root: Path, cookie_path: Path, index: dict[str, dict[str, Any]],
             download_fn: DownloadFn | None = None, probe: ProbeFn = ffprobe_duration) -> Path:
    vid = video["video_id"]
    tmp = root / ".downloading" / vid
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        (download_fn or douyin_download)(f"https://www.douyin.com/video/{vid}", cookie_path, tmp)
        found = sorted(tmp.rglob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
        if not found:
            raise RuntimeError("下载完了，但没找到视频文件")
        want = video.get("duration_seconds")
        got = probe(found[0])
        if want and (got is None or abs(got - want) > DOWNLOAD_TOLERANCE_SECONDS):
            raise RuntimeError(f"下回来的只有 {round(got or 0)} 秒，抖音上是 {round(want)} 秒，不是完整视频")
        folder = video_folder(root, video, index)
        dest = folder / FINAL_DIR / download_name(folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(found[0]), dest)
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # a half file must never count as archived


def archive_pending(videos: list[dict[str, Any]], *, root: Path | None, cookie_path: Path, search: list[Path] | None = None,
                    limit: int | None = None, delay: float = DEFAULT_DELAY_SECONDS, download_fn: DownloadFn | None = None,
                    download: bool = False, only: set[str] | None = None,
                    probe: ProbeFn = ffprobe_duration, on_progress: Callable[[dict[str, Any]], None] | None = None,
                    sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Local originals first; download only the rest, one at a time. A failed download is
    recorded and skipped; two failures in a row stop the run (it looks like risk control).
    `videos` is every own video (who a file belongs to depends on all of them); `only` limits
    which ones this run fills in."""
    result: dict[str, Any] = {"root": str(root) if root else None, "local": [], "done": [], "failed": []}
    if root is None:
        result["skipped"] = "作品库没配置，或者那块硬盘没插"
        return result
    own = [v for v in videos if not v.get("is_image_post")]
    todo = pending(videos, root)
    index = read_index(root)
    upgrades = [v for v in own if v not in todo and source_of(root, v["video_id"]) == "douyin"]
    if only is not None:
        todo = [v for v in todo if v["video_id"] in only]
        upgrades = [v for v in upgrades if v["video_id"] in only]
    result["upgraded"] = []
    if search and (todo or upgrades):
        if on_progress:
            on_progress({"state": "scanning", "total": len(todo)})
        files = scan_local(search, root=root, probe=probe)
        taken = {f.stat().st_size for vid in index if (f := video_file(root, vid)) is not None}
        for v in todo + upgrades:
            hit = match_local(v, files, rivals=own, taken=taken)
            if not hit:
                continue
            taken.add(hit["size"])
            folder = video_folder(root, v, index)
            src = Path(hit["path"])
            dest = folder / FINAL_DIR / final_name(folder, src.suffix)
            if dest.exists() and not os.path.samefile(dest, src):
                dest = dest.with_name(f"{folder.name} {round(hit['dur'])}秒版{src.suffix.lower()}")
            link_or_copy(src, dest)
            index[v["video_id"]] = {"folder": str(folder), "path": str(dest), "source": "local"}
            if v in upgrades:
                write_info(folder, v, f"成片：换成原片 {hit['path']}（时长差 {hit['diff']} 秒）；抖音下载版留着当备份")
                result["upgraded"].append(v["video_id"])
            else:
                write_info(folder, v, f"成片：本机原片 {hit['path']}（时长差 {hit['diff']} 秒，{hit['candidates']} 个候选里挑的）")
                result["local"].append(v["video_id"])
        for v in todo:
            if v["video_id"] in result["local"]:
                continue
            got = match_download(v, files)
            if got is None:
                continue
            folder = video_folder(root, v, index)
            dest = folder / FINAL_DIR / download_name(folder)
            link_or_copy(Path(got["path"]), dest)
            index[v["video_id"]] = {"folder": str(folder), "path": str(dest), "source": "douyin"}
            write_info(folder, v, f"成片：抖音下载版 {got['path']}（本机已有的抖音下载，码率低于原片）")
            result["local"].append(v["video_id"])
        write_index(root, index)
        todo = [v for v in todo if v["video_id"] not in result["local"]]
    if not download:
        result["missing"] = [v["video_id"] for v in todo]
        todo = []
    if limit is not None:
        todo = todo[:limit]
    result["todo"] = len(todo)
    streak = 0
    for i, v in enumerate(todo):
        if on_progress:
            on_progress({"state": "downloading", "video_id": v["video_id"], "index": i + 1, "total": len(todo),
                         "done": len(result["done"]), "local": len(result["local"])})
        try:
            dest = fetch(v, root=root, cookie_path=cookie_path, index=index, download_fn=download_fn, probe=probe)
            index[v["video_id"]] = {"folder": str(dest.parent.parent), "path": str(dest), "source": "douyin"}
            write_index(root, index)
            write_info(dest.parent.parent, v, "成片：从抖音下的备份（码率低于原片）")
            result["done"].append(v["video_id"])
            streak = 0
        except Exception as exc:  # noqa: BLE001 - recorded, shown on the queue
            result["failed"].append({"video_id": v["video_id"], "error": str(exc)[:200] or type(exc).__name__})
            streak += 1
            if streak >= 2:
                result["stopped"] = "连着两条下载失败，可能是抖音风控，先停"
                break
        if i + 1 < len(todo):
            sleep(delay)
    if on_progress:
        on_progress({"state": "stopped" if result.get("stopped") else "done", "done": len(result["done"]), "local": len(result["local"]),
                     "failed": result["failed"], "total": len(todo), "stopped": result.get("stopped")})
    return result
