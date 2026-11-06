"""Publishing title and 简介 for one topic, plus where it has been published.

作者 writes one title and one short 简介 shared by every platform (the page saves the
same entry under each platform key, which the publisher reads). Nothing here
generates copy or publishes. Limits are conservative caps; X counts CJK as two.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

PLATFORMS: dict[str, dict[str, Any]] = {
    # 话题 8：抖音作品描述里带多少个 # 都行，作者 以前的视频最多带过 7 个（4 个流量话题 + 内容话题）
    "douyin": {"label": "抖音", "title": 30, "body": 1000, "tags": 8, "admin": "https://creator.douyin.com/creator-micro/content/upload"},
    "channels": {"label": "视频号", "title": 16, "body": 1000, "tags": 5, "admin": "https://channels.weixin.qq.com/platform/post/create"},
    # 小红书标题 20「字」：两个英文字母算一个字（9/24 作者 实测：按 20 个字符截出来，小红书显示 14）。不截，超了提醒。
    "xiaohongshu": {"label": "小红书", "title": 20, "body": 1000, "tags": 10, "admin": "https://creator.xiaohongshu.com/publish/publish",
                    "count": "half_ascii", "no_trim": True},
    "bilibili": {"label": "B 站", "title": 80, "body": 2000, "tags": 10, "admin": "https://member.bilibili.com/platform/upload/video/frame"},
    "youtube": {"label": "YouTube", "title": 100, "body": 5000, "tags": 15, "admin": "https://studio.youtube.com/"},
    "x": {"label": "X", "title": 0, "body": 280, "tags": 3, "admin": "https://x.com/compose/post", "weighted": True},
    "wechat_mp": {"label": "公众号", "title": 64, "body": 20000, "tags": 5, "admin": "https://mp.weixin.qq.com/"},
    "miniprogram": {"label": "研习室", "title": 64, "body": 200, "tags": 5, "admin": None},
    "xiaoyuzhou": {"label": "小宇宙", "title": 32, "body": 1000, "tags": 5, "admin": "https://podcaster.xiaoyuzhoufm.com/"},
    "yanxishi": {"label": "研习室", "title": 64, "body": 200, "tags": 5, "admin": None},
}


# 设置里能填流量话题的平台（10/8 作者：一页看全，只在设置里改）。公众号、研习室、小宇宙发出去不带话题。
TAG_PLATFORMS = ("douyin", "channels", "xiaohongshu", "x", "bilibili", "youtube")


def with_traffic(key: str, tags: list[str], traffic: dict[str, list[str]]) -> list[str]:
    """这个平台发出去的话题：它自己的流量话题在前，内容话题在后（任何平台的流量话题都不算内容话题），去重，按上限截。
    10/8 起发的时候按设置现算：设置里新填的流量话题，已经打包好的那条也带上。"""
    every = {t for v in traffic.values() for t in (v or [])}
    content = [t for t in tags if t not in every]
    merged = list(dict.fromkeys([*(traffic.get(key) or []), *content]))
    return merged[: int(PLATFORMS.get(key, {}).get("tags") or len(merged))]


# 这条带了产品（#590）：发出去时描述最后加一行。国内三个平台（抖音、视频号、小红书）只放私信关键词——
# 站外链接点不开、还容易被限流；其余平台有落地页放落地页，没有就放关键词。都没填就什么都不加，不编。
KEYWORD_ONLY = ("douyin", "channels", "xiaohongshu")


def product_line(key: str, product: dict[str, Any] | None) -> str:
    if not product:
        return ""
    name, word, landing = (str(product.get(k) or "").strip() for k in ("name", "keyword", "landing"))
    if word and (key in KEYWORD_ONLY or not landing):
        return f"{name}：私信「{word}」"
    if landing and key not in KEYWORD_ONLY:
        return f"{name}：{landing}"
    return ""


def with_product(key: str, body: str, product: dict[str, Any] | None, tags: list[str] | None = None) -> str:
    """描述末尾加上这条带的产品那一行；已经有了、或者加了会超过这个平台的上限，就不加。"""
    line = product_line(key, product)
    if not line or line in body:
        return body
    out = f"{body.rstrip()}\n\n{line}" if body.strip() else line
    spec = PLATFORMS.get(key) or {}
    cap = int(spec.get("body") or 0)
    size = x_length(out + " " + " ".join(f"#{t}" for t in tags or [])) if spec.get("weighted") else len(out)
    return out if not cap or size <= cap else body


def x_length(text: str) -> int:
    return sum(2 if re.match(r"[⺀-鿿＀-￯　-〿]", ch) else 1 for ch in text)


def measure(platform: str, entry: dict[str, Any]) -> list[str]:
    spec = PLATFORMS[platform]
    problems = []
    title = str(entry.get("title") or "")
    body = str(entry.get("body") or "")
    tags = entry.get("tags") or []
    if spec["title"] and not title.strip():
        problems.append(f"{spec['label']}缺标题")
    if spec["title"] and len(title) > spec["title"]:
        problems.append(f"{spec['label']}标题 {len(title)} 字，超过 {spec['title']}")
    if not spec["title"] and title:
        problems.append(f"{spec['label']}不需要标题")
    length = x_length(body + " " + " ".join(f"#{t}" for t in tags)) if spec.get("weighted") else len(body)
    if not body.strip():
        problems.append(f"{spec['label']}缺正文")
    elif length > spec["body"]:
        problems.append(f"{spec['label']}正文长度 {length}，超过 {spec['body']}")
    if not isinstance(tags, list) or len(tags) > spec["tags"] or any(not str(t).strip() or "#" in str(t) for t in tags):
        problems.append(f"{spec['label']}话题最多 {spec['tags']} 个，不带 #")
    return problems


def save_copy(drafts_dir: Path, topic_id: int, copy: dict[str, Any]) -> Path:
    folder = drafts_dir.expanduser() / f"topic-{topic_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "copy.json"
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "platforms": copy}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_copy(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    path = drafts_dir.expanduser() / f"topic-{topic_id}" / "copy.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["checks"] = {key: measure(key, entry) for key, entry in data["platforms"].items() if key in PLATFORMS}
    return data


def title_units(text: str, spec: dict[str, Any]) -> float:
    """按平台的算法数标题长度。小红书：ASCII 字符算半个字。"""
    if spec.get("count") == "half_ascii":
        return sum(0.5 if ord(ch) < 128 else 1 for ch in text)
    return float(len(text))
