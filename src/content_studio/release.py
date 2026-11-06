"""成片交付包：final/ 下的视频、封面和发布文案。

工作台原来只认 `final/video.mp4`。Codex 在 9/22 那条视频里交付的是
`final/9月22日-抖音上传版.mp4`、`final/9月22日-封面.jpg`、`final/covers/*.svg|png`
和 `final/发布文案.md`——发布台于是一直说「还没有成片」。

这里只做识别，不改 14 步的判据（Step 14 仍然看 final/video.mp4 + QA + 终审）。
"""
from __future__ import annotations

from pathlib import Path
import re
import struct
from typing import Any

VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
# 老项目的固定位置，优先于猜。
LEGACY_VIDEOS = ("final/video.mp4", "final-video.mp4", "delivery/final-video.mp4")
# 名字里带这些词的更像「要上传的那一个」。顺序即优先级。
VIDEO_HINTS = ("上传版", "上传", "upload", "final", "video")
COVER_HINTS = ("封面", "cover")
# 封面目录里还会放抠像、取帧、拼图这些中间产物，它们不是封面。
COVER_NOISE = ("cutout", "source", "contact", "person", "subject", "frame", "mask")


def _files(folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in suffixes]


def find_video(base: Path) -> str | None:
    """交付的成片，返回相对项目目录的路径。"""
    for rel in LEGACY_VIDEOS:
        if (base / rel).is_file():
            return rel
    candidates = _files(base / "final", VIDEO_SUFFIXES)
    if not candidates:
        return None

    def rank(p: Path) -> tuple[int, int]:
        name = p.name.lower()
        hint = next((i for i, h in enumerate(VIDEO_HINTS) if h in name), len(VIDEO_HINTS))
        # 同样没有提示词时取最大的：代理片、预览片都比母版小。
        return hint, -p.stat().st_size

    return str(min(candidates, key=rank).relative_to(base))


def image_size(path: Path) -> tuple[int, int] | None:
    """不装 Pillow：PNG 读 IHDR，JPEG 扫 SOF 段。读不出就返回 None。"""
    try:
        with path.open("rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head[:2] != b"\xff\xd8":
                return None
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h
                length = struct.unpack(">H", f.read(2))[0]
                f.seek(length - 2, 1)
    except (OSError, struct.error):
        return None


def find_covers(base: Path) -> dict[str, str | None]:
    """横版（宽 > 高）、竖版、公众号（2.35:1）封面各挑一张，返回相对路径。"""
    found = _files(base / "final", IMAGE_SUFFIXES) + _files(base / "final" / "covers", IMAGE_SUFFIXES)
    covers = [
        p for p in found
        if any(h in p.name.lower() for h in COVER_HINTS) and not any(n in p.name.lower() for n in COVER_NOISE)
    ]
    # wide 是 16:9（YouTube、B 站的框，9/29 起封面多出这一张）；landscape 是 4:3
    out: dict[str, str | None] = {"landscape": None, "portrait": None, "wechat": None, "wide": None}
    # 新的在前：改过一版封面，旧的那张不该再被选中。
    for p in sorted(covers, key=lambda p: p.stat().st_mtime, reverse=True):
        size = image_size(p)
        if "公众号" in p.name or (size and size[0] / size[1] >= 2.2):
            kind = "wechat"  # 2.35:1 的公众号封面也是「宽 > 高」，不能被当成横版
        elif "YouTube" in p.name or (size and 1.6 <= size[0] / size[1] < 2.2):
            kind = "wide"
        elif size:
            kind = "landscape" if size[0] > size[1] else "portrait"
        elif "竖" in p.name:
            kind = "portrait"
        else:
            kind = "landscape"
        out[kind] = out[kind] or str(p.relative_to(base))
    return out


def parse_copy(text: str) -> dict[str, Any]:
    """发布文案.md → 标题、备选标题、简介、话题。按二级标题分节，不认识的节忽略。"""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    def block(*names: str) -> str:
        for n in names:
            if n in sections:
                return "\n".join(sections[n]).strip()
        return ""

    title = next((l.strip().lstrip("-*").strip() for l in block("推荐标题", "标题").splitlines() if l.strip()), "")
    alternatives = [l.strip().lstrip("-*0123456789.、").strip() for l in block("备选标题").splitlines() if l.strip()]
    raw_body = block("简介", "正文", "描述")
    tags = re.findall(r"#([^\s#]+)", raw_body)
    body = "\n".join(l for l in raw_body.splitlines() if not re.fullmatch(r"\s*(#[^\s#]+\s*)+", l)).strip()
    return {"title": title, "alternatives": alternatives, "body": body, "tags": tags}


def find_release(base: Path) -> dict[str, Any]:
    copy_path = base / "final" / "发布文案.md"
    copy = parse_copy(copy_path.read_text(encoding="utf-8")) if copy_path.is_file() else None
    return {"video": find_video(base), "covers": find_covers(base), "copy": copy}
