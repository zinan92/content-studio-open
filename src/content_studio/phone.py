"""手机预览：成片压成 540p，放得下就一个文件，放不下再切，每段不超过 28 MB。

成片 130 MB 以上，能直接发给 作者 的文件上限是 30 MB——他出门时没法审片。
这里只在本机出文件到 `final/手机预览/`，不开端口、不上传；怎么送到手机上是另一回事。

先整条压一遍再看实际大小：口播画面变化小，9/22 那条 12 分钟压完才 21 MB，
按码率上限预先切会白白切成四段。放不下时按实际大小等分，每段从原片重压（拷流只能从关键帧切）。
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

FOLDER = "手机预览"
CAP_MB = 28
VIDEO_KBPS = 900   # 码率上限：动效多的段落也不会爆
AUDIO_KBPS = 96
MARGIN = 0.9  # 段与段码率不均，按平均算要留余量
PART = re.compile(r"^(\d{2})_(\d{2})-(\d{2})至(\d{2})-(\d{2})\.mp4$")


class PhonePreviewError(RuntimeError):
    """说给人听的一句话。"""


def plan_segments(duration: float, size_mb: float, *, cap_mb: float | None = None) -> list[tuple[float, float]]:
    """按压好之后的实际大小等分；一段按平均码率算也要留一成余量。"""
    cap_mb = cap_mb or CAP_MB
    if duration <= 0:
        raise PhonePreviewError("成片时长是 0")
    count = 1 if size_mb <= cap_mb else math.ceil(size_mb / (cap_mb * MARGIN))
    step = duration / count
    return [(round(i * step, 3), round(duration if i == count - 1 else (i + 1) * step, 3)) for i in range(count)]


def _mmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60:02d}-{s % 60:02d}"


def part_name(index: int, start: float, end: float) -> str:
    return f"{index:02d}_{_mmss(start)}至{_mmss(end)}.mp4"


def _run(args: list[str], what: str) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        raise PhonePreviewError(f"{what}失败：{(done.stderr or done.stdout).strip()[-200:]}")
    return done.stdout


def _encode(src: Path, dst: Path, what: str, *, start: float | None = None, length: float | None = None) -> None:
    window = ["-ss", str(start)] if start is not None else []
    span = ["-t", str(round(length, 3))] if length is not None else []
    _run([
        "ffmpeg", "-v", "error", "-y", *window, "-i", str(src), *span,
        "-vf", "scale=-2:540", "-c:v", "libx264", "-preset", "medium", "-crf", "26",
        "-maxrate", f"{VIDEO_KBPS}k", "-bufsize", f"{VIDEO_KBPS * 2}k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-movflags", "+faststart", str(dst),
    ], what)


def duration_of(video: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)], "读时长")
    return float(out.strip())


def existing(base: Path, folder: Path | None = None) -> list[dict[str, Any]]:
    """已经生成的分段，按序号排。path 相对项目目录（输出在别处时是绝对路径）。"""
    folder = folder or base / "final" / FOLDER
    if not folder.is_dir():
        return []
    parts = []
    for path in sorted(folder.iterdir()):
        if PART.match(path.name):
            rel = str(path.relative_to(base)) if base in path.parents else str(path)
            parts.append({"name": path.name, "path": rel, "mb": round(path.stat().st_size / 1024 / 1024, 1)})
    return parts


def make_preview(base: Path, video: Path, *, out: Path | None = None) -> list[dict[str, Any]]:
    """出分段到 final/手机预览/。旧的分段先清掉——换了成片，旧预览就是错的。"""
    if not shutil.which("ffmpeg"):
        raise PhonePreviewError("这台机器上没有 ffmpeg")
    from . import icloud

    try:
        icloud.ensure_local(video)
    except icloud.NotLocalError as exc:
        raise PhonePreviewError(str(exc)) from None
    folder = out or base / "final" / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        if PART.match(old.name):
            old.unlink()
    whole = folder / ".压缩中.mp4"
    try:
        _encode(video, whole, "压缩")
        duration = duration_of(whole)
        segments = plan_segments(duration, whole.stat().st_size / 1024 / 1024)
        if len(segments) == 1:
            whole.rename(folder / part_name(1, 0, duration))
        else:
            # 放不下才切。从原片按段重压：拷流只能从关键帧切，段会重叠、变大。
            for i, (start, end) in enumerate(segments, 1):
                target = folder / part_name(i, start, end)
                _encode(video, target, f"第 {i} 段", start=start, length=end - start)
                mb = target.stat().st_size / 1024 / 1024
                if mb > CAP_MB:
                    raise PhonePreviewError(f"第 {i} 段 {mb:.1f} MB，超过 {CAP_MB} MB")
    finally:
        whole.unlink(missing_ok=True)
    return existing(base, folder)
