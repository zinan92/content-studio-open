"""流量视频：作者 看到就想转、想复刻的单条视频，先存下来。

9/30 作者：「我可能会把一些看起来就愿意转发、点赞、收藏的视频放进来……不一定是我的对标账号，但我想先复刻它。」
和对标雷达不一样：那边按账号盯，这里按单条存，多半是纯 AIGC 的成品。

- 存的时候就下载：他要的是视频本身（每段几秒、画面是什么），而且这类视频常被删，链接会失效。
- 抖音的链接用他的登录下，所以一天最多 DOUYIN_DAILY_CAP 条（9/29 他最担心主号被限流）；
  X、小红书不走抖音登录，没有这个上限。
- 文件放在 data/swipe/ 下，不和拆解的下载混在一起——拆解转完文字会删视频省空间，这里的视频要留着看。
- 「开始复刻」才建选题、放进「接下来要拍的」：是他点的，不自动加。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from .deps import subprocess_env

DOUYIN_DAILY_CAP = 5
PLATFORMS = (
    ("douyin", "抖音", re.compile(r"(douyin\.com|iesdouyin\.com)")),
    ("x", "X", re.compile(r"(//|\.)(x|twitter)\.com/")),
    ("xiaohongshu", "小红书", re.compile(r"(xiaohongshu\.com|xhslink\.com)")),
)
LABELS = {k: label for k, label, _ in PLATFORMS}
# 存的时候要过的那一关：换成我的，归哪个合集（9/30 定的四类），还是只图流量
COLLECTIONS = ("老板的 AI 早报", "这个 AI 能替谁", "一个人加 AI 做成的", "AI 时代的钱", "只是流量")


class SwipeError(RuntimeError):
    """说给人听的一句话。"""


def clean_url(raw: str) -> tuple[str, str]:
    """从粘贴的文字里取出链接，认出是哪个平台。"""
    match = re.search(r"https?://\S+", raw or "")
    url = (match.group(0) if match else (raw or "")).strip().rstrip("，。,")
    if not url:
        raise SwipeError("贴一个视频链接")
    for key, _label, pattern in PLATFORMS:
        if pattern.search(url):
            if key == "douyin":
                # 在主页、搜索、推荐里点开的视频，地址是「那一页 + modal_id=视频号」。照原样交给下载工具，
                # 它会当成整个账号主页（9/30 作者 贴的两条就是这样，什么都没下）。一律换成单条视频的地址。
                vid = re.search(r"/video/(\d{8,})", url) or re.search(r"[?&]modal_id=(\d{8,})", url)
                if vid:
                    return f"https://www.douyin.com/video/{vid.group(1)}", key
                if "/user/" in url:
                    raise SwipeError("这是账号主页。流量视频存的是单条视频；想盯这个号去「对标雷达」")
            return url, key
    raise SwipeError("现在认得的是抖音、X、小红书的视频链接")


def download(url: str, platform: str, *, out_dir: Path, cookies: Path | None) -> Path:
    """下到 out_dir，返回这条内容的文件夹（里面有 content_item.json、media/）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p.parent for p in out_dir.rglob("content_item.json")}
    argv = [sys.executable, "-m", "content_downloader", "download", url, "--output-dir", str(out_dir)]
    if platform == "douyin":
        if cookies is None:
            raise SwipeError("抖音的视频要用你的抖音登录下：先在设置里连上抖音")
        argv += ["--cookies", str(cookies)]
    done = subprocess.run(argv, check=False, capture_output=True, text=True, env=subprocess_env(), timeout=900)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        raise SwipeError(f"没下下来：{lines[-1][:200] if lines else '下载工具退出了'}")
    after = {p.parent for p in out_dir.rglob("content_item.json")}
    new = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new:
        return new[-1]
    # 以前下过同一条：下载工具会说 Skipped，文件夹还在
    match = re.search(r"(?:Downloaded|Skipped \(already downloaded\)):\s*([A-Za-z0-9_-]+)", done.stdout or "")
    found = [p for p in after if match and p.name == match.group(1)]
    if found:
        return found[0]
    raise SwipeError("下载工具说成功了，但没找到文件")


def read_item(content_dir: Path) -> dict[str, Any]:
    """下载工具写的 content_item.json → 卡片要的几样。"""
    try:
        item = json.loads((content_dir / "content_item.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SwipeError("下下来的文件夹里没有内容信息") from None
    media = [m for m in item.get("media_files") or [] if str(m).lower().endswith((".mp4", ".mov", ".webm", ".m4v"))]
    num = lambda k: int(item[k]) if str(item.get(k) or "").lstrip("-").isdigit() else None  # noqa: E731
    return {
        "content_id": str(item.get("content_id") or content_dir.name),
        "title": (item.get("title") or item.get("description") or "").strip()[:300],
        "author": item.get("author_name") or "",
        "published_at": item.get("publish_time"),
        "likes": num("likes"), "comments": num("comments"), "shares": num("shares"), "collects": num("collects"), "views": num("views"),
        "video": media[0] if media else None,
        "cover": item.get("cover_file") if item.get("cover_file") and (content_dir / item["cover_file"]).is_file() else None,
        "is_video": bool(media),
    }
