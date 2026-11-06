"""Anna: the resident content editor in the workbench's right column.

Everything 作者 says inside the workbench goes to Anna. Her role, principles and
knowledge live in 作者's Obsidian vault as plain Markdown (the "soul"); the
workbench reads them on every turn so editing the file edits the person. Each
turn also carries a fresh snapshot of what 作者 is looking at (the "context"),
assembled by the web layer.

Anna reads but does not act. 10/1 作者 wanted her to look things up in his vault
when he mentions them (老师对标, 日报, 原始输出, clippings, 咨询) instead of loading
everything every turn, so she gets read-only tools (Read / Glob / Grep) on the vault
and the teardown folders, with the vault's `_secrets` and `_contact` denied.
Everything else stays off; when she wants something done she writes a `[动作]` line,
the page turns it into a button and 作者 clicks it. The workbench is reachable
through a password proxy, so a chat box that could run commands would be a shell for
anyone holding that password.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Callable

from ... import llm

ANNA_COMMAND_ENV = "CONTENT_STUDIO_ANNA_CMD"
ANNA_ROLE_ENV = "CONTENT_STUDIO_ANNA_ROLE"
ANNA_SKILL_ENV = "CONTENT_STUDIO_QA_GUIDE"
# The bundled role is a generic editor; point `anna.role` in profile.yaml at your own.
DEFAULT_ROLE = Path(__file__).resolve().parents[2] / "examples" / "anna" / "Anna.md"
DEFAULT_SKILL = Path("~/.claude/skills/content-qa/SKILL.md")
# Claude Code, logged in on this Mac: fast enough for a chat turn, resumable, no API key.
# Every tool is disabled; Anna reads the prompt and answers.
DEFAULT_ANNA_COMMAND = (
    "claude -p --model sonnet --output-format json "
    '--allowedTools "Read Glob Grep" '
    "--disallowedTools Bash,Edit,Write,WebFetch,WebSearch,NotebookEdit,Skill,Task"
)
# vault 里这些文件夹她不能读（密钥、联系人）。Read 规则同时管 Grep / Glob。
DENY_FOLDERS = ("_secrets", "_contact", ".obsidian", ".trash")
RAW_FOLDER = "003_原始输出"
KNOWLEDGE_SUFFIXES = (".md", ".txt")
MAX_KNOWLEDGE_FILE_CHARS = 12000
MAX_CONTEXT_CHARS = 24000
SCREEN_MAX = 8000  # 他屏幕上那一页的文字，最多带这么多字
TURN_TIMEOUT_SECONDS = 300  # 要翻 vault 的时候慢一点

SCOPE_LABELS = {"input": "选题", "board": "加工中", "work": "这条视频", "output": "已发出", "settings": "设置", "positioning": "定位", "consults": "咨询客户"}
# What each [动作] line may ask for; anything else is shown as text.
ACTION_KINDS = {"存进备注": "memo", "重写提纲": "outline", "拿来做": "take", "按三点评分": "qa", "记进标准": "standard", "记进定位": "positioning",
                "写进原始输出": "raw"}
RAW_BLOCK = re.compile(r"<原始输出>\s*(.*?)\s*</原始输出>", re.S)
ACTION_RE = re.compile(r"^\s*\[动作\]\s*(" + "|".join(ACTION_KINDS) + r")\s*[:：]?\s*(.*)$")

TurnFn = Callable[[str, str, str | None], dict]


class AnnaError(RuntimeError):
    """A turn could not be completed; the message is shown in the panel."""


class AnnaLoginError(AnnaError):
    """The local CLI is logged out or out of quota; retrying will not help."""


# -- soul ---------------------------------------------------------------------

def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


def load_soul(role_path: Path | None = None, skill_path: Path | None = None) -> dict[str, Any]:
    """Role file + its knowledge folder + the three-point QA skill, as one system prompt."""
    role = (role_path or Path(os.environ.get(ANNA_ROLE_ENV) or DEFAULT_ROLE)).expanduser()
    skill = (skill_path or Path(os.environ.get(ANNA_SKILL_ENV) or DEFAULT_SKILL)).expanduser()
    parts: list[str] = []
    sources: list[str] = []
    try:
        parts.append(_strip_frontmatter(role.read_text(encoding="utf-8")))
        sources.append(str(role))
    except OSError:
        parts.append("# Anna｜流量 CEO\n\n第一目标：触达对的人，让他们看得更久。你管触达：选题、内容、各平台。收入归 Wendy。你常驻内容工作台，只动嘴不动手。")
    knowledge_dir = role.with_suffix("") / "knowledge"
    if knowledge_dir.is_dir():
        for path in sorted(knowledge_dir.iterdir()):
            if path.suffix.lower() not in KNOWLEDGE_SUFFIXES or path.name.startswith("."):
                continue
            try:
                body = _strip_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if body:
                parts.append(f"## 知识：{path.stem}\n\n{body[:MAX_KNOWLEDGE_FILE_CHARS]}")
                sources.append(str(path))
    principles = skill.parent / "principles.md"
    try:
        # 作者's own first principles come before the rubric: they say why it scores that way.
        parts.append("## 作者 的内容原则（和下面的评分标准冲突时，以这里为准）\n\n" + _strip_frontmatter(principles.read_text(encoding="utf-8")))
        sources.append(str(principles))
    except OSError:
        pass
    positioning = skill.parent / "positioning.md"
    try:
        # Who 作者 is, whom he finds, what he sells. Anna reads it so 「对的人」 is never a guess.
        parts.append("## 作者 的定位（我是谁 / 怎么找到客户 / 卖什么）\n\n" + _strip_frontmatter(positioning.read_text(encoding="utf-8")))
        sources.append(str(positioning))
    except OSError:
        pass
    try:
        parts.append("## 三点评分标准\n\n" + _strip_frontmatter(skill.read_text(encoding="utf-8")))
        sources.append(str(skill))
    except OSError:
        pass
    return {"text": "\n\n---\n\n".join(parts), "sources": sources}


# 每一轮除了上面那些文件还带上的，「设置与 Skills」照这里列出来。改了她每轮读什么，这里跟着改。
ALSO = (
    "写在代码里的工作台规则：怎么回答、能出哪几种 [动作] 按钮",
    "这一页的资料：后台按你在哪一页拼的（进项、看板、这条视频的提纲、拆解报告……）",
    "你屏幕上这一页的文字：你发消息那一刻的",
    "前面聊过的：换页不换人，同一场对话接着聊",
    "需要时自己去 vault 和拆解报告里查（只读；_secrets、_contact 不能读）",
)


WORKBENCH_RULES = """## 你在内容工作台里

