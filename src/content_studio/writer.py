"""Write an article draft for a topic with the local Claude CLI.

默认不用任何写作 skill，只整理作者的原话
（删口语、可以调句子顺序、不改每句话的词）；设置里留一个「写文章用哪个 skill」的空位，客户想用
某个写作 skill 仍然可以选。作者永远是 作者。Drafts live under the app data directory and are
never written back into the Obsidian vault.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable

from . import vault
from . import llm
from .paths import config_dir
from .judge import JudgeLoginError

DEFAULT_WRITER_COMMAND = (
    "claude -p --model opus --output-format text "
    '--allowedTools "Skill Read Glob Grep" '
    '--disallowedTools "Bash Edit Write WebFetch WebSearch NotebookEdit"'
)
WRITER_COMMAND_ENV = "CONTENT_STUDIO_WRITER_CMD"
DEFAULT_DRAFTS_DIR = config_dir() / "drafts"
MAX_NOTE_CHARS = 12000
MAX_SOURCE_CHARS = 30000
ARTICLE_BLOCK = re.compile(r"<<<ARTICLE>>>\s*\n(.*?)\n\s*<<<END>>>", re.DOTALL)
FOREIGN_SIGNATURE = re.compile(r"(作者[:：]\s*卡兹克|数字生命卡兹克|wzglyay@|投稿或爆料)")
ORIGINAL_WORDS = "原话整理"  # meta 里的 skill 名：没用写作 skill
# 只整理原话时，正文里连着的四个字至少这么多要能在原话里找到。10/4 拿 10/2 那条（1.2 万字字幕）校过：
# 卡兹克写的版本 46%，照新规矩整理的 82%。两个字一组太松（卡兹克版也有 81%）。
MIN_FIDELITY = 0.7
GRAM = 4

WriteFn = Callable[[str], str]


class WriterError(RuntimeError):
    """The article could not be produced; the message is shown to 作者."""


def gather_sources(vault_raw: str, note_paths: list[str]) -> list[dict[str, Any]]:
    sources, used = [], 0
    for path in note_paths:
        try:
            note = vault.read_note(vault_raw, path)
        except vault.VaultError:
            continue
        body = (note.get("body") or "").strip()[:MAX_NOTE_CHARS]
        if not body or used >= MAX_SOURCE_CHARS:
            continue
        body = body[: MAX_SOURCE_CHARS - used]
        used += len(body)
        sources.append({"path": path, "title": note["title"], "url": note["meta"].get("source") or note["meta"].get("url"), "body": body})
    return sources


def topic_sources(vault_raw: str, topic: dict[str, Any], drafts_dir: Path) -> list[dict[str, Any]]:
    """Everything a topic was built from: snapshots stored with it (a 快讯 picked from the
    daily), then its vault notes, under one character budget."""
    from .extras.dailies.newsletter import attached_sources

    out, used = [], 0
    for src in [*attached_sources(drafts_dir, topic["id"]), *gather_sources(vault_raw, topic.get("note_paths") or [])]:
        if used >= MAX_SOURCE_CHARS:
            break
        body = src["body"][: min(MAX_NOTE_CHARS, MAX_SOURCE_CHARS - used)]
        used += len(body)
        out.append({**src, "body": body})
    return out


TRANSCRIPT_TITLE = "视频原话（转写）"
VIDEO_RULE = """
- 这篇的内容来自 作者 那条视频的原话（文章里不要提视频）。**观点和例子以「视频原话」为准**：
  不要加视频里没说的观点、经历和数字；笔记只用来核对和补细节。"""


def original_words_rules() -> str:
    """作者 10/4 定的整理规矩。写文章和 X 的「整理」都用这一份，规矩只在这里改。"""
    return """- 只删：口头禅、语气词、重复、说岔了又收回来的半句（「就是」「然后」「对吧」「其实呢」这类）。
