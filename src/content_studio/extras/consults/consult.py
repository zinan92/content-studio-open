"""客户咨询录音/录像 → 转文字 + 分析 → 两份成品：给 作者 的、给客户的。

作者 9/28：做完一单 1v1 咨询，把录音（语音备忘录的 m4a）或录像丢进工作台：
- 本机留两样：原件（原件.m4a / 原件.mp4）和文字（转写.txt），都在工作目录里。
- 一个客户一个文件夹：vault 010_咨询/<客户>/，这个客户的所有东西都放这里（作者 9/28）。
- 给 作者 的：「MMDD 咨询记录.md」，最上面整场总结（含成交信号、素材、复盘），
  下面左边转写原文、右边逐段分析。
- 给客户的：「MMDD 客户版.html」和同名 PDF，只有会议纪要和 takeaway，不附转写，
  也不带任何只给 作者 看的东西（成交判断、报价策略、素材、复盘）。作者 直接发 PDF。

- 转写本机跑 mlx-whisper，原文不经模型改写：45 分钟的对话让模型整段抄一遍，
  会截断、会悄悄改字（口播那边就是这样才加了漂移守卫）。左栏永远是 whisper 的原话。
- 分析交给 claude -p：只拿编号的段落，回每段一句分析 + 整场总结，不重抄原文。
  客户版是第二次调用，拿总结和原文写给客户看的纪要。
- 每一步的结果都落在工作目录里（~/.config/content-studio/consults/<名字>/），
  中途断了重跑会跳过已完成的步骤（转写、分析、客户版各自缓存）。
- 笔记只写进空文件或工作台自己写的文件；作者 手写过内容的同名文件不覆盖，另存一份。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from ... import conf
from ...writer import cli_write

ROOT_ENV = "CONTENT_STUDIO_CONSULTS"
TRASH_ENV = "CONTENT_STUDIO_TRASH"
DEFAULT_ROOT = Path("~/.config/content-studio/consults")
FOLDER = conf.value("consult.folder")
MARKER = "generated_by: 内容工作台"
MEDIA_SUFFIXES = (".m4a", ".mp3", ".wav", ".aac", ".caf", ".mp4", ".mov", ".m4v", ".webm", ".mkv")
ORIGINAL = "原件"
TEXT_FILE = "转写.txt"
NOTE_NAME = "{day:%m%d} 咨询记录.md"
CLIENT_NAME = "{day:%m%d} 客户版"
CHUNK_SECONDS = 150
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
ANALYZE_COMMAND = (
    "claude -p --model opus --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill,Task"
)

Transcriber = Callable[[Path], list[dict[str, Any]]]
Analyzer = Callable[[str], str]


class ConsultError(RuntimeError):
    """Shown to 作者 as-is."""


# -- 工作目录与状态 --------------------------------------------------------------

def root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or DEFAULT_ROOT).expanduser()


def slug(name: str, day: date) -> str:
    clean = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name or "").strip() or "客户"
    return f"{day:%m%d}-{clean[:40]}"


def load_state(folder: Path) -> dict[str, Any]:
    try:
        return json.loads((folder / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(folder: Path, **changes: Any) -> dict[str, Any]:
    state = {**load_state(folder), **changes, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return state


def audio_of(folder: Path) -> Path | None:
    for path in sorted(folder.glob(f"{ORIGINAL}.*")) + sorted(folder.glob("audio.*")):
        if path.suffix.lower() in MEDIA_SUFFIXES:
            return path
    return None


def write_text(folder: Path, segments: list[dict[str, Any]]) -> Path:
    """本机留一份能直接看的文字：一行一句，前面是录音里的时间。"""
    path = folder / TEXT_FILE
    path.write_text("\n".join(f"[{clock(s['start'])}] {s['text']}" for s in segments) + "\n", encoding="utf-8")
    return path


# -- 转写 -------------------------------------------------------------------------

def whisper_transcriber(audio: Path) -> list[dict[str, Any]]:
    try:
        import mlx_whisper
    except ImportError as exc:
        raise ConsultError("这台机器上没有 mlx-whisper，转不了文字") from exc
    # initial_prompt 让 whisper 带标点、出简体；关掉 condition_on_previous_text，
    # 长录音才不会卡在一句话上反复输出。
    result = mlx_whisper.transcribe(
        str(audio), path_or_hf_repo=WHISPER_MODEL, language="zh", verbose=None,
        initial_prompt="以下是普通话的对话，请加上标点符号。", condition_on_previous_text=False,
    )
    return [
        {"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": (s.get("text") or "").strip()}
        for s in result.get("segments") or []
    ]


def transcribe(folder: Path, *, transcriber: Transcriber | None = None) -> list[dict[str, Any]]:
    """转过就直接读 transcript.json，不重跑。"""
    cached = folder / "transcript.json"
    if cached.is_file():
        try:
            segments = clean(json.loads(cached.read_text(encoding="utf-8")).get("segments") or [])
        except ValueError:
            segments = []
        if segments:
            if not (folder / TEXT_FILE).is_file():
                write_text(folder, segments)
            return segments
    audio = audio_of(folder)
    if not audio:
        raise ConsultError("找不到录音文件")
    segments = clean((transcriber or whisper_transcriber)(audio))
    if not segments:
        raise ConsultError("录音里没转出文字：确认一下是不是空录音")
    cached.write_text(json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8")
    write_text(folder, segments)
    return segments


def clean(segments: list[dict[str, Any]], *, max_repeat: int = 3) -> list[dict[str, Any]]:
    """去掉 whisper 在长录音上的两种幻觉循环（9/28 那场都出现过）：
    时间往回跳、两句来回刷（「where is my phone / Holy shit」×7）；同一句连刷几十遍（「嗯」×22）。"""
    out: list[dict[str, Any]] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text or seg["end"] < seg["start"] or (out and seg["start"] < out[-1]["end"] - 0.5):
            continue
        tail = out[-max_repeat:]
        if len(tail) == max_repeat and all(t["text"] == text for t in tail):
            continue
        out.append({**seg, "text": text})
    return out


def chunks(segments: list[dict[str, Any]], seconds: int = CHUNK_SECONDS) -> list[dict[str, Any]]:
    """按 whisper 的句子边界切成两三分钟一段，一段是对照表的一行。"""
    out: list[dict[str, Any]] = []
    for seg in segments:
        if not out or seg["start"] - out[-1]["start"] >= seconds:
            out.append({"i": len(out) + 1, "start": seg["start"], "end": seg["end"], "parts": []})
        out[-1]["end"] = seg["end"]
        out[-1]["parts"].append(seg["text"])
    return [{"i": c["i"], "start": c["start"], "end": c["end"], "text": _join(c["parts"])} for c in out]


def _join(parts: list[str]) -> str:
    text = ""
    for part in (re.sub(r"\s+", "，", p.strip()) for p in parts):
        if text and not re.search(r"[。！？，、；：…,.!?]$", text):
            text += "，"
        text += part
    return text


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


# -- 分析 -------------------------------------------------------------------------

def _positioning() -> str:
    try:
        text = (conf.path("standards").parent / "positioning.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return text.split("## 飞轮")[0].strip()[:4000]


def prompt(name: str, parts: list[dict[str, Any]], *, positioning: str | None = None) -> str:
    body = "\n\n".join(f"[{c['i']}] {clock(c['start'])}–{clock(c['end'])}\n{c['text']}" for c in parts)
    context = positioning if positioning is not None else _positioning()
    return f"""你在帮 作者 复盘一场刚做完的 1v1 付费咨询。客户：{name}。