你是 Anna，常驻在 作者 的内容工作台右侧。作者 在工作台里说的每一句话都是对你说的，不管他在哪一页——这是一场连续的对话，他换页你不换人，前面聊过的都算数。每一轮消息里的 <工作台> 块是他此刻正在看的页面的实时资料；<他屏幕上这一页> 块是他发消息那一刻页面上显示的文字，他说「这个」「上面那个数」指的就是它。以这两块为准，不要凭记忆编造工作台里没有的数据；两块对不上时以 <工作台> 为准。他换了页，就以新页面的资料回答，但可以接着前面的话题说。

回答规则：
- 全中文，简单直接。先给一句话结论，再给依据（引用资料里的原话或数字），最后落到一个动作上。不写长篇。
- 不讨好。题不行就说不行，素材太薄就说太薄。
- 每次最多追问一个问题。
- 三点评分里「不要讲过头」标出的地方，是这条内容里还没核实的细节。你给具体台词、开场白或原话建议时，不能把这些细节讲成确定的事实或可以直接念的引语——要么保留它原来的不确定语气（比如"据你说的印象……"），要么明说这里需要先核实或补证据。不要因为一句话更有反差就把警示丢掉。
- 你能查资料，不能改东西。需要工作台做事时，在回答最后单独成行写「[动作]」，作者 会看到按钮，点了才执行。只能用下面几种，每种最多一行：
  [动作] 存进备注：<要存进这条视频备注的一句话>
  [动作] 重写提纲
  [动作] 按三点评分
  [动作] 拿来做：<新选题的标题>
  [动作] 记进标准：<一句话的判断标准>
  [动作] 记进定位：<一句话，回答"我是谁 / 怎么找到客户 / 卖什么"三问之一>
  [动作] 写进原始输出：<子目录>/<文件名>
  「重写提纲」「按三点评分」只在看着某一条视频时用；「拿来做」只在进项或加工中用；「记进标准」「记进定位」「写进原始输出」哪一页都能用。没有动作就不写。
- 「写进原始输出」：作者 让你把他的想法整理成一篇（比如要拍的一条视频）时用。整篇放在回答里的 <原始输出> 和 </原始输出> 之间，按 003_原始输出/README.md 的双版本：
  「## Section 1：原始输出」只放 作者自己说过的话（这次对话里的、或你从他笔记里查到的原话，标出处），不替他编；
  「## Section 2：处理过的输出」放你的整理（结构、要点、口播稿草稿），每个核心判断都能在 Section 1 或他的笔记里找到来源。
  子目录用 003_原始输出 下已有的（比如 自媒体、认知提升）；作者 点了按钮才会写进去，不会覆盖已有的文件。
