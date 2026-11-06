"""Three-point content QA: is this topic worth shooting?

作者 judges every topic on 痛点具象度 (is the pain concrete), 认知反差度 (does it
contradict what most people believe) and 交付可行性 (does the viewer see a real,
reachable result). Scores must cite the material or the outline; a point with no
quotable evidence is capped at 2, and thin material is reported as thin instead of
being padded to a middling score.

The full guide lives in 作者's private skill file (outside this public repo); the
workbench reads it when present and falls back to the short rubric below.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from .judge import JudgeError, JudgeLoginError, cli_judge

QA_COMMAND_ENV = "CONTENT_STUDIO_QA_CMD"
QA_GUIDE_ENV = "CONTENT_STUDIO_QA_GUIDE"
DEFAULT_GUIDE = Path("~/.claude/skills/content-qa/SKILL.md")
# 作者's own first principles, next to the rubric: why the three points are scored the way they
# are. Read-only — he hand-edits it and nothing in the workbench writes to it.
PRINCIPLES_FILE = "principles.md"
DEFAULT_QA_COMMAND = (
    "claude -p --model sonnet --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Skill"
)
POINTS = (("pain", "痛点具象度"), ("contrast", "认知反差度"), ("delivery", "交付可行性"))
MAX_GUIDE_CHARS = 9000
MAX_PRINCIPLES_CHARS = 4000
MAX_MATERIAL_CHARS = 16000

RUBRIC = """三点，每点 1–5 分：
1. 痛点具象度：观众能不能在第一句认出「这说的就是我」，而且真的难受、花钱或亏钱。5 = 具体的人、场景和损失；1 = 只是一个话题。
2. 认知反差度：能不能写出「大多数人以为 A，其实是 B」，且 B 有证据。5 = 有反差有证据；2 = 观众会说「这个我知道」；1 = 复述共识。
3. 交付可行性：观众会不会相信这件事能做成、自己也能做到。5 = 有真实结果和第一步；2 = 只有观点；1 = 要夸大才成立。
每个分数都要引用材料或提纲里的原话；引不出原话的点最多 2 分。不能编造 作者 的收益、经历或学员结果。"""

QAFn = Callable[[str], dict]


class QAError(RuntimeError):
    """The QA pass could not produce a valid verdict; the message is shown to 作者."""


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


def guide_target(path: Path | None = None) -> Path:
    return (path or Path(os.environ.get(QA_GUIDE_ENV) or DEFAULT_GUIDE)).expanduser()


def load_principles(path: Path | None = None) -> str:
    """作者's first principles, if he has written any. Missing is normal, not a failure —
    it must never fall back to RUBRIC the way a missing guide does."""
    try:
        text = (guide_target(path).parent / PRINCIPLES_FILE).read_text(encoding="utf-8")
    except OSError:
        return ""
    return _strip_frontmatter(text)[:MAX_PRINCIPLES_CHARS]


def load_guide(path: Path | None = None) -> str:
    try:
        text = guide_target(path).read_text(encoding="utf-8")
    except OSError:
        return RUBRIC
    return _strip_frontmatter(text)[:MAX_GUIDE_CHARS] or RUBRIC


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text).lower()


def build_prompt(title: str, outline_md: str, material: str, guide: str, error: str | None = None, principles: str | None = None) -> str:
    retry = f"\n\n上一次输出没有通过校验：{error}\n请修正后重新输出完整 JSON。" if error else ""
    principles = (load_principles() if principles is None else principles).strip()
    # Principles first and in their own block: they say why the rubric scores the way it does,
    # and they win where the two disagree. Precedence has to be visible in the structure.
    head = f"<原则｜作者自己定的，和下面的标准冲突时以这里为准>\n{principles}\n</原则>\n\n" if principles else ""
    return f"""下面是 作者 的内容 QA 标准。请严格按这份标准，给一条口播视频的选题和提纲打分。

{head}<标准>
{guide}
</标准>

## 选题
{title}

## 拍摄提纲
{outline_md.strip() or '（还没有提纲）'}

## 素材（作者 关联的笔记和备注）
{material.strip()[:MAX_MATERIAL_CHARS] or '（没有素材）'}