下面是 作者自己的定位，用来理解他卖什么、想从咨询里得到什么（不要照抄进输出）：
<定位>
{context}
</定位>

下面是整场录音的机器转写，已经切成 {len(parts)} 段，每段前面有编号和时间。
转写没有区分说话人，有错别字和同音字；请根据上下文判断哪句是 作者、哪句是客户。

<转写>
{body}
</转写>

请严格按下面的格式输出，不要输出别的：

=== 总结 ===
（Markdown，用下面这些二级标题，顺序不变。每个判断后面用（mm:ss）标出依据在录音里的时间。
只写录音里真的说过的；客户没提的数字、价格、承诺一律不写，拿不准就写「录音里没提」。）

## 一句话
## 客户是谁
（做什么生意、做到什么程度、现在卡在哪。）
## 客户真正的问题
（他嘴上问的 vs 真正要解决的。）
## 作者 给的诊断
（作者 在对话里给出的判断和建议，按原意提炼。）
## 成交信号与下一步
（客户的需求、顾虑、预算线索、他说接下来要做什么；作者 该怎么跟进。）
## 给客户的纪要
（可以直接发给客户的 3–6 条，第二人称，不带时间标记。）
## 素材候选
（1–3 个可以拍成视频的选题：隐去客户名字、公司和可识别的细节。每个写一个标题 + 为什么值得拍。）
## 复盘提纲
（作者 录复盘视频时照着讲的 3–5 点。）
## 下次可以做得更好
（问法、节奏、漏问的地方，具体到哪一段。）

