"""进项里每一条的「发 X」：按 作者 的风格给一条建议稿，他删改、他点了才发（10/5 作者）。

作者：「你要找到我的写作风格。这样的话，发 X 的时候会有一个建议：如果我选择确定，就直接发出去；
我也可以在你的这个建议上进行删除或者修改。」还有：「先所有东西都需要我的 approval。」

规矩：
- 只在他点「发 X」时跑，不预先给每条都写（他先看原始的）。
- 他自己的原始输出走 x_line.organize：只删口语、不改词，和 X 单独一条线同一套。
- 别人的东西（收藏、Clippings、日报、老师和对标）才写建议稿。世界观文件 的内容红线：newsletter / references
  不原样总结成他的内容发出去——所以必须说清是谁说的、带链接，再加一句他自己的判断。
- 他的判断只能来自 世界观文件 里他真说过的世界观和原则；不编他的经历，不编数字。这两条代码也查，不只靠提示词。
- 风格是一份文件：第一次用时从他发过的内容（005）和原始输出（003）里总结出来，写进 Anna 的工作流文件夹
  「X 写作风格.md」，之后他随时能改；文件在就不重写，免得冲掉他的改动。
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Callable

from ... import writing_rules

from ... import writer
from ...outline import DEFAULT_WORKFLOWS, workflows_dir
from ...paths import config_dir
from ...vault import SERIES_INDEX, parse_frontmatter
from ...x_post import MAX_WEIGHTED, weighted_length

STYLE_FILE = "X 写作风格.md"
PUBLISHED_FOLDER = "005_我发出的内容"
RAW_FOLDER = "003_原始输出"
WORLDVIEW_ENV = "CONTENT_STUDIO_WORLDVIEW"
DEFAULT_WORLDVIEW = Path("~/notes/worldview.md")
SAMPLES = {PUBLISHED_FOLDER: (10, 1500), RAW_FOLDER: (8, 1200)}
# 他没说过的亲身经历：建议稿里出现就打回重写
MADE_UP = re.compile(r"我(?:试了|测了|用了|做了|跑了|装了|上周|昨天|前天|今天早上|的客户|客户)|有个客户|我一个客户")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
URL = re.compile(r"https?://\S+")


class SuggestError(RuntimeError):
    pass


# -- 风格 ----------------------------------------------------------------------


def style_path() -> Path:
    """配了 Anna 的工作流文件夹（Obsidian）就放那里，他能改；没配就放本机配置目录，绝不写进仓库自带的示例。"""
    references = writing_rules.references_dir()
    if references is not None:
        return references / writing_rules.LEGACY[STYLE_FILE]
    folder = workflows_dir()
    try:
        bundled = folder.resolve() == DEFAULT_WORKFLOWS.resolve()
    except OSError:
        bundled = True
    return (config_dir() if bundled else folder) / STYLE_FILE


def corpus(vault: Path) -> str:
    """他自己的话：发出去的视频文稿（005）和原始输出（003），各取最新几篇的开头。"""
    parts = []
    for folder, (count, chars) in SAMPLES.items():
        root = vault / folder
        if not root.is_dir():
            continue
        files = sorted((p for p in root.rglob("*.md") if not p.name.startswith(".") and p.name != SERIES_INDEX
                        and "鸡蛋" not in p.relative_to(root).parts),  # 鸡蛋话术是回评论区的，不是他写 X 的口气
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:count]:
            try:
                _, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            body = body.strip()
            if body:
                parts.append(f"### {folder} / {path.stem}\n{body[:chars]}")
    return "\n\n".join(parts)


def style_prompt(text: str) -> str:
    return f"""下面是 作者自己的话：他发出去的视频文稿和他自己写的原始输出。从里面总结他的说话、写作风格，
给以后替他起草 X 帖子的人看。

要求：
- 只写他真有的特点，每一条后面跟一句他的原话当例子（原样抄，不改）。他没有的特点不要写。
- 写这几块：怎么开头、句子长短和节奏、常用的词和说法（包括中英夹杂）、语气和态度、他从来不用的东西。
- 最后一块「发 X 时」：一条帖子怎么写最像他（几句、多长、怎么落一句判断）。
- 用 Markdown，标题是「# X 写作风格」，全文 1500 字以内。只输出这份文件，前后不要说明。

