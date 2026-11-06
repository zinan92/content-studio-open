"""每条内容在每个平台上的链接：存成别人点得开的公开链接，存不成的说清楚。

9/29 作者：「每一条内容在每一个平台上都有一个独特的链接，这个我们要好好保存下来。」链接只存一处——
工作台数据库的 publish_records（一条内容 × 一个平台一行）；「已发出 → 链接」那一页读它、改它。

存进来的时候先换成公开链接：发布脚本回来的常常是后台页（YouTube Studio 编辑页、抖音创作者中心作品详情），
作者自己点得开，别人点不开。换不了的（公众号草稿预览链接会过期）照存，但标出来等他换。
"""
from __future__ import annotations

import re

_YOUTUBE_STUDIO = re.compile(r"^https?://studio\.youtube\.com/video/([\w-]{6,})")
_DOUYIN_CREATOR = re.compile(r"^https?://creator\.douyin\.com/.*/work-detail/(\d{8,})")


def public_url(platform: str, url: str | None) -> str | None:
    """后台链接换成公开链接；认不出的原样返回。"""
    if not url:
        return url
    url = url.strip()
    m = _YOUTUBE_STUDIO.match(url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    m = _DOUYIN_CREATOR.match(url)
    if m:
        return f"https://www.douyin.com/video/{m.group(1)}"
    return url


def issue(platform: str, url: str | None) -> str | None:
    """这条链接还有什么问题（没有就 None）。"""
    if not url:
        # 研习室是小程序，没有网页链接；记一笔已发就够了
        return None if platform == "miniprogram" else "还没贴链接"
    if "mp.weixin.qq.com" in url and "tempkey=" in url:
        return "这是公众号草稿预览链接，会过期：群发后换成正式链接"
    if not url.startswith("http"):
        return "不像一个网址"
    return None


_POST_ID = {
    "bilibili": re.compile(r"/video/(BV[\w]+)"),
    "youtube": re.compile(r"[?&]v=([\w-]{6,})"),
    "x": re.compile(r"/status/(\d+)"),
    "xiaohongshu": re.compile(r"/explore/([0-9a-f]{16,})"),
    "douyin": re.compile(r"/video/(\d{8,})"),
}


def post_id(platform: str, url: str | None) -> str | None:
    """从公开链接里拿出平台自己的帖子编号（和 post_snapshots.post_id 对得上）。"""
    m = _POST_ID.get(platform).search(url or "") if platform in _POST_ID else None
    return m.group(1) if m else None