- 在定位页，作者 问的是他是谁、在自媒体上怎么找到客户、卖给客户什么。你的任务是把他的答案逼得更窄、更具体：一想到哪个问题就想到他。用他最近的视频标题做自测——陌生人看完能不能说出他帮哪群人解决哪件事。有观点就用「记进定位」提一句，他点了才算数。不定价、不写 CTA、不替他拍板。
- 「记进标准」是把一条方法写进 作者 的三点评分标准，以后每一条内容都按它评分。只有从拆解报告或老师的内容里真的学到、以后每次都适用的判断，才值得记；一次性的点子用「存进备注」。写成一句可执行的判断（「什么情况下该怎么做」），不写成感想。这句话会原样写进文件，作者 点了才生效。
- 不给投资建议，不承诺收益，不编 作者 的经历和数据。"""


def reach_note(vault: Path | None, extra: dict[str, Path] | None = None) -> str:
    """她能查的地方：vault 顶层每个文件夹（不含不能读的）和拆解报告、流量视频。只给目录，不给内容——用到再查。"""
    lines = []
    if vault and vault.is_dir():
        for d in sorted(vault.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in DENY_FOLDERS:
                try:
                    n = sum(1 for _ in d.iterdir())
                except OSError:
                    continue
                lines.append(f"- {d} （{n} 项）")
    for label, path in (extra or {}).items():
        if path.is_dir():
            lines.append(f"- {path} （{label}）")
    if not lines:
        return ""
    return ("## 你能查的资料（只读）\n\n"
            "作者 的 Obsidian 库和工作台的拆解资料你都能用 Read / Glob / Grep 查。默认不查：<工作台> 块够用就直接答。"
            "作者 提到某个东西（某个老师、某篇日报、某个客户、他写过的某篇）或者你确实需要原文时，先用 Glob / Grep 按名字或关键词找到那一两个文件，再 Read。"
            "不要整个文件夹地读，一轮最多读五六个文件。答的时候说清楚你看的是哪个文件。"
            f"{'、'.join(DENY_FOLDERS)} 这几个文件夹不能读，也不要试。\n\n" + "\n".join(lines))


def reach_args(vault: Path | None, extra: dict[str, Path] | None = None) -> list[str]:
    """命令行参数：把这些目录加进能读的范围，vault 里的密钥、联系人文件夹拒绝。"""
    args: list[str] = []
    dirs = ([vault] if vault and vault.is_dir() else []) + [p for p in (extra or {}).values() if p.is_dir()]
    for d in dirs:
        args += ["--add-dir", str(d)]
    if vault and vault.is_dir():
        for name in DENY_FOLDERS:
            args += ["--disallowedTools", f"Read(/{(vault / name).resolve()}/**)"]
    return args


def system_prompt(soul_text: str, reach: str = "") -> str:
    return f"{soul_text}\n\n---\n\n{WORKBENCH_RULES}" + (f"\n\n{reach}" if reach else "")


# -- turns ---------------------------------------------------------------------

def screen_block(screen: str) -> str:
    """他发消息那一刻屏幕上那一页的字（前端带来的），包成一块；没有就是空串。
    10/5 作者：页面加了全网粉丝，问 Wendy 看不看得到，她说看不到——后台给的资料是代码里一条条写死的，
    页面一改就跟不上。带上屏幕，页面怎么改她们看到的就是他看到的。Anna 和 Wendy 共用。"""
    seen = re.sub(r"\n{3,}", "\n\n", (screen or "").strip())[:SCREEN_MAX]
    return f"\n\n<他屏幕上这一页>\n{seen}\n</他屏幕上这一页>" if seen else ""


def compose_user_message(context: str, message: str, *, scope_label: str, screen: str = "") -> str:
    context = context.strip()
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n（资料过长，已截断）"
    return f"<工作台 页面=\"{scope_label}\">\n{context or '（这一页没有资料）'}\n</工作台>{screen_block(screen)}\n\n作者：{message.strip()}"


def parse_reply(text: str) -> dict[str, Any]:
    """Split Anna's answer into prose and the [动作] buttons she asked for."""
    actions: list[dict[str, str]] = []
    kept: list[str] = []
    raw = RAW_BLOCK.search(text)
    draft = raw.group(1).strip() if raw else ""
    if raw:  # 整篇照样显示给他看，标签去掉
        text = text[:raw.start()] + draft + text[raw.end():]
    for line in text.strip().splitlines():
        m = ACTION_RE.match(line)
        if not m:
            kept.append(line)
            continue
        kind, arg = ACTION_KINDS[m.group(1)], m.group(2).strip()
        if kind in ("memo", "take", "standard", "raw") and not arg:
            continue
        if kind == "raw" and not draft:
            continue  # 没给整篇就没东西可写
        if not any(a["kind"] == kind and a.get("arg") == arg for a in actions):
            actions.append({"kind": kind, "label": m.group(1), "arg": arg, **({"body": draft} if kind == "raw" else {})})
    return {"text": "\n".join(kept).strip(), "actions": actions[:4]}


