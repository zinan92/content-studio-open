"""骨架：暴论候选 + 论点证据 + 一句结尾。不写成稿。

作者 有完整的原文，中间怎么讲是他自己的事。他要的是三样一个人不好做的：一堆
反常识暴论候选（他挑一两个当开头）、原文拆成论点 + 证据的骨架、一句结尾。

他对上一版结尾的评价：「其实我觉得这段话里只有最后一句话有用。」所以结尾不再写成段。

规则不在代码里。它在 Anna 的工作流文件里（Obsidian，作者 随时能改），而那份文件的
每一条都来自一勾工作号真实逐字稿加点赞倍数。文件找不到就直接报错，不偷偷退回旧提示词：
作者 会以为他的修改生效了，其实没有。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from . import writing_rules

from .identity import author
from .judge import JudgeLoginError
from .writer import ARTICLE_BLOCK, DEFAULT_DRAFTS_DIR, WriteFn, WriterError, cli_write, gather_sources, topic_sources

OUTLINE_COMMAND_ENV = "CONTENT_STUDIO_OUTLINE_CMD"
WORKFLOWS_ENV = "CONTENT_STUDIO_WORKFLOWS"
# Bundled generic framework; point `anna.workflows` in profile.yaml at your own folder.
DEFAULT_WORKFLOWS = Path(__file__).resolve().parent / "examples" / "anna" / "Anna" / "workflows"
FRAMEWORK_FILE = "一勾式骨架.md"
LABEL = "骨架"
FILENAME = "skeleton.md"
DEFAULT_OUTLINE_COMMAND = (
    "claude -p --model opus --output-format text "
    '--disallowedTools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Skill"'
)
# 下游真正会读的四节：opening.thesis_for() 解析「主线」，三点评分把开头候选当反差、
# 中间骨架当痛点、结尾当交付。少一节，后面两个功能就静默降级成拿标题当主线。
SECTIONS = ("主线", "开头候选", "中间骨架", "结尾")
MIN_HOOKS = 5      # 作者 要 5–10 条挑
MIN_POINTS = 2     # 一个论点不叫骨架


def workflows_dir() -> Path:
    return Path(os.environ.get(WORKFLOWS_ENV) or DEFAULT_WORKFLOWS).expanduser()


def load_framework(root: Path | None = None) -> str:
    references = writing_rules.references_dir() if root is None else None
    if references is not None:
        bodies = []
        for name in (writing_rules.LEGACY[FRAMEWORK_FILE], writing_rules.OPENING):
            path = references / name
            try:
                body = writing_rules.strip_frontmatter(path.read_text(encoding="utf-8"))
            except OSError:
                raise WriterError(f"找不到框架文件：{path}") from None
            if name == writing_rules.OPENING:
                body = re.split(r"^##\s*标题\s*$", body, flags=re.M)[0].strip()
            if not body:
                raise WriterError(f"框架文件是空的：{path}")
            bodies.append(body)
        return "\n\n".join(bodies)
    path = (root or workflows_dir()) / FRAMEWORK_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WriterError(f"找不到框架文件：{path}") from None
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()
    if not body:
        raise WriterError(f"框架文件是空的：{path}")
    return body


def frame_sections(series_frame: str, episode_material: str) -> str:
    layers = ""
    if series_frame.strip():
        layers += f"\n\n## 这个系列的框架（第二层，和上面冲突时以这里为准）\n{series_frame}"
    if episode_material.strip():
        layers += f"\n\n## 这一集的材料（真实事实，只能用这里和素材里的事实）\n{episode_material}"
    return layers


def build_prompt(
    topic: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    framework: str,
    error: str | None = None,
    adjustments: list[str] | None = None,  # 兼容旧调用；每周复盘只用于标题和封面
    series_frame: str = "",
    episode_material: str = "",
) -> str:
    material = "\n\n".join(
        f"### 素材 {i + 1}：{s['title']}\n来源：{s['url'] or s['path']}\n\n{s['body']}" for i, s in enumerate(sources)
    ) or "（没有附带素材，根据本集材料（如有）、选题和备注写。）"
    retry = f"\n\n上一次输出有问题：{error}。请修正后重新输出。" if error else ""
    layers = frame_sections(series_frame, episode_material)
    me = author()
    return f"""你在帮 {me.name} 准备一条抖音口播视频的**骨架**。{me.channel_phrase}他对着骨架即兴讲。

