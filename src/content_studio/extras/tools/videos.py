"""视频样片（10/16 作者：用三个开源仓库各做几条放进单点功能页）。

清单 videos.json 进仓库；成片是生成出来的大文件，放本机 ~/.config/content-studio/tool-videos/<id>.mp4 和 <id>.webp（封面），
不进仓库（同风格样图，#623）。预览时可以用 CONTENT_STUDIO_TOOL_VIDEOS 指到别的文件夹。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ...paths import config_dir

HERE = Path(__file__).resolve().parent
KINDS = ("mp4", "webp")


def videos_dir() -> Path:
    return Path(os.environ.get("CONTENT_STUDIO_TOOL_VIDEOS") or config_dir() / "tool-videos")


def manifest() -> dict[str, Any]:
    return json.loads((HERE / "videos.json").read_text(encoding="utf-8"))


def files() -> list[str]:
    """清单里每一条要的文件名：<id>.mp4 和 <id>.webp。"""
    return [f"{item['id']}.{kind}" for group in manifest()["groups"] for item in group["items"] for kind in KINDS]


def missing() -> list[str]:
    folder = videos_dir()
    return [name for name in files() if not (folder / name).is_file()]