## 他的话
{text}"""


def ensure_style(vault: Path, write_fn: Callable[[str], str]) -> tuple[Path, str, bool]:
    """有就读；没有就总结一份写进去。返回（路径, 内容, 是不是这次新写的）。"""
    path = style_path()
    if path.is_file():
        return path, path.read_text(encoding="utf-8"), False
    text = corpus(vault)
    if not text:
        raise SuggestError(f"找不到你自己的话（{PUBLISHED_FOLDER}、{RAW_FOLDER} 都是空的），没法总结风格")
    style = str(write_fn(style_prompt(text)) or "").strip()
    if len(style) < 100:
        raise SuggestError("总结风格没出结果，再点一次")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(style + "\n", encoding="utf-8")
    return path, style, True


def views() -> str:
    """世界观文件 里他的世界观和原则（交易那一节不要）。找不到就空着，建议稿只写一句问题。"""
    path = Path(os.environ.get(WORLDVIEW_ENV) or DEFAULT_WORLDVIEW).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    start, end = text.find("## 二、"), text.find("## 四、")
    if start < 0:
        return ""
    body = text[start:end if end > start else None]
    body = re.sub(r"### 交易\n.*?(?=\n### |\Z)", "", body, flags=re.S)
    return body.strip()[:7000]


# -- 建议稿 --------------------------------------------------------------------


def suggest_prompt(item: dict[str, Any], style: str, beliefs: str, error: str | None = None) -> str:
    retry = f"\n\n上一次的稿子有问题：{error}。改掉再输出。" if error else ""
    who = "，".join(x for x in (item.get("source") or "", item.get("author") or "") if x)
    judge = ("作者 的判断只能来自下面「他的世界观和原则」里真有的一条：挑最相关的，用他的话说出来。没有相关的，就只写一句他会追问的问题。"
             if beliefs else "没有他的世界观材料：不要替他下判断，只写一句他会追问的问题。")
    return f"""你在替 作者 起草一条 X 帖子的建议稿。他会看、会删改，他点了才发。

## 他的写作风格（照这个写）
{style.strip()}

## 他的世界观和原则（他真说过的）
{beliefs or '（没有）'}

## 他在进项里看到的这一条（不是他写的）
来源：{who or '（不知道）'}
标题：{item.get('title') or ''}
链接：{item.get('url') or '（没有）'}
内容：
{(item.get('text') or '（只有标题）').strip()[:4000]}

## 规矩（不能破）
- 只写一条。中文一个字算两个，链接按实际字数算，整条不超过 {MAX_WEIGHTED}。
- 这是别人的东西：说清是谁 / 哪里说的；有链接就带上。不许写成 作者 的原创，也不许只是原样总结。
- {judge}
- 不编他的经历：不写「我试了」「我用了」「我客户」「上周我」这类他没说过的事。
- 不编数字：数字只能来自上面这条内容。
- 不加话题标签、不加表情、不加「关注我」。

## 输出
放在单独一行的 <<<POST>>> 和单独一行的 <<<END>>> 之间，前后不要有其他说明。{retry}"""


def x_length(text: str) -> int:
    """和真正发帖的 x_post.post_tweet 用同一把尺子（链接按实际字数算，比 X 自己的 23 严）：这里说没超，点「确定」就发得出去。"""
    return weighted_length(text)


def check(post: str, item: dict[str, Any], *, limit: int = MAX_WEIGHTED) -> str | None:
    """代码这一关：长度、编经历、编数字。返回问题，没问题返回 None。limit：热点长帖（10/9）放到长帖上限。"""
    if not post.strip():
        return "是空的"
    if x_length(post) > limit:
        return f"太长了（{x_length(post)}，上限 {limit}，中文算两个）"
    made = MADE_UP.search(post)
    if made:
        return f"编了他没说过的经历：「{made.group(0)}」"
    source = f"{item.get('title') or ''}\n{item.get('text') or ''}"
    invented = [n for n in NUMBER.findall(URL.sub("", post)) if n not in source]
    if invented:
        return f"这些数字原文里没有：{'、'.join(invented)}"
    return None


def _post(raw: str) -> str:
    found = re.findall(r"<<<POST>>>\s*\n(.*?)\n\s*<<<END>>>", str(raw or ""), flags=re.S)
    return (found[0] if found else str(raw or "")).strip()


def suggest(item: dict[str, Any], *, style: str, beliefs: str, write_fn: Callable[[str], str], attempts: int = 2) -> str:
    """一条建议稿。不过代码这一关就带着问题重写一次；还不过就报错，不把有问题的稿子给他。"""
    error = None
    for _ in range(attempts):
        post = _post(write_fn(suggest_prompt(item, style, beliefs, error)))
        url = item.get("url") or ""
        if url and url not in post and x_length(post.rstrip() + "\n" + url) <= MAX_WEIGHTED:
            post = post.rstrip() + "\n" + url  # 别人的东西要带出处：模型忘了就补上
        error = check(post, item)
        if error is None:
            return post
    raise SuggestError(f"建议稿没写好（{error}），再点一次")


def source_id(kind: str, ref: str) -> str:
    return f"in:{kind}:{ref}"[:300]


def is_own(path: str, raw_folder: str = RAW_FOLDER) -> bool:
    return path.replace("\\", "/").startswith(raw_folder.rstrip("/") + "/")


def default_write(prompt_text: str) -> str:
    return writer.cli_write(prompt_text)