- 可以调顺序：句子和段落可以挪（比如第 4 句放到第 3 句前面），让它更好读、更有条理。
- 不改词：每一句保留 作者 的原词、原来的说法和语气，包括中英夹杂；不换同义词，不把口语改成书面语，
  不加连接句、过渡段、总结段，不加原话里没有的比喻、例子、数字和观点。
- 实在不通的句子，只补最少的字让它读得通。"""


def _skill_part(skill: str) -> str:
    if skill:
        return f"""请使用 {skill} skill 的写作方法、风格规则和自检流程来写。
重要：{skill} 只提供写法。文章作者是你，不是这个 skill 的作者。
- 不要出现这个 skill 作者的署名、邮箱、投稿方式和他的固定结尾（比如「以上，既然看到这里了……三连」）。"""
    return f"""文章作者是你，用的是他自己的话。不要用任何写作 skill，也不要换成你自己的文风。作者 的力量感来自他自己的句子，你的工作只是整理：
{original_words_rules()}
- 素材里 作者自己说的、写的照上面整理；别人的观点要说明是谁说的，不要据为己有，也不要替 作者 扩写成长篇。"""


def _grams(text: str) -> list[str]:
    chars = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text.lower())
    return ["".join(chars[i:i + GRAM]) for i in range(len(chars) - GRAM + 1)]


def fidelity(article: str, original: str) -> float:
    """正文（不算标题行）里连着的四个字有多少能在原话里找到。只删、只挪时高；改写会明显变低。"""
    body = "\n".join(l for l in article.splitlines() if not l.lstrip().startswith("#"))
    grams = _grams(body)
    if not grams:
        return 1.0
    known = set(_grams(original))
    return sum(g in known for g in grams) / len(grams)


def _memo_for_writer(memo: str | None) -> str:
    """备注里工作台自己记的流程话（比如补发时的「补发：抖音发过的旧视频」）不是写作要求，不给写作看：
    9/27 它让文章开头写成了「这是我之前在抖音发过的视频，整理成了文字版」。"""
    return "\n".join(l for l in (memo or "").splitlines() if not l.strip().startswith("补发")).strip()


def _rewrite_part(instruction: str, previous: str) -> str:
    """9/29 作者：「重写就完全不一样了，我要知道它怎么会不一样。」重写一定带一句要求和上一版，只改他说的。"""
    if not instruction.strip():
        return ""
    return f"""

## 这次是重写
作者 看了上一版，要这样改：{instruction.strip()}
只按这句话改；他没提到的地方（观点、例子、结构、措辞）保持上一版不动。素材规则照旧。

### 上一版全文
{previous.strip()}"""


def build_prompt(topic: dict[str, Any], sources: list[dict[str, Any]], error: str | None = None,
                 instruction: str = "", previous: str = "", skill: str = "") -> str:
    from_video = any(s["title"] == TRANSCRIPT_TITLE for s in sources)
    material = "\n\n".join(
        f"### 素材 {i + 1}：{s['title']}\n来源：{s['url'] or s['path']}\n\n{s['body']}" for i, s in enumerate(sources)
    ) or "（没有附带素材，只根据选题和备注写。）"
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    return f"""你在帮 作者 写一篇公众号文章，文章会发到他的会员内容产品「作者 研习室」。

{_skill_part(skill)}
- 用第一人称「我」写 作者 的观点；素材里别人的观点要说明是谁说的，不要据为己有。
- 素材里没有的事实、数字、人名不要编。
- 文章要像专门为这个平台写的：不要提它来自哪个平台或哪条视频，不要写「之前在抖音发过」「整理成文字版」「补发」
  「视频里」「关注我」这类话，也不要出现抖音、视频号、小红书、B 站等平台名（作者 9/27：其他平台会当成引流）。{VIDEO_RULE if from_video else ""}

## 选题
{topic['title']}

## 作者 的备注
{_memo_for_writer(topic.get('memo')) or '（无）'}

