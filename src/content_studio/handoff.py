"""把工作台写好的文章交给 作者 现成的公众号管线。

作者 早就有一整套：`004_内容加工中/<主题>/wechat-package/` 里有橄榄手记排版模板、
封面渲染器、图文质检、API 草稿回读、media_id 回执。工作台不重做这些——它的活儿到
「文章写完、按管线要的格式落进 vault」为止，后面交给那套跑。

所以这里只写管线的入口所需，不伪造它下游自己会产出的东西（配图规划、QA、回执）。
封面同理：`draft/add` 要 thumb_media_id，而那是 cover/ 渲染器的产物，不是工作台的。
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import tempfile
from typing import Any

FOLDER = "004_内容加工中"
PACKAGE = "wechat-package"


class HandoffError(RuntimeError):
    """交接没做成；消息直接展示给 作者。"""


def slug(title: str) -> str:
    """目录名用 作者自己的习惯：短标题，不带日期、不带标点。"""
    cleaned = re.sub(r"[\\/:*?\"<>|#\[\]]+", "", title or "").strip()
    cleaned = re.sub(r"[，。！？、；：,.!?;:]+", "", cleaned)
    return cleaned[:28] or "未命名"


def split_article(markdown: str) -> dict[str, str]:
    """从文章正文里取标题、引语和摘要——不另外调模型。"""
    body = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.S).strip()
    title_match = re.search(r"^#\s+(.+)$", body, flags=re.M)
    title = title_match.group(1).strip() if title_match else ""
    rest = body[title_match.end():].strip() if title_match else body
    quote = ""
    quote_match = re.match(r"^>\s*(.+)$", rest, flags=re.M)
    if quote_match:
        quote = quote_match.group(1).strip()
        rest = rest[quote_match.end():].strip()
    # 摘要取第一段正文，公众号摘要栏放得下的长度
    first = next((p.strip() for p in re.split(r"\n\s*\n", rest) if p.strip() and not p.startswith(("#", ">", "-", "|"))), "")
    summary = quote or re.sub(r"\s+", "", first)[:110]
    return {"title": title, "quote": quote, "summary": summary, "body": body}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".h-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def handoff(vault_root: Path, *, topic: dict[str, Any], markdown: str, today: str | None = None,
            author: str = "作者") -> dict[str, Any]:
    parts = split_article(markdown)
    if not parts["title"]:
        raise HandoffError("文章没有一级标题，管线认不出标题")
    day = today or datetime.now().date().isoformat()
    folder = vault_root / FOLDER / slug(topic.get("title") or parts["title"])
    article_path = folder / PACKAGE / "wechat-article.md"
    if article_path.exists():
        raise HandoffError(f"{folder.name} 已经交接过了，没有覆盖。要重做就先把那个目录改名")

    front = "\n".join([
        "---",
        'stage: "06"',
        'version: "v1"',
        'content_lock: "工作台草稿，作者 未确认"',
        f'title: "{parts["title"]}"',
        f'author: "{author}"',
        f'summary: "{parts["summary"]}"',
        'coverImage: ""   # 待 cover/ 渲染器生成',
        f'from_workbench: "topic-{topic.get("id")}"',
        f'handed_off_at: "{day}"',
        "---",
        "",
    ])
    _write(article_path, front + parts["body"] + "\n")

    _write(folder / "README.md", "\n".join([
        "---",
        f'topic: "{parts["title"]}"',
        'delivery_status: "草稿已就位，等配图和排版"',
        f'updated_at: "{day}"',
        "---",
        "",
        f"# {parts['title']}｜工作台交接",
        "",
        "## Final 内容",
        "",
        f"- 公众号正文：[[{PACKAGE}/wechat-article]]",
        "",
        "## 当前状态",
        "",
        f"- 正文由内容工作台生成（topic-{topic.get('id')}），{day} 交接。",
        "- 待办：配图规划、封面渲染、排版成 HTML、发草稿箱。",
        "- 工作台只负责到正文；后面走既有的 wechat-package 流程。",
        "",
    ]))
    return {"folder": str(folder), "article": str(article_path), "title": parts["title"], "summary": parts["summary"]}
