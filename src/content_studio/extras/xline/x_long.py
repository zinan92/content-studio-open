"""X 每日长文：一篇原始输出笔记 → park-writing 改一遍 → 个人形象插图 → 他勾了发成 X 图文文章（10/8 作者，#537）。

作者：「长帖现在就不叫长帖了吧，我们变成长文……长文还需要：1. 有个人 IP 的插图；2. 经过我的 approval。
可能需要经过一下这个 park writing skill。」每天 3 篇，纯文字长帖不要了。

- 改写：park-writing 只删、只挪，不改他的词；改完和笔记原文比四字组（writer.fidelity），低于 MIN_FIDELITY 重来一次，
  再不行就算没做成，等他点「重做」。
- 插图：illustrate.illustrate（有个人形象就画他，没有画小黑），图插回文章里。
- 封面：x_article 发的时候按标题出一张纯文字横幅（x_cover，9/24 作者：封面不带人脸）。
- 一篇一个文件夹：<config>/x_long/<帖子 id>/article.md + illustrations/。帖子里的 text 是这篇文章的 Markdown，
  他在页面上改字改的就是它；发之前写回 article.md 再发。

10/9 作者（#564）：「每一篇长文都加一个写这篇文章的日期，在第一段给一个 summary」——第一人称（「我在 2024 年 3 月
25 号写下这篇文章」），一段话回顾当时的情况和 context（交易的尤其要讲当时在想什么），再说这篇总结了什么。
- 这是他点名要的新写的一段（和「只用他原话」的例外一样），单独一次调用写，正文那一关照旧只查正文。
- 日期只信笔记里写的 date / created，其次文件名里的日期；文件创建时间不信（54 篇是 7/19 一次导进来的）。
  都没有就不写日期，卡片上提醒他。
- 当时的情况只能来自笔记本身和它的来源说明；数字、「亏损」这类事件词原文里没有就打回。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any, Callable

from ... import writing_rules

from ... import writer
from ...paths import config_dir

FOLDER = "x_long"
ARTICLE = "article.md"
SKILL = "park-writing"
# 写作走的是本机的 AI 命令（10/6 起是 Codex），它不一定装了这个 skill：工作台自己读 SKILL.md 放进提示词里


class LongError(RuntimeError):
    """Shown to 作者 as-is."""


def folder(post_id: str, root: Path | None = None) -> Path:
    return (root or config_dir()) / FOLDER / post_id


def post_folder(post: dict[str, Any], root: Path | None = None) -> Path:
    """这一篇的文件夹（插图、封面在里面）。跨天挪过来的长文换了 id（10-13-c10-12-A2），文件还在原来那个文件夹里：
    有 article 就跟着 article 走（10/13 作者：封面显示不出来），还没做出来的才按 id。"""
    return Path(post["article"]).parent if post.get("article") else folder(post["id"], root)


def skill_text() -> str:
    """park-writing 的 SKILL.md 正文（去掉 frontmatter）。这台机器没装就空着，只按整理规矩走。"""
    root = writing_rules.skill_dir()
    if root is None:
        return ""
    try:
        text = (root / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    if text.startswith("---"):
        text = text.split("---", 2)[-1]
    return text.strip()


def prompt(title: str, note: str, error: str | None = None, skill: str | None = None) -> str:
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    skill = skill_text() if skill is None else skill
    how = f"\n\n## {SKILL} 的写法（照这个改）\n{skill}\n" if skill else ""
    return f"""按 {SKILL} 的写法，把下面这篇 作者自己的原始输出整理成一篇发在 X 上的长文（X 图文文章）。作者是你 本人。{how}

规矩不能破（和上面冲突时以这里为准）：
{writer.original_words_rules()}
- 不加原文里没有的观点、例子、数字；不要开场白、不要总结段、不要「关注我」。
- 不要出现抖音、视频号、小红书、B 站等平台名，不写「视频里」「整理成文字版」。
- 可以加小标题（## ），小标题尽量用原文里的话。