=== 逐段 ===
[1] 这一段在聊什么，以及值得注意的：客户信号、作者 的关键判断、能当素材的原话。一到三句，不超过 80 字。
[2] ……
（每一段都要有，从 [1] 写到 [{len(parts)}]，不要合并。）
"""


def cli_analyzer(text: str) -> str:
    return cli_write(text, command=os.environ.get("CONTENT_STUDIO_CONSULT_CMD") or ANALYZE_COMMAND, timeout=1800)


def parse(output: str, count: int) -> dict[str, Any]:
    match = re.search(r"===\s*总结\s*===\s*(.*?)\s*===\s*逐段\s*===\s*(.*)$", output or "", re.S)
    if not match:
        raise ConsultError("分析没有按格式返回，可以点重试")
    summary, rest = match.group(1).strip(), match.group(2)
    notes: dict[int, str] = {}
    for m in re.finditer(r"^\s*\[(\d+)\]\s*(.*?)(?=^\s*\[\d+\]|\Z)", rest, re.S | re.M):
        i = int(m.group(1))
        if 1 <= i <= count and m.group(2).strip():
            notes[i] = m.group(2).strip()
    if len(summary) < 80:
        raise ConsultError("分析的总结太短，可以点重试")
    return {"summary": summary, "notes": notes, "missing": [i for i in range(1, count + 1) if i not in notes]}


# -- 客户版 -----------------------------------------------------------------------

CLIENT_HEADINGS = ("你现在的情况", "这次聊的核心问题", "我的判断", "建议你做的", "下一步")


def client_prompt(name: str, parts: list[dict[str, Any]], summary: str) -> str:
    body = "\n\n".join(f"[{clock(c['start'])}] {c['text']}" for c in parts)
    headings = "\n".join(f"## {h}" for h in CLIENT_HEADINGS)
    return f"""作者 刚做完一场 1v1 付费咨询，现在要发给客户一份会后纪要。请你以 作者 的口吻（第一人称「我」，称客户为「你」）写。

客户：{name}（这是 作者自己写的，客户的名字以这里为准；转写里的同音字、别字不算）

下面是 作者自己的复盘总结（内部用，里面有很多**不能给客户看**的东西）和整场录音的机器转写（有错别字、没分说话人）。

<内部总结>
{summary}
</内部总结>

<转写>
{body}
</转写>

写作要求：
- 这是会议纪要 + takeaway，给客户看的。简洁、具体、能执行，读完两三分钟。
- 只写录音里真的聊过的内容。数字只用客户自己说过的，口径要准（比如客户说的是销售额，就写销售额，不要写成利润）；录音里没谈的价格、报价、承诺一律不写。
- **绝对不能出现**：对这单生意的成交判断、报价策略、「素材」「选题」「复盘」「下次改进」、对客户的内部评价、作者自己的定位宣传、任何平台引流字样。
- 不附转写原文，不写时间戳。
- 作者 答应客户要做的事，放进「下一步」的「我这边」；客户自己说要做的，放进「你那边」。