def _detail(stderr: str, stdout: str) -> str:
    return (stderr.strip() or stdout.strip())[-300:] or "没有输出"


def cli_turn(system: str, user: str, session_id: str | None, *, command: str | None = None, timeout: float = TURN_TIMEOUT_SECONDS,
             extra_args: list[str] | None = None) -> dict[str, Any]:
    """One turn through the local Claude Code CLI; returns {"text", "session_id"}."""
    argv = shlex.split(command or os.environ.get(ANNA_COMMAND_ENV) or DEFAULT_ANNA_COMMAND)
    argv += [*(extra_args or []), "--system-prompt", system]
    if session_id:
        argv += ["--resume", session_id]
    try:
        completed = llm.run(argv, input=user, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AnnaError(f"Anna 想了 {int(timeout)} 秒还没答完，再问一次试试") from exc
    except OSError as exc:
        raise AnnaError(f"找不到本机的 {llm.label()} 命令：{exc}") from exc
    if completed.returncode != 0:
        detail = f"{completed.stderr}\n{completed.stdout}"
        if re.search(r"authenticat|log ?in|oauth", detail, re.IGNORECASE):
            raise AnnaLoginError(f"本机 {llm.label()} 命令行没登录或登录过期：{llm.login_hint()}，再回来问")
        if re.search(r"usage limit|rate limit|limit reached|quota", detail, re.IGNORECASE):
            raise AnnaLoginError(f"本机 {llm.label()} 额度用完或被限流，稍后再问：{_detail(completed.stderr, completed.stdout)[:120]}")
        if session_id and re.search(r"session|resume|not found", detail, re.IGNORECASE):
            # The CLI forgot the session (restart, cleanup): start over rather than fail the panel.
            return cli_turn(system, user, None, command=command, timeout=timeout, extra_args=extra_args)
        raise AnnaError(f"Anna 没答上来（退出码 {completed.returncode}）：{_detail(completed.stderr, completed.stdout)}")
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {"result": completed.stdout.strip(), "session_id": session_id}
    if payload.get("is_error"):
        raise AnnaError(f"Anna 没答上来：{str(payload.get('result') or '')[:300]}")
    text = str(payload.get("result") or "").strip()
    if not text:
        raise AnnaError("Anna 没有回话，再问一次试试")
    return {"text": text, "session_id": payload.get("session_id") or session_id}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_turn(
    *,
    scope: str,
    scope_label: str,
    context: str,
    message: str,
    session_id: str | None,
    turn_fn: TurnFn | None = None,
    soul: dict[str, Any] | None = None,
    vault: Path | None = None,
    extra_dirs: dict[str, Path] | None = None,
    screen: str = "",
) -> dict[str, Any]:
    """Compose one turn and return the assistant message ready to store. screen: what is on his screen right now."""
    soul = soul or load_soul()
    system = system_prompt(soul["text"], reach_note(vault, extra_dirs))
    user = compose_user_message(context, message, scope_label=scope_label, screen=screen)
    args = reach_args(vault, extra_dirs)
    fn = turn_fn or (lambda s_, u_, sid: cli_turn(s_, u_, sid, extra_args=args))
    result = fn(system, user, session_id)
    parsed = parse_reply(result["text"])
    return {
        "role": "anna",
        "text": parsed["text"],
        "actions": parsed["actions"],
        "at": now_iso(),
        "session_id": result.get("session_id"),
        "scope": scope,
    }


def save_raw(vault: Path, target: str, body: str) -> Path:
    """Anna 整理的一篇写进 003_原始输出/<子目录>/<文件名>.md。子目录要已经存在，不覆盖已有文件。"""
    root = (vault / RAW_FOLDER).resolve()
    if not root.is_dir():
        raise AnnaError(f"vault 里没有 {RAW_FOLDER}")
    parts = [p.strip() for p in re.split(r"[/／]", target.strip()) if p.strip()]
    if not parts or not body.strip():
        raise AnnaError("没有要写的内容")
    name = re.sub(r'[\\:*?"<>|]', "", parts[-1]).removesuffix(".md")[:80] or "Anna 整理"
    folder = root
    for sub in parts[:-1]:
        cand = (folder / sub).resolve()
        if root not in cand.parents and cand != root or not cand.is_dir():
            break  # 没有这个子目录（或者想跳出去）：放在 003 根下
        folder = cand
    path = folder / f"{name}.md"
    n = 2
    while path.exists():
        path = folder / f"{name}-{n}.md"
        n += 1
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path
