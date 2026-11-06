"""用 gzh-design skill 给研习室那篇文章排版：一份 HTML，公众号和研习室都用它。

9/24 作者：「公众号和小程序其实都可以通过 gzh skill 来编辑格式。」以前 7/13、7/14 两篇
公众号就是这个 skill 排的（橄榄手记）。它按内容挑组件（引言卡、重点观点卡、章节编号……），
比逐行机械转换好看；研习室的 HTML 导入会原样保留内联样式。

排完用 skill 自带的 validate_gzh_html.py 校验；再核一遍文字——排版只能动样式，不能丢段落、
不能加文章里没有的话。文章改过（哈希变了）旧排版就作废，发布时退回机械排版并说明。
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

from .writer import ARTICLE_BLOCK, WriterError, cli_write

from . import conf

SKILL_DIR = conf.path("skills.gzh_design")
VALIDATOR = SKILL_DIR / "scripts" / "validate_gzh_html.py"
THEME = "橄榄手记"
FILENAME = "article.gzh.html"
META = "article.gzh.json"
LAYOUT_COMMAND_ENV = "CONTENT_STUDIO_LAYOUT_CMD"
DEFAULT_LAYOUT_COMMAND = (
    "claude -p --model opus --output-format text "
    '--allowedTools "Skill Read Glob Grep" '
    '--disallowedTools "Bash Edit Write WebFetch WebSearch NotebookEdit"'
)
KEEP_RATIO = 0.97  # 原文字符至少这么多出现在排版结果里


def digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def build_prompt(markdown: str, *, theme: str = THEME, error: str | None = None) -> str:
    retry = f"\n\n上一次的结果有问题：{error}。请修正后重新输出。" if error else ""
    return f"""用 gzh-design skill 给下面这篇文章排公众号 HTML。

- 全自动模式：不要提问，直接排。
- 主题：{theme}。
- 这是排版，不是改写：正文每一句都要原样保留，不增不删、不改措辞、不加文章里没有的标题或结语。可以用主题里的组件（章节编号、引言卡、重点观点卡等）承载原文。
- 不要作者签名区、二维码、关注引导这类原文没有的东西。
- 头图卡不要右边那格占位插画（DOODLE），整栏去掉；全文不放任何占位图。
- 排完按 skill 的要求自查一遍能不能直接粘贴进公众号编辑器。

只输出最终 HTML（从最外层 <section> 开始），放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间，前后不要有别的说明。

---

{markdown}{retry}"""


def _plain(text: str) -> str:
    """只留汉字、字母、数字，比较「字还在不在」用。"""
    return re.sub(r"[^\w一-鿿]", "", text)


def text_of_html(markup: str) -> str:
    markup = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", markup, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def text_of_markdown(markdown: str) -> str:
    body = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.S)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", body)
    return re.sub(r"[#>*`_~\-|]", "", body)


def check_fidelity(markdown: str, markup: str) -> None:
    """原文的字要基本都在；排版不许丢段落。按字符多重集算，顺序换了（放进卡片）不算错。"""
    want = _plain(text_of_markdown(markdown))
    have = _plain(text_of_html(markup))
    if not want:
        raise WriterError("文章是空的")
    pool: dict[str, int] = {}
    for ch in have:
        pool[ch] = pool.get(ch, 0) + 1
    kept = 0
    for ch in want:
        if pool.get(ch, 0) > 0:
            pool[ch] -= 1
            kept += 1
    ratio = kept / len(want)
    if ratio < KEEP_RATIO:
        raise WriterError(f"排版后原文只剩 {ratio:.0%}，有段落被丢了")
    extra = len(have) - kept
    if extra > max(200, len(want) * 0.08):
        raise WriterError(f"排版多出了约 {extra} 个原文没有的字")


DOODLE = re.compile(r'<section[^>]*border:1px dashed[^>]*>\s*<svg[\s\S]*?</svg>\s*<span[^>]*>\s*<span leaf="">DOODLE</span>\s*</span>\s*</section>')


def drop_placeholders(markup: str) -> str:
    """橄榄手记头图卡右边那格占位插画（一张笑脸 + DOODLE）是模板占位，不该发出去。"""
    return DOODLE.sub("", markup)


def validate(markup: str, *, validator: Path = VALIDATOR) -> None:
    if not validator.is_file():
        return  # skill 没装校验脚本就跳过，文字核对照做
    done = subprocess.run([sys.executable, str(validator), "--stdin"], input=markup, capture_output=True, text=True, timeout=60, check=False)
    if "完全合规" not in done.stdout:
        problems = [l.strip() for l in done.stdout.splitlines() if l.strip().startswith(("❌", "⚠", "-"))][:6]
        raise WriterError("公众号合规校验没过：" + ("；".join(problems) or done.stdout.strip()[-200:]))


def layout(article: Path, *, write_fn: Callable[[str], str] | None = None, attempts: int = 2,
           theme: str = THEME, validator: Path = VALIDATOR, now: datetime | None = None) -> dict[str, Any]:
    markdown = article.read_text(encoding="utf-8")
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(LAYOUT_COMMAND_ENV) or DEFAULT_LAYOUT_COMMAND, timeout=1200))
    error: str | None = None
    for _ in range(attempts):
        try:
            match = ARTICLE_BLOCK.search(fn(build_prompt(markdown, theme=theme, error=error)))
            if not match:
                raise WriterError("模型没有按格式返回 HTML")
            markup = drop_placeholders(match.group(1).strip())
            if not markup.startswith("<"):
                raise WriterError("返回的不是 HTML")
            if "DOODLE" in markup:
                raise WriterError("还留着占位插画（DOODLE），去掉")
            validate(markup, validator=validator)
            check_fidelity(markdown, markup)
            break
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没排成：{error}")
    (article.parent / FILENAME).write_text(markup, encoding="utf-8")
    meta = {"source_sha256": digest(markdown), "theme": theme,
            "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    (article.parent / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def current(article: Path) -> Path | None:
    """和现在这篇文章对得上的排版；文章改过就返回 None（旧排版作废）。"""
    page, meta = article.parent / FILENAME, article.parent / META
    if not (article.is_file() and page.is_file() and meta.is_file()):
        return None
    try:
        recorded = json.loads(meta.read_text(encoding="utf-8")).get("source_sha256")
    except (OSError, ValueError):
        return None
    return page if recorded == digest(article.read_text(encoding="utf-8")) else None


def state(article: Path | None) -> dict[str, Any]:
    if article is None or not article.is_file():
        return {"has_layout": False, "stale": False}
    page, meta = article.parent / FILENAME, article.parent / META
    fresh = current(article)
    info: dict[str, Any] = {"has_layout": page.is_file(), "stale": page.is_file() and fresh is None}
    if meta.is_file():
        try:
            info.update({k: v for k, v in json.loads(meta.read_text(encoding="utf-8")).items() if k in ("theme", "generated_at")})
        except (OSError, ValueError):
            pass
    return info