严格按下面格式输出，不要输出别的：

称呼：（客户的称呼，以上面「客户」一栏里的名字为准，例如「小李」；看不出名字就写「你好」）
标题：（一句话概括这次咨询，15 字以内）
画像：（只给 作者 内部用、不会出现在纪要里：一句话说客户做什么、多大体量，只用录音里说过的数字，例如「宁波 POD 数码印刷，年销售额 150–200 万，三四个人」）

{headings}

每个二级标题下用 2–5 条「- 」开头的要点，可以用 **加粗** 标出关键词。「下一步」下面分两组：「**我这边**」和「**你那边**」，各自再列要点。
"""


def parse_client(output: str) -> dict[str, str]:
    text = (output or "").strip()
    call = re.search(r"^称呼[:：]\s*(.+)$", text, re.M)
    title = re.search(r"^标题[:：]\s*(.+)$", text, re.M)
    portrait = re.search(r"^画像[:：]\s*(.+)$", text, re.M)
    body = text[text.find("## "):] if "## " in text else ""
    missing = [h for h in CLIENT_HEADINGS if f"## {h}" not in body]
    if not body or missing:
        raise ConsultError(f"客户版没有按格式返回（缺：{'、'.join(missing) or '正文'}），可以点重试")
    return {"call": (call.group(1).strip() if call else "你好"), "title": (title.group(1).strip() if title else "咨询纪要"), "body": body,
            "portrait": portrait.group(1).strip() if portrait else ""}


LOGO = ('<svg viewBox="0 0 120 120" width="40" height="40" aria-hidden="true">'
        '<path d="M14 66 Q30 28 48 86" fill="none" stroke="#B7B0A3" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M48 86 Q76 88 106 22" fill="none" stroke="#15171C" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="48" cy="86" r="9" fill="#E2461F"/></svg>')


def _list_breaks(text: str) -> str:
    """「**我这边**」下一行紧跟「- 」时，Markdown 不认成列表（9/28 客户版就挤成了一段），先补空行。"""
    out: list[str] = []
    for line in text.splitlines():
        if re.match(r"\s*([-*]|\d+\.)\s", line) and out and out[-1].strip() and not re.match(r"\s*([-*]|\d+\.)\s", out[-1]):
            out.append("")
        out.append(line)
    return "\n".join(out)


def to_pdf(page: Path, pdf: Path) -> Path:
    """用本机 Playwright 的 Chromium 按 A4 打印。系统 Chrome 的 --print-to-pdf 打完不退出，别用。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ConsultError("这台机器上没有 playwright，出不了 PDF") from exc
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.goto(page.resolve().as_uri())
            tab.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True)
        finally:
            browser.close()
    return pdf


def brand_logo(b: dict[str, str]) -> str:
    """客户的 logo（SVG 文件）内联进去；没配就用对勾。"""
    if b.get("logo"):
        try:
            svg = Path(b["logo"]).expanduser().read_text(encoding="utf-8")
            return re.sub(r"<svg\b", '<svg width="40" height="40" aria-hidden="true"', svg, count=1)
        except OSError:
            pass
    return LOGO