**不要写成稿。** 中间怎么讲是 {me.name} 自己的事，你只给骨架。

下面是他和 Anna 定的加工框架。
**严格照着做**，它比你的写作习惯优先：

---

{framework}

---{layers}

## 选题
{topic['title']}

## 作者 的备注（可能写了这条要砸哪个数字、给谁看、结尾承接什么）
{topic.get('memo') or '（无）'}

## 素材（作者 的原始内容）
{material}

## 输出
按框架的「输出」一节写，放在单独一行的 <<<ARTICLE>>> 和单独一行的 <<<END>>> 之间。
必须有 {'、'.join(SECTIONS)} 这四节；可以在主线前面多一节「够不够成一篇」。不写口播全文，不写编辑说明或评分。
不要编造 作者 的经历、数据和收入——素材里没有的证据，写成一行具体的待办。{retry}"""


def _section(text: str, name: str) -> str:
    match = re.search(rf"^##\s*{name}\s*\n+(.+?)(?=^##\s|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def extract_outline(output: str) -> str:
    match = ARTICLE_BLOCK.search(output)
    if not match:
        raise WriterError("模型没有按格式返回")
    text = match.group(1).strip()
    if not text.startswith("#"):
        raise WriterError("缺少标题")
    for name in SECTIONS:
        if not _section(text, name).strip():
            raise WriterError(f"缺少「{name}」一节")
    hooks = _section(text, "开头候选")
    n = len(re.findall(r"^\s*(?:\d+[.、)]|[-*])\s*\S", hooks, flags=re.MULTILINE))
    if n < MIN_HOOKS:
        raise WriterError(f"开头候选要 {MIN_HOOKS}–10 条给 作者 挑，现在只有 {n} 条")
    points = re.findall(r"^###\s*论点", _section(text, "中间骨架"), flags=re.MULTILINE)
    if len(points) < MIN_POINTS:
        raise WriterError(f"中间骨架至少 {MIN_POINTS} 个论点，现在只有 {len(points)} 个")
    return text + "\n"


def write_outline(
    topic: dict[str, Any],
    *,
    vault_raw: str,
    drafts_dir: Path = DEFAULT_DRAFTS_DIR,
    write_fn: WriteFn | None = None,
    workflows: Path | None = None,
    attempts: int = 2,
    now: datetime | None = None,
    adjustments: list[str] | None = None,  # 兼容旧调用；每周复盘只用于标题和封面
    series_frame: str = "",
    episode_material: str = "",
    series_folder: str | None = None,
) -> dict[str, Any]:
    framework = load_framework(workflows)
    fn = write_fn or (lambda prompt: cli_write(prompt, command=os.environ.get(OUTLINE_COMMAND_ENV) or DEFAULT_OUTLINE_COMMAND, timeout=900))
    sources = topic_sources(vault_raw, topic, drafts_dir)
    if series_frame.strip() and not sources and not episode_material.strip():
        raise WriterError("这一集还没有材料：先说一遍，或在设置·内容框架里这个系列的「每集材料」下写几句这一集的真实事实")
    error: str | None = None
    for _ in range(attempts):
        try:
            outline = extract_outline(fn(build_prompt(topic, sources, framework=framework, error=error, series_frame=series_frame, episode_material=episode_material)))
            break
        except JudgeLoginError:
            raise
        except WriterError as exc:
            error = str(exc)
    else:
        raise WriterError(f"连续 {attempts} 次没写成：{error}")
    folder = drafts_dir.expanduser() / f"topic-{topic['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILENAME
    path.write_text(outline, encoding="utf-8")
    from . import speak

    series_folder = series_folder or (speak.load(folder) or {}).get("series") or topic.get("series")
    meta = {
        "frames": [LABEL] + ([series_folder] if series_frame.strip() and series_folder else []),
        "topic_id": topic["id"],
        "mode_label": LABEL,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "sources": [{k: s[k] for k in ("path", "title", "url")} for s in sources],
    }
    (folder / "skeleton.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"outline_path": str(path), **meta}


def read_outline(topic: dict[str, Any]) -> dict[str, Any] | None:
    """以前的 outline.md / bookend.md 照样读得出来——换写法不该让以前写的消失。"""
    if not topic.get("outline_path"):
        return None
    path = Path(topic["outline_path"])
    if not path.is_file():
        return None
    meta_path = path.with_name(path.stem + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return {
        "markdown": path.read_text(encoding="utf-8"),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "path": str(path),
        **meta,
    }
