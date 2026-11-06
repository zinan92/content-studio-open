"""内容框架：所有视频共用第一层，系列可追加第二层。"""
from __future__ import annotations

import logging
from pathlib import Path
import re
import subprocess

from . import writing_rules

from . import outline
from .vault import parse_frontmatter

logger = logging.getLogger(__name__)
FOLDER = "系列框架"
NEW_TEMPLATE = """# 系列框架：{series_name}（第二层）

## 先展示结果
（写下这个系列先给观众看的结果。）

## 谁最适合
（写下这个系列最适合谁。）

## 操作流程
（写下这个系列的操作步骤。）

## CTA
（写下观众看完后可以做什么。）

## 每集材料
在下面用「### 集标题」分节，标题与排期中的集标题一致；每节写几句这一集的真实事实。
"""


def _allowed_path(relative: Path, root: Path) -> Path:
    references = writing_rules.references_dir()
    skill_root = references is not None and root.resolve() == references.resolve()

    def allowed_name(path: Path) -> bool:
        if skill_root and path.parts in (("开头.md",), ("骨架.md",), ("密度.md",)):
            return True
        return path.parts in (("一勾式骨架.md",), ("付息稿.md",)) or (
            len(path.parts) == 2 and path.parts[0] == FOLDER and path.suffix == ".md" and bool(path.stem.strip())
        )

    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
        raise ValueError("框架路径不合法")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("框架路径超出工作流目录")
    if not allowed_name(relative) or not allowed_name(path.resolve().relative_to(root.resolve())):
        raise ValueError("只能修改写作框架和系列框架")
    return path


def series_frame_path(series_folder: str, root: Path | None = None) -> Path:
    if not series_folder.strip() or series_folder in (".", "..") or any(c in series_folder for c in ("/", "\\", "\0")):
        raise ValueError("系列文件夹名不合法")
    return _allowed_path(Path(FOLDER) / f"{series_folder}.md", root or outline.workflows_dir())


def load_series_frame(series_folder: str | None, root: Path | None = None) -> str:
    if not series_folder:
        return ""
    path = series_frame_path(series_folder, root)
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))[1].strip()
    except FileNotFoundError:
        return ""


def episode_material(frame_text: str, episode_title: str) -> str:
    """只取「每集材料」下标题完全相同的一集，保留正文中的更低级标题。"""
    section = re.search(r"^##[ \t]+每集材料[ \t]*\r?$\n?(.*?)(?=^#{1,2}[ \t]+|\Z)",
                        frame_text, re.MULTILINE | re.DOTALL)
    if not section or not episode_title.strip():
        return ""
    episode = re.search(rf"^###[ \t]+{re.escape(episode_title.strip())}[ \t]*\r?$\n?(.*?)(?=^#{{1,3}}[ \t]+|\Z)",
                        section[1], re.MULTILINE | re.DOTALL)
    return episode[1].strip() if episode else ""


def layer_one_files(root: Path | None = None) -> list[dict]:
    references = writing_rules.references_dir() if root is None else None
    root = root or references or outline.workflows_dir()
    # 没装 park-writing 时文件名还是旧的（客户的通用版），页面上一律叫 骨架 / 密度
    entries = (("opening", "开头", "开头.md"), ("skeleton", "骨架", "骨架.md"), ("coupon", "密度", "密度.md")) if references is not None else (
        ("skeleton", "骨架", "一勾式骨架.md"), ("coupon", "密度", "付息稿.md"))
    return [{"key": key, "label": label, "file": file,
             "path": str(_allowed_path(Path(file), root).absolute()),
             "exists": _allowed_path(Path(file), root).is_file()}
            for key, label, file in entries]


def save(path: Path, text: str, root: Path | None = None) -> None:
    """path 必须是相对 root 的白名单路径；编辑内容原样写回。"""
    root = root or outline.workflows_dir()
    target = _allowed_path(path, root)
    if not text.strip():
        raise ValueError("内容是空的")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    try:
        probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return
        subprocess.run(["git", "-C", str(root), "add", "--", str(path)],
                       capture_output=True, text=True, check=True, timeout=10)
        # --only 保证不会把工作流仓库里其他已暂存的改动一起提交。
        subprocess.run(["git", "-C", str(root), "commit", "--only", "-m", f"docs: 设置里改了{target.name}", "--", str(path)],
                       capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("框架已保存，Git 记录失败：%s", exc)