## 要求
只输出一个 JSON 对象，不要其他文字；字符串里需要引号时用「」。
- pain / contrast / delivery：各是 {{"score": 1-5 的整数, "reason": "一句话", "evidence": "提纲或素材里的原话，照抄"}}。引不出原话时 evidence 写空字符串，且 score 不能超过 2。
- thin：素材里没有任何数据、案例或结果时写 true，否则 false。
- fix：最该改的一处，一句话，具体到加哪句、删哪句或补什么素材。
- caution：不能讲过头的地方，没有就写空字符串。{retry}

## 输出格式
{{"pain": {{"score": 3, "reason": "", "evidence": ""}}, "contrast": {{"score": 3, "reason": "", "evidence": ""}}, "delivery": {{"score": 3, "reason": "", "evidence": ""}}, "thin": false, "fix": "", "caution": ""}}"""


def validate(raw: dict[str, Any], sources_text: str) -> list[str]:
    problems = []
    haystack = _norm(sources_text)
    for key, label in POINTS:
        point = raw.get(key)
        if not isinstance(point, dict):
            problems.append(f"缺少 {key}")
            continue
        score = point.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            problems.append(f"{label}的 score 必须是 1–5 的整数")
            continue
        if not str(point.get("reason") or "").strip():
            problems.append(f"{label}缺少 reason")
        evidence = _norm(str(point.get("evidence") or ""))
        if evidence and evidence[:12] not in haystack:
            problems.append(f"{label}的 evidence 必须是提纲或素材里的原话")
        if not evidence and score > 2:
            problems.append(f"{label}没有原话证据，score 不能超过 2")
    if not isinstance(raw.get("thin"), bool):
        problems.append("thin 必须是 true 或 false")
    if not str(raw.get("fix") or "").strip():
        problems.append("fix 不能为空")
    return problems


def verdict(result: dict[str, Any]) -> str:
    scores = [result[key]["score"] for key, _ in POINTS]
    if result.get("thin") and result["delivery"]["score"] <= 2:
        return "thin"
    if min(scores) <= 2:
        return "patch"
    return "go" if sum(scores) >= 12 else "patch"


def score_topic(
    title: str,
    outline_md: str,
    material: str,
    *,
    qa_fn: QAFn | None = None,
    guide: str | None = None,
    attempts: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not outline_md.strip() and not material.strip():
        raise QAError("没有提纲也没有素材，没法评")
    fn = qa_fn or (lambda prompt: cli_judge(prompt, command=os.environ.get(QA_COMMAND_ENV) or DEFAULT_QA_COMMAND, timeout=300))
    text = guide if guide is not None else load_guide()
    rules = load_principles()
    sources_text = f"{title}\n{outline_md}\n{material}"
    error: str | None = None
    for _ in range(attempts):
        try:
            raw = fn(build_prompt(title, outline_md, material, text, error, rules))
        except JudgeLoginError:
            raise
        except JudgeError as exc:
            error = str(exc)
            continue
        problems = validate(raw, sources_text)
        if not problems:
            result = {key: {"score": raw[key]["score"], "reason": str(raw[key]["reason"]).strip(), "evidence": str(raw[key].get("evidence") or "").strip()} for key, _ in POINTS}
            result.update({
                "thin": raw["thin"],
                "fix": str(raw["fix"]).strip(),
                "caution": str(raw.get("caution") or "").strip(),
                "total": sum(result[key]["score"] for key, _ in POINTS),
                "guide": "private" if text != RUBRIC else "rubric",
                "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            })
            result["verdict"] = verdict(result)
            return result
        error = "；".join(problems[:6])
    raise QAError(f"三点评分连续 {attempts} 次没通过校验，可点重评：{error}")


def save(drafts_dir: Path, topic_id: int, result: dict[str, Any]) -> None:
    folder = drafts_dir.expanduser() / f"topic-{topic_id}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "qa.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def load(drafts_dir: Path, topic_id: int) -> dict[str, Any] | None:
    try:
        return json.loads((drafts_dir.expanduser() / f"topic-{topic_id}" / "qa.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