## 素材
{material}

{_rewrite_part(instruction, previous)}

## 输出
只输出文章本身，Markdown 格式，第一行是「# 标题」。把整篇文章放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间，前后不要有其他说明。{retry}"""


def cli_write(prompt: str, *, command: str | None = None, timeout: float = 1200.0) -> str:
    argv = shlex.split(command or os.environ.get(WRITER_COMMAND_ENV) or DEFAULT_WRITER_COMMAND)
    try:
        completed = llm.run(argv, input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise WriterError("写作超时（20 分钟），可以点重试") from exc
    except OSError as exc:
        raise WriterError(f"找不到写作命令：{exc}") from exc
    if completed.returncode != 0:
        detail = f"{completed.stderr}\n{completed.stdout}"
        if re.search(r"authenticat|log ?in|oauth", detail, re.IGNORECASE):
            raise JudgeLoginError(f"本机 {llm.label()} 命令行没登录或登录过期：{llm.login_hint()}，然后点重试")
        raise WriterError(f"写作命令失败（退出码 {completed.returncode}）：{llm.error_detail(completed.stderr, completed.stdout)}")
    return completed.stdout


def extract_article(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回文章")
    article = match.group(1).strip()
    if not article.startswith("#") or len(article) < 200:
        raise WriterError("返回的文章太短或缺少标题")
    if FOREIGN_SIGNATURE.search(article):
        raise WriterError("文章里带了写作 skill 作者的署名或联系方式")
    return article + "\n"


def transcript_fp(text: str) -> str:
    """字幕原话的指纹（忽略空白）：文章记下它是照哪一份字幕写的，视频重录、字幕换了就对不上。"""
    return hashlib.sha1(re.sub(r"\s+", "", text).encode("utf-8")).hexdigest()[:16]


def write_article(
    topic: dict[str, Any],
    *,
    vault_raw: str,
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn = cli_write,
    attempts: int = 2,
    now: datetime | None = None,
    transcript: str = "",
    instruction: str = "",
    skill: str = "",
) -> dict[str, Any]:
    sources = topic_sources(vault_raw, topic, drafts_dir)
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    old = folder / "article.md"
    previous = old.read_text(encoding="utf-8") if old.is_file() else ""
    if transcript.strip():
        # 视频拍完了：原话排第一，不占笔记的字数额度。
        sources = [{"path": "视频项目", "title": TRANSCRIPT_TITLE, "url": None, "body": transcript.strip()[:MAX_SOURCE_CHARS]}, *sources]
    error: str | None = None
    for _ in range(attempts):
        try:
            article = extract_article(write_fn(build_prompt(topic, sources, error, instruction, previous, skill)))
            score = fidelity(article, transcript) if transcript.strip() and not skill else 1.0
            if score < MIN_FIDELITY:
                raise WriterError(f"改动太多：正文只有 {score:.0%} 能在原话里找到，要只删口语、调顺序，不改词")
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成：{error}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "article.md"
    if previous:
        (folder / "article.prev.md").write_text(previous, encoding="utf-8")  # 上一版留一份，重写不满意还能找回
    path.write_text(article, encoding="utf-8")
    meta = {
        "topic_id": topic["id"],
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "skill": skill or ORIGINAL_WORDS,
        "sources": [{k: s[k] for k in ("path", "title", "url")} for s in sources],
        **({"instruction": instruction.strip()} if instruction.strip() else {}),
        **({"transcript_fp": transcript_fp(transcript)} if transcript.strip() else {}),
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"article_path": str(path), **meta}


def read_draft(topic: dict[str, Any]) -> dict[str, Any] | None:
    if not topic.get("article_path"):
        return None
    path = Path(topic["article_path"])
    if not path.is_file():
        return None
    meta_path = path.with_name("meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return {"markdown": path.read_text(encoding="utf-8"), "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"), **meta}
