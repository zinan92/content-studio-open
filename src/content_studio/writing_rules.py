"""优先读取已安装的写作 skill，未安装时保留旧工作流路径。"""
from pathlib import Path
import os
import re

SKILL = "park-writing"
SKILL_ENV = "CONTENT_STUDIO_WRITING_SKILL"
SKILL_DIRS = ("~/.claude/skills", "~/.codex/skills", "~/.agents/skills")
REFERENCES = "references"
LEGACY = {"一勾式骨架.md": "骨架.md", "付息稿.md": "密度.md", "标题.md": "开头.md",
          "X 发前 QA.md": "QA.md", "X 写作风格.md": "X短帖.md"}
OPENING = "开头.md"


def skill_dir() -> Path | None:
    configured = os.environ.get(SKILL_ENV)
    if configured == "off":
        return None
    candidates = [Path(configured).expanduser()] if configured else [Path(d).expanduser() / SKILL for d in SKILL_DIRS]
    for path in candidates:
        if (path / "SKILL.md").is_file() and (path / REFERENCES).is_dir():
            return path.resolve()
    return None


def references_dir() -> Path | None:
    path = skill_dir()
    return path / REFERENCES if path is not None else None


def current_path(legacy_name: str) -> Path:
    from . import outline

    references = references_dir()
    if references is not None and legacy_name in LEGACY:
        return references / LEGACY[legacy_name]
    return outline.workflows_dir() / legacy_name


def strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()