## 标题
{title}

## 原文
{note}

## 输出
只输出文章本身，Markdown，第一行是「# {title}」。整篇放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间；
改动说明不要放进文章里。{retry}"""


def write(title: str, note: str, *, write_fn: Callable[[str], str], attempts: int = 2) -> str:
    """改写 + 核对：只删只挪的话，四个字连着的片段大多能在原文里找到。"""
    error = None
    for _ in range(attempts):
        try:
            article = writer.extract_article(str(write_fn(prompt(title, note, error)) or ""))
        except writer.WriterError as exc:
            error = str(exc)
            continue
        score = writer.fidelity(article, note)
        if score >= writer.MIN_FIDELITY:
            return article
        error = f"改动太多：只有 {score:.0%} 能在原文里找到，要只删口语、调顺序，不改词"
    raise LongError(f"改写没过：{error}")


# -- 第一段：写作日期 + 当时的情况 + 这篇总结了什么（10/9 作者）-------------------------------------

FILE_DATE = re.compile(r"(?<!\d)(20\d{2})-?(\d{2})-?(\d{2})(?!\d)|(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")
SUMMARY_BLOCK = re.compile(r"<<<SUMMARY>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)
PLATFORMS = re.compile(r"抖音|视频号|小红书|B ?站|公众号")
# 当时发生了什么：这些词原文里没有就不许写（他举的例子是「迎来了巨大的一波亏损」——那得是真的）
EVENTS = ("亏损", "亏了", "爆仓", "盈利", "赚了", "回撤", "清仓", "抄底", "裁员", "离职", "融资", "生病", "分手", "失眠")


def _day(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def written_on(note_path: str, meta: dict[str, Any] | None) -> date | None:
    """这篇是哪天写的：笔记里的 date / created，其次文件名里的日期。都没有返回 None，不猜。"""
    for key in ("date", "created"):
        m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str((meta or {}).get(key) or ""))
        if m and (d := _day(*map(int, m.groups()))):
            return d
    m = FILE_DATE.search(Path(note_path).stem)
    if m:
        y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else ("20" + m.group(4), m.group(5), m.group(6))
        return _day(int(y), int(mo), int(d))
    return None


def cn_date(d: date) -> str:
    return f"{d.year} 年 {d.month} 月 {d.day} 号"


def summary_prompt(title: str, note: str, when: date | None, context: str, error: str | None = None) -> str:
    retry = f"\n\n上一次有问题：{error}。改掉再输出。" if error else ""
    opening = (f"第一句固定是「我在 {cn_date(when)}写下这篇文章。」，一字不差。" if when
               else "不知道这篇是哪天写的：不要写任何日期，第一句从「写这篇文章的时候」开始。")
    return f"""作者 要在这篇长文的最前面加一段 summary。用他自己的口气、第一人称「我」写一段话（不是第三人称介绍他）。

要求：
1. {opening}
2. 接着回顾当时的情况和 context：我当时在想什么、在做什么、遇到了什么。交易相关的尤其要讲清楚当时的处境
   （比如当时正在考虑仓位管理的问题）。只能用下面原文和来源说明里有的事；原文里没有的经历、事件、数字一个都不许加。
3. 最后说这篇文章总结了什么，并直说它是什么东西（10/10 作者：读者要一眼看懂）——比如这其实是我写给 AI agent 的一段 prompt、我和 AI 的一段对话、我的几条原则、一段录音整理，还是我自己的思考。
- 一段话，不分段，150–300 字；口语、直接，像他说话；不要「本文」「笔者」「作者」，不要平台名，不要「关注我」。

## 标题
{title}

## 来源说明（这篇笔记是怎么来的）
{context or '（没有）'}

## 原文
{note[:12000]}

