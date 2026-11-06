"""Opening check: does the video say its thesis within the first 15 seconds?

Reads the subtitles already in the video project (no new transcription), keeps
the first 60 seconds, and asks the model where the thesis is first stated. Timing and the
quote are checked against the subtitles in code, so the verdict cannot drift from the text.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from .judge import JudgeError, JudgeLoginError, cli_judge

OPENING_COMMAND_ENV = "CONTENT_STUDIO_OPENING_CMD"
DEFAULT_OPENING_COMMAND = (
    "claude -p --model sonnet --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)
WINDOW_SECONDS = 60
TARGET_SECONDS = 15

# The finished cut is the truth; fall back to the hook cut, then the raw recording.
SUBTITLE_CANDIDATES = (
    ("final-video.srt", "成片"),
    ("final/video.srt", "成片"),
    ("part-a-hook/subtitles.srt", "Hook 剪辑"),
    ("captions/hook.srt", "Hook 剪辑"),
    ("subtitles/source.srt", "原始录音"),
    ("transcript/master.srt", "原始录音"),
)

OpeningFn = Callable[[str], dict]


class OpeningError(RuntimeError):
    """The opening could not be scored; the message is shown to 作者."""


def find_subtitles(project: Path) -> tuple[Path, str] | None:
    for rel, label in SUBTITLE_CANDIDATES:
        path = project / rel
        if path.is_file():
            return path, label
    return None


def _seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.strip().replace(".", ",").split(":")
    secs, _, millis = rest.partition(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis or 0) / 1000


def parse_srt(text: str) -> list[dict[str, Any]]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start, _, end = lines[timing].partition("-->")
        try:
            cue = {"start": _seconds(start), "end": _seconds(end.split()[0])}
        except (ValueError, IndexError):
            continue
        cue["text"] = " ".join(lines[timing + 1:]).strip()
        if cue["text"]:
            cues.append(cue)
    return cues


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text).lower()


def thesis_for(outline_markdown: str | None, title: str) -> str:
    if outline_markdown:
        match = re.search(r"^##\s*主线\s*\n(.+?)(?=^##\s|\Z)", outline_markdown, flags=re.M | re.S)
        if match and match.group(1).strip():
            return re.sub(r"\s+", " ", match.group(1)).strip()[:300]
    return title


def build_prompt(thesis: str, cues: list[dict[str, Any]], error: str | None = None) -> str:
    lines = "\n".join(f"[{c['start']:.1f}s] {c['text']}" for c in cues)
    retry = f"\n\n上一次输出没有通过校验：{error}\n请修正后重新输出完整 JSON。" if error else ""
    return f"""你在帮 作者 检查口播视频的开头。他的观众平均只看 14–26 秒，所以前 {TARGET_SECONDS} 秒必须直接说出这条视频的主线。

## 这条视频的主线（来自拍摄提纲）
{thesis}

## 视频前 {WINDOW_SECONDS} 秒的字幕（方括号是开始秒数）
{lines}

## 要求
只输出一个 JSON 对象，不要其他文字；字符串里需要引号时用「」。
- stated_at：观众第一次听到主线「结论本身」的那句字幕的开始秒数（照抄方括号里的数字）。只抛出话题或问题（比如「今天聊聊……有什么区别」）不算，必须说出主张；意思对上即可，不要求字面一样。前 {WINDOW_SECONDS} 秒都没说出主张就写 null。
- quote：那句字幕原文（可以是连续几句拼起来），stated_at 为 null 时写空字符串。
- before：主线出来之前在讲什么，一句话（寒暄、日期、背景铺垫……）；开门见山就写空字符串。
- fixes：1–3 条改法，每条具体到「删掉哪句」「把哪句提到最前面」或「第一句改成……」。只能用字幕里已经有的话，或者明确标注「需要补录」。{retry}

## 输出格式
{{"stated_at": 0.0, "quote": "", "before": "", "fixes": []}}"""


def validate(raw: dict[str, Any], cues: list[dict[str, Any]]) -> list[str]:
    problems = []
    stated = raw.get("stated_at")
    if stated is not None:
        if not isinstance(stated, (int, float)) or not any(abs(c["start"] - stated) < 0.05 for c in cues):
            problems.append("stated_at 必须是字幕里某一句的开始秒数")
        quote = _norm(str(raw.get("quote") or ""))
        if not quote or quote[:12] not in _norm("".join(c["text"] for c in cues)):
            problems.append("quote 必须是字幕原文")
    fixes = raw.get("fixes")
    if not isinstance(fixes, list) or not 1 <= len(fixes) <= 3 or not all(str(f).strip() for f in fixes):
        problems.append("fixes 需要 1–3 条")
    return problems


def score_opening(
    project: Path,
    *,
    thesis: str,
    opening_fn: OpeningFn | None = None,
    attempts: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    found = find_subtitles(project)
    if found is None:
        raise OpeningError("项目里还没有字幕文件：录完把粗剪和字幕放进项目文件夹，或者先跑到 Step 4")
    path, label = found
    from . import icloud

    try:
        icloud.ensure_local(path)
    except icloud.NotLocalError as exc:
        raise OpeningError(str(exc)) from None
    cues = [c for c in parse_srt(path.read_text(encoding="utf-8", errors="replace")) if c["start"] < WINDOW_SECONDS]
    if not cues:
        raise OpeningError(f"{path.name} 里读不到前 {WINDOW_SECONDS} 秒的字幕")
    fn = opening_fn or (lambda prompt: cli_judge(prompt, command=os.environ.get(OPENING_COMMAND_ENV) or DEFAULT_OPENING_COMMAND, timeout=300))
    error: str | None = None
    for _ in range(attempts):
        try:
            raw = fn(build_prompt(thesis, cues, error))
        except JudgeLoginError:
            raise
        except JudgeError as exc:
            error = str(exc)
            continue
        problems = validate(raw, cues)
        if not problems:
            stated = raw.get("stated_at")
            return {
                "passed": stated is not None and stated <= TARGET_SECONDS,
                "stated_at": stated,
                "quote": str(raw.get("quote") or "") if stated is not None else "",
                "before": str(raw.get("before") or ""),
                "fixes": [str(f) for f in raw["fixes"]],
                "thesis": thesis,
                "first_15s": " ".join(c["text"] for c in cues if c["start"] < TARGET_SECONDS),
                "source": str(path.relative_to(project)),
                "source_label": label,
                "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            }
        error = "；".join(problems)
    raise OpeningError(f"开头检查连续 {attempts} 次没通过校验，可点重试：{error}")


def save(drafts_dir: Path, topic_id: int, result: dict[str, Any]) -> None:
    folder = drafts_dir.expanduser() / f"topic-{topic_id}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "opening.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def load(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    path = drafts_dir.expanduser() / f"topic-{topic_id}" / "opening.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