def render_client(client: dict[str, str], *, day: date, brand: dict[str, str] | None = None) -> str:
    import html

    import markdown as md

    b = brand or conf.brand()

    body = md.markdown(_list_breaks(client["body"]), extensions=["sane_lists"])
    esc = html.escape
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(client['title'])} · {esc(b['name'])}</title>
<style>
:root{{--ink:#15171C;--ink-2:#5F5A51;--stone:#B7B0A3;--red:#E2461F;--paper:#F4F1EA;--card:#FFFFFF;--line:#E4DFD4}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.75 "PingFang SC","Noto Sans SC","Hiragino Sans GB",system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
.page{{max-width:720px;margin:0 auto;padding:40px 20px 56px}}
header{{display:flex;align-items:center;gap:12px;padding-bottom:18px;border-bottom:1px solid var(--line)}}
.brand b{{display:block;font-family:"Songti SC","Noto Serif SC",serif;font-weight:900;font-size:20px;letter-spacing:.06em;line-height:1.2}}
.brand span{{font-size:12px;color:var(--ink-2);letter-spacing:.04em}}
.meta{{margin:28px 0 6px;font-size:13px;color:var(--ink-2);letter-spacing:.04em}}
h1{{font-family:"Songti SC","Noto Serif SC",serif;font-weight:900;font-size:28px;line-height:1.35;margin:0 0 18px}}
.hello{{margin:0 0 8px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 24px 18px;margin-top:18px}}
h2{{font-family:"Songti SC","Noto Serif SC",serif;font-size:19px;margin:22px 0 8px;padding-left:12px;border-left:4px solid var(--red);line-height:1.3}}
ul,ol{{margin:0;padding-left:1.25em}}
li{{margin:6px 0}}
li::marker{{color:var(--stone)}}
strong{{font-weight:700}}
p{{margin:10px 0}}
footer{{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--ink-2);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
footer b{{color:var(--ink)}}
@page{{size:A4;margin:14mm 12mm}}
@media print{{body{{background:#fff}}.page{{padding:0;max-width:none}}.card{{border:0;padding:0}}h2{{break-after:avoid}}li{{break-inside:avoid}}}}
</style>
</head>
<body>
<div class="page">
<header>{brand_logo(b)}<div class="brand"><b>{esc(b['name'])}</b><span>{esc(b['slogan'])}</span></div></header>
<div class="meta">咨询纪要 · {day.year} 年 {day.month} 月 {day.day} 日</div>
<h1>{esc(client['title'])}</h1>
<p class="hello">{esc(client['call'])}，这是我们这次聊的要点和接下来要做的事。</p>
<div class="card">
{body}
</div>
<footer><span><b>{esc(b['name'])}</b>{' · ' + esc(b['en']) if b['en'] else ''}</span><span>{esc(b['promise'])}</span></footer>
</div>
</body>
</html>
"""


# -- 笔记 -------------------------------------------------------------------------

def _cell(text: str) -> str:
    return re.sub(r"\s*\n\s*", "<br>", (text or "").strip()).replace("|", "\\|") or "—"


def render(*, name: str, day: date, audio: Path, parts: list[dict[str, Any]], analysis: dict[str, Any], client_file: str | None = None) -> str:
    duration = clock(parts[-1]["end"]) if parts else "00:00"
    client_line = f"\n> 发给客户的版本：[[{client_file}]]（只有纪要和 takeaway，不带转写；同名 HTML 也在这个文件夹）" if client_file else ""
    rows = "\n".join(
        f"| {clock(c['start'])} | {_cell(c['text'])} | {_cell(analysis['notes'].get(c['i'], ''))} |" for c in parts
    )
    return f"""---
type: consult
date: {day.isoformat()}
client: "{name}"
duration: "{duration}"
audio: "{audio}"
cssclasses: [consult]
{MARKER}
---

# {day:%m%d} · {name} · 咨询记录

> 录音 {duration}。这是给我自己看的版本：先是整场总结，「逐段对照」左边是机器转写的原话（有错字、没分说话人），右边是这一段的分析。{client_line}

{analysis['summary']}

## 逐段对照

| 时间 | 原话 | 分析 |
|:--|:--|:--|
{rows}
"""


def client_dir(vault: Path, name: str) -> Path:
    """一个客户一个文件夹，名字就是上传时写的客户名。"""
    clean = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name or "").strip() or "客户"
    return vault / FOLDER / clean


def note_path(folder: Path, day: date) -> Path:
    """空文件或工作台写过的同名文件直接写；作者 手写过的不碰，另存「… 转写」。"""
    target = folder / NOTE_NAME.format(day=day)
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if text.strip() and MARKER not in text:
            target = target.with_name(f"{target.stem} 转写.md")
    return target


# -- 客户档案 ---------------------------------------------------------------------
# 工作台「客户」页的一行 = 010_咨询/<客户>/ 一个文件夹。作者 填的来源、收费、微信名、
# 后续方案和报价存在文件夹里的「客户档案.md」frontmatter：Obsidian 里也能直接看、直接改。

PROFILE = "客户档案.md"
# 做咨询时照着过的那一页：010_咨询/诊断流程.md。作者 在 Obsidian 里改，工作台只读出来给他看。
PLAYBOOK = "诊断流程.md"
# 加微信的人问「能不能陪跑」时发的统一话术：010_咨询/统一话术.md，一条话术一个「## 标题」，工作台每条配一个复制按钮。
SCRIPTS = "统一话术.md"
PROFILE_FIELDS = ("来源", "首次咨询收费", "画像", "微信名", "后续方案", "报价")


def read_profile(home: Path) -> dict[str, str]:
    import yaml

    try:
        text = (home / PROFILE).read_text(encoding="utf-8")
    except OSError:
        return {k: "" for k in PROFILE_FIELDS}
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    data = (yaml.safe_load(match.group(1)) if match else None) or {}
    return {k: "" if data.get(k) is None else str(data.get(k)) for k in PROFILE_FIELDS}


def write_profile(home: Path, changes: dict[str, Any]) -> dict[str, str]:
    """只改 frontmatter 里这几项；正文（作者 在 Obsidian 里记的）原样保留。"""
    import yaml

    current = read_profile(home)
    current.update({k: str(v or "").strip() for k, v in changes.items() if k in PROFILE_FIELDS})
    path = home / PROFILE
    try:
        old = path.read_text(encoding="utf-8")
        body = re.sub(r"^---\n.*?\n---\n?", "", old, count=1, flags=re.S)
    except OSError:
        body = f"\n# {home.name} · 客户档案\n\n工作台「客户」页会读写上面这几项；下面随便记。\n"
    front = yaml.safe_dump({"type": "client", **current}, allow_unicode=True, sort_keys=False).strip()
    home.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return current


DOC_NAME = re.compile(r"^(\d{4}) (.+)\.(pdf|html|md)$")


def _doc_label(stem: str) -> str:
    if stem == "客户版":
        return "会议纪要"
    if stem.startswith("调研"):
        rest = stem[2:].strip()
        return f"调研报告 · {rest}" if rest else "调研报告"
    return stem


def client_files(home: Path) -> list[dict[str, Any]]:
    """按文件夹里真有的东西算：每一天发给客户的（PDF/HTML，按名字配对）和自己看的（.md）。

    作者 9/28：发给小李的是会议纪要和一份调研报告，各一个 PDF + HTML；调研报告不是流水线出的，
    所以不能只看任务记录，要扫文件夹。以后手动放进来的也算。"""
    days: dict[str, dict[str, Any]] = {}
    if not home.is_dir():
        return []
    for path in sorted(home.iterdir()):
        m = DOC_NAME.match(path.name)
        if not m or path.name == PROFILE:
            continue
        day, stem, ext = m.groups()
        entry = days.setdefault(day, {"day": day, "sent": {}, "mine": []})
        if ext == "md":
            entry["mine"].append({"label": stem, "file": path.name})
        else:
            doc = entry["sent"].setdefault(stem, {"label": _doc_label(stem), "pdf": None, "html": None})
            doc[ext] = path.name
    out = []
    for day in sorted(days, reverse=True):
        e = days[day]
        sent = sorted(e["sent"].values(), key=lambda d: (d["label"] != "会议纪要", d["label"]))
        out.append({"day": day, "sent": sent, "mine": e["mine"]})
    return out


def playbook(vault: Path, name: str = PLAYBOOK) -> dict[str, Any]:
    """诊断流程 / 统一话术那一页的原文；还没写就是空的，页面上提示去 Obsidian 建。"""
    path = vault / FOLDER / name
    markdown = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {"path": str(path), "markdown": markdown}


def clients(vault: Path) -> list[dict[str, Any]]:
    """每个客户一行：档案 + 这个客户每一场咨询（最新在前）。还在转写、没建文件夹的也列出来。"""
    base = vault / FOLDER
    rows: dict[str, dict[str, Any]] = {}
    if base.is_dir():
        for home in base.iterdir():
            if home.is_dir() and not home.name.startswith("."):
                rows[home.name] = {"name": home.name, "profile": read_profile(home), "consults": []}
    for job in jobs():
        name = client_dir(vault, job.get("name") or "").name
        row = rows.setdefault(name, {"name": name, "profile": {k: "" for k in PROFILE_FIELDS}, "consults": []})
        row["consults"].append(job)
    for row in rows.values():
        row["files"] = client_files(base / row["name"])
        latest_file = f"{datetime.now().year}-{row['files'][0]['day'][:2]}-{row['files'][0]['day'][2:]}" if row["files"] else ""
        row["latest"] = max([c.get("day") or "" for c in row["consults"]] + [latest_file])
    return sorted(rows.values(), key=lambda r: (r["latest"], r["name"]), reverse=True)


def delete_client(vault: Path, name: str) -> list[Path]:
    """删客户（作者 10/5）：010_咨询/<客户>/ 和这个客户每一场的工作目录（原件、转写）一起挪进废纸篓。
    不真删：删错了从废纸篓拿回来。"""
    home = client_dir(vault, name)
    targets = [home] if home.is_dir() else []
    targets += [root() / job["slug"] for job in jobs() if client_dir(vault, job.get("name") or "").name == home.name]
    if not targets:
        raise ConsultError("找不到这个客户")
    trash = Path(os.environ.get(TRASH_ENV) or "~/.Trash").expanduser()
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")
    moved = []
    for path in targets:
        dest = trash / f"{path.name} {stamp}"
        shutil.move(str(path), str(dest))
        moved.append(dest)
    return moved


# -- 一整趟 ---------------------------------------------------------------------

def _cached(folder: Path, name: str, make: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    path = folder / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    value = make()
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return value


def run(folder: Path, vault: Path, *, transcriber: Transcriber | None = None, analyzer: Analyzer | None = None) -> Path:
    state = load_state(folder)
    name, day = state.get("name") or folder.name, date.fromisoformat(state.get("day") or date.today().isoformat())
    ask = analyzer or cli_analyzer
    save_state(folder, stage="transcribing", error=None, pid=os.getpid())
    parts = chunks(transcribe(folder, transcriber=transcriber))
    save_state(folder, stage="analyzing", minutes=round(parts[-1]["end"] / 60))
    analysis = _cached(folder, "analysis.json", lambda: parse(ask(prompt(name, parts)), len(parts)))
    analysis["notes"] = {int(k): v for k, v in analysis["notes"].items()}
    save_state(folder, stage="client")
    client = _cached(folder, "client.json", lambda: parse_client(ask(client_prompt(name, parts, analysis["summary"]))))

    home = client_dir(vault, name)
    home.mkdir(parents=True, exist_ok=True)
    if client.get("portrait") and not read_profile(home)["画像"]:
        write_profile(home, {"画像": client["portrait"]})
    target = note_path(home, day)
    page = render_client(client, day=day)
    (folder / "客户版.html").write_text(page, encoding="utf-8")
    client_path = home / f"{CLIENT_NAME.format(day=day)}.html"
    client_path.write_text(page, encoding="utf-8")
    pdf_error = None
    try:
        to_pdf(client_path, client_path.with_suffix(".pdf"))
    except Exception as exc:  # noqa: BLE001 - PDF 出不来不挡住笔记，窗口里会显示
        pdf_error = f"客户版 PDF 没出来：{str(exc)[:160]}"
    target.write_text(render(name=name, day=day, audio=audio_of(folder) or folder, parts=parts,
                             analysis=analysis, client_file=client_path.with_suffix(".pdf").name if not pdf_error else client_path.name),
                      encoding="utf-8")
    save_state(folder, stage="done", note=str(target), client=str(client_path), pdf=None if pdf_error else str(client_path.with_suffix(".pdf")),
               error=pdf_error, missing=analysis["missing"], pid=None)
    return target


def jobs() -> list[dict[str, Any]]:
    base = root()
    if not base.is_dir():
        return []
    rows = [{"slug": d.name, **load_state(d)} for d in base.iterdir() if d.is_dir() and (d / "state.json").is_file()]
    return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)