## 输出
只输出这一段，放在单独一行的 <<<SUMMARY>>> 和单独一行的 <<<END>>> 之间。{retry}"""


def check_summary(text: str, note: str, when: date | None) -> str | None:
    if not text or "\n\n" in text.strip():
        return "要一段话，不要分段"
    if not 60 <= len(text) <= 450:
        return f"长度不对（{len(text)} 字），要 150–300 字"
    if when and not text.startswith(f"我在 {cn_date(when)}写下这篇文章"):
        return f"第一句要是「我在 {cn_date(when)}写下这篇文章。」"
    if not when and re.search(r"\d{4} ?年|\d{1,2} ?月 ?\d{1,2} ?[号日]", text):
        return "不知道哪天写的，不要写日期"
    if PLATFORMS.search(text):
        return "不要出现平台名"
    if re.search(r"笔者|作者|本文", text):
        return "要第一人称「我」，不要「笔者」「作者」「本文」"
    allowed = note + (cn_date(when) if when else "")
    numbers = [n for n in re.findall(r"\d+(?:\.\d+)?", text) if n not in allowed]
    if numbers:
        return f"这些数字原文里没有：{'、'.join(numbers)}"
    events = [w for w in EVENTS if w in text and w not in note]
    if events:
        return f"原文里没有这些事：{'、'.join(events)}"
    return None


def summarize(title: str, note: str, *, when: date | None, context: str, write_fn: Callable[[str], str], attempts: int = 2) -> str:
    error = None
    for _ in range(attempts):
        raw = str(write_fn(summary_prompt(title, note, when, context, error)) or "")
        m = SUMMARY_BLOCK.search(raw)
        text = (m.group(1) if m else "").strip()
        error = check_summary(text, note, when) if m else "没有按 <<<SUMMARY>>> 格式返回"
        if error is None:
            return text
    raise LongError(f"开头那段 summary 没写好：{error}")


def with_summary(article: str, summary: str) -> str:
    """把 summary 放成标题下面的第一段。"""
    head, _, rest = article.strip().partition("\n")
    if not head.startswith("#"):
        head, rest = "", article.strip()
    return "\n\n".join(x for x in (head, summary.strip(), rest.strip()) if x) + "\n"


def replace_summary(article: str, summary: str) -> str:
    """换掉标题下面那段 summary（重写 summary 用）；文章里还没有就加上。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", article.strip()) if b.strip()]
    if len(blocks) >= 2 and blocks[0].startswith("#"):
        return "\n\n".join([blocks[0], summary.strip(), *blocks[2:]]) + "\n"
    return with_summary(article, summary)


def context_of(meta: dict[str, Any] | None) -> str:
    meta = meta or {}
    return "\n".join(f"{label}：{meta[k]}" for k, label in (("source", "怎么来的"), ("source_context", "当时的背景")) if meta.get(k))


def prepare(post: dict[str, Any], note: str, *, write_fn: Callable[[str], str],
            illustrate_fn: Callable[[Path], Any], root: Path | None = None,
            meta: dict[str, Any] | None = None,
            steps_fn: Callable[[str, str], str] | None = None, summary: bool = True) -> tuple[str, Path, date | None]:
    """做一篇：改写 → 开头加 summary → 存 article.md → 配图（图插回文章）。返回 (文章 Markdown, 文章路径, 写作日期)。
    steps_fn(标题, 原文) 给了就按 park-writing 清单一步一步改；没给走老的一次整理。"""
    from .x_daily import long_title

    title = long_title(Path(post.get("source_id") or post["id"]).stem)
    when = written_on(str(post.get("source_id") or ""), meta)
    article = steps_fn(title, note) if steps_fn else write(title, note, write_fn=write_fn)
    if summary:  # 带日期的 summary 只给补发的老笔记写（10/12 作者）
        article = with_summary(article, summarize(title, note, when=when, context=context_of(meta), write_fn=write_fn))
    path = folder(post["id"], root) / ARTICLE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(article, encoding="utf-8")
    try:
        illustrate_fn(path)
    except Exception as exc:  # noqa: BLE001 - illustrate 的错误本来就是给 作者 看的
        raise LongError(f"文章改好了，配图没成：{exc}") from exc
    return path.read_text(encoding="utf-8"), path, when
