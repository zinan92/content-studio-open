"""标题候选：按 Anna 的「标题」工作流出 6–10 条，作者 挑。

同一个标题问题问不同的 agent，答案各不一样。标题该有一套标准，而不是看问的是谁。

标准不在代码里，在 Anna 的工作流文件「标题.md」（Obsidian，作者 随时能改）。
代码只管查得出来的事：条数、数字有没有出处、视频里点了名的人至少有一条借力候选
把名字放进去；超过抖音标题字数的标出来，不退回。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from . import writing_rules

from .copypack import PLATFORMS
from .judge import JudgeLoginError
from .outline import DEFAULT_OUTLINE_COMMAND, OUTLINE_COMMAND_ENV, workflows_dir
from .writer import ARTICLE_BLOCK, DEFAULT_DRAFTS_DIR, WriteFn, WriterError, cli_write

FRAMEWORK_FILE = "标题.md"
FILENAME = "titles.json"
MIN_TITLES, MAX_TITLES = 6, 10
# 10/2 作者：只有抖音有话题，视频号、小红书都没有。出标题时顺便按内容出一批话题，各平台都带。
MIN_TAGS, MAX_TAGS, TAG_MAX = 3, 8, 12
TITLE_MAX = PLATFORMS["douyin"]["title"]
BORROW = "借力点名"
CANDIDATES = "(?:标题)?候选"
MATERIAL_CAP = 14000  # 15 分钟口播的转写大约一万字；再长就截，标题用不着看全
LINE = re.compile(r"^\s*\d+\s*[.、)）]\s*(?P<title>.+?)\s*[｜|]\s*(?P<pattern>[^｜|]+?)\s*[｜|]\s*(?:依据\s*[:：])?\s*(?P<basis>.+?)\s*$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def load_framework(root: Path | None = None) -> str:
    path = root / FRAMEWORK_FILE if root is not None else writing_rules.current_path(FRAMEWORK_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WriterError(f"找不到标题工作流：{path}") from None
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()
    if not body:
        raise WriterError(f"标题工作流是空的：{path}")
    return body


def srt_text(path: Path) -> str:
    """SRT 去掉序号和时间轴，只留字。"""
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        lines.append(line)
    return "".join(lines)


def build_prompt(topic: dict[str, Any], *, framework: str, transcript: str, skeleton: str, error: str | None = None,
                 adjustments: list[str] | None = None) -> str:
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    adjust = "\n".join(f"- {a}" for a in (adjustments or []))
    adjust_block = f"\n\n## 最近一次每周复盘定下的调整（只管标题和封面）\n{adjust}" if adjust else ""
    return f"""你在帮 作者 给一条已经拍完的抖音口播视频出标题候选。

下面是他和 Anna 定的标题标准。**严格照着做**，它比你的写作习惯优先：

---

{framework}

---

## 选题
{topic['title']}

## 作者 的备注
{topic.get('memo') or '（无）'}

## 拍摄骨架
{skeleton or '（没有）'}

## 视频原话（转写）
{transcript[:MATERIAL_CAP] or '（没有转写，只根据选题、备注和骨架出）'}{adjust_block}

## 输出
只出标题，不出开头候选。放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间，按这个格式：

## 点名的人
原文里点名提到的人或产品，用顿号隔开；没点名就写「无」

## 标题候选
1. 标题｜句式｜依据：「原文里的那一句」

{MIN_TITLES}–{MAX_TITLES} 条，每条一行，每条不超过 {TITLE_MAX} 个字。不写解释、不写推荐哪条。

在同一块的最后再加一节「## 话题」：{MIN_TAGS + 2}–{MAX_TAGS} 个内容话题，用中文逗号隔开，不带 #，每个不超过 {TAG_MAX} 个字。
话题说的是这条视频讲什么、谁会搜（例如：自媒体变现，咨询，个人IP），只用视频里真的讲到的东西；
不要写平台活动、扶持计划这类流量话题（那些 作者 在设置里按平台填）。{retry}"""


def _section(text: str, name: str) -> str:
    match = re.search(rf"^##\s*{name}\s*\n+(.+?)(?=^##\s|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def parse(output: str, *, material: str) -> dict[str, Any]:
    """拆出点名的人和候选，查条数、长度、数字出处、借力。"""
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回")
    text = match.group(1)
    named = _section(text, "点名的人")
    people = [] if not named or named.startswith("无") else [p.strip() for p in re.split(r"[、，,\n]+", named) if p.strip() and not p.strip().startswith("（")]
    # 10/20 park-writing 的「开头.md」把这一节叫「标题候选」，旧工作流叫「候选」，两个都认；「开头候选」不算
    section = _section(text, CANDIDATES)
    if not section:
        raise WriterError("没有「## 标题候选」这一节")
    candidates = []
    for line in section.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        title = m["title"].strip().strip("「」\"")
        candidates.append({"title": title, "pattern": m["pattern"].strip(), "basis": m["basis"].strip()})
    if not MIN_TITLES <= len(candidates) <= MAX_TITLES:
        raise WriterError(f"要 {MIN_TITLES}–{MAX_TITLES} 条候选，现在是 {len(candidates)} 条")
    # 超长不退回：9/23 作者 选的那条就是 31 字。标出来，让他在发布前自己决定删哪个字。
    for c in candidates:
        c["over"] = len(c["title"]) > TITLE_MAX
    made_up = [c["title"] for c in candidates if any(n not in material for n in NUMBER.findall(c["title"]))]
    if made_up:
        raise WriterError(f"这几条里的数字原文里没有：{'；'.join(made_up)}")
    if people:
        borrowed = [c for c in candidates if BORROW in c["pattern"] and any(p.lower() in c["title"].lower() for p in people)]
        if not borrowed:
            raise WriterError(f"视频里点名了 {'、'.join(people)}，至少要一条「{BORROW}」把名字放进标题")
    tags = []
    for raw in re.split(r"[，,、\n]+", _section(text, "话题")):
        tag = raw.strip().lstrip("#").strip()
        if tag and len(tag) <= TAG_MAX and tag not in tags:
            tags.append(tag)
    # 话题是顺带的：没给或者太少不退回，标题照样能用
    return {"people": people, "candidates": candidates, "tags": tags[:MAX_TAGS] if len(tags) >= MIN_TAGS else []}


def write_titles(
    topic: dict[str, Any],
    *,
    transcript: str = "",
    skeleton: str = "",
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn | None = None,
    workflows: Path | None = None,
    attempts: int = 2,
    now: datetime | None = None,
    adjustments: list[str] | None = None,
) -> dict[str, Any]:
    framework = load_framework(workflows)
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(OUTLINE_COMMAND_ENV) or DEFAULT_OUTLINE_COMMAND, timeout=600))
    material = "\n".join([topic["title"], topic.get("memo") or "", skeleton, transcript])
    error: str | None = None
    for _ in range(attempts):
        try:
            result = parse(fn(build_prompt(topic, framework=framework, transcript=transcript, skeleton=skeleton, error=error, adjustments=adjustments)), material=material)
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没出成：{error}")
    result = {
        "topic_id": topic["id"],
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "had_transcript": bool(transcript),
        **result,
    }
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILENAME).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def read_titles(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    path = drafts_dir.expanduser() / f"topic-{topic_id}" / FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
