"""本地风格目录，只读数据，不调用生成服务。

load_all / by_function 只返回风格，grammars 单独返回解说语法；get 同时查两者。
首次读取后缓存到进程结束，返回深拷贝，调用方修改不会污染缓存。
validate 每次重新读磁盘，收集问题而不因单个坏文件提前退出。
prompt 只约定替换 {topic} / {script}，不要用 str.format 解释原文的其他大括号。
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path, PurePosixPath
import re


DATA_DIR = Path(__file__).with_suffix("")
SOURCE_FILES = (
    "huashu-art-motion.json", "opus-videos.json", "ai-motion.json",
    "mg-styles.json", "handraw.json", "gpt-image.json",
)
_FUNCTIONS = ("image", "video", "motion")
_ASPECTS = (None, "1:1", "3:4", "4:3", "9:16", "16:9")
_FIELDS = (
    "id", "function", "category", "name", "name_en", "summary", "prompt",
    "inputs", "aspect", "path", "preview", "attribution", "status", "needs", "listed",
)
_HANDRAW_ATTRIBUTION = "handraw-style by yang0 (https://github.com/yang0/handraw-style)"


@lru_cache(maxsize=1)
def _catalog() -> tuple[list[dict], list[dict]]:
    styles: list[dict] = []
    syntax: list[dict] = []
    for filename in SOURCE_FILES:
        data = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
        styles.extend(data["styles"])
        syntax.extend(data.get("grammars", []))
    return styles, syntax


def load_all() -> list[dict]:
    """按来源及来源内部顺序返回全部风格，不含语法。"""
    return deepcopy(_catalog()[0])


def by_function(fn: str) -> list[dict]:
    """返回 image / video / motion 风格；未知功能返回空列表。"""
    return deepcopy([style for style in _catalog()[0] if style["function"] == fn])


def get(style_id: str) -> dict | None:
    """以全局 ID 查风格或语法；不存在时返回 None。"""
    for group in _catalog():
        for style in group:
            if style["id"] == style_id:
                return deepcopy(style)
    return None


def grammars() -> list[dict]:
    """返回花叔的解说语法，不与艺术风格展开组合。"""
    return deepcopy(_catalog()[1])


def _relative_path(value: object) -> bool:
    return (
        isinstance(value, str) and bool(value.strip())
        and not PurePosixPath(value).is_absolute()
        and ".." not in PurePosixPath(value).parts
        and ":" not in value and "\\" not in value
    )


def validate() -> list[str]:
    """逐文件、逐条返回全部结构问题；needs 表示待补资料，不豁免字段结构。"""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for filename in SOURCE_FILES:
        try:
            data = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{filename}: 无法读取 JSON: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{filename}: 根节点必须是对象")
            continue
        source = data.get("source")
        if not isinstance(source, dict):
            errors.append(f"{filename}: source 缺失或不是对象")
            source = {}
        for field in ("repo", "license", "url"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"{filename}: source.{field} 缺失或为空")
        if "attribution" not in source:
            errors.append(f"{filename}: source.attribution 缺失")
        elif source["attribution"] is not None and not isinstance(source["attribution"], str):
            errors.append(f"{filename}: source.attribution 必须是字符串或 null")
        handraw = filename == "handraw.json" or source.get("repo") == "yang0/handraw-style"
        if handraw and source.get("attribution") != _HANDRAW_ATTRIBUTION:
            errors.append(f"{filename}: handraw source.attribution 缺少指定署名")
        if data.get("function") not in _FUNCTIONS:
            errors.append(f"{filename}: function 必须是 image / video / motion")
        if filename == "huashu-art-motion.json" and "grammars" not in data:
            errors.append(f"{filename}: 缺少 grammars")
        if filename != "huashu-art-motion.json" and "grammars" in data:
            errors.append(f"{filename}: grammars 只允许花叔来源提供")

        for group in ("styles", "grammars"):
            if group == "grammars" and group not in data:
                continue
            rows = data.get(group)
            if not isinstance(rows, list):
                errors.append(f"{filename}: {group} 缺失或不是数组")
                continue
            for position, style in enumerate(rows):
                where = f"{filename}:{group}[{position}]"
                if not isinstance(style, dict):
                    errors.append(f"{where}: 条目必须是对象")
                    continue
                for field in _FIELDS:
                    if field not in style:
                        errors.append(f"{where}: 缺少字段 {field}")
                ident = style.get("id")
                if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", ident):
                    errors.append(f"{where}: id 格式不对")
                if isinstance(ident, str):
                    if ident in seen:
                        errors.append(f"{where}: id 重复 {ident}（首次在 {seen[ident]}）")
                    else:
                        seen[ident] = where
                fn = style.get("function")
                expected = "grammar" if group == "grammars" else data.get("function")
                if fn not in (_FUNCTIONS if group == "styles" else ("grammar",)) or fn != expected:
                    errors.append(f"{where}: function 与 {group} / 来源不符")
                needs = style.get("needs")
                if not isinstance(style.get("listed"), bool):
                    errors.append(f"{where}: listed 必须是布尔值")
                if style.get("listed") is True and needs != []:
                    errors.append(f"{where}: listed 为 true 时 needs 必须为空")
                if not isinstance(needs, list) or any(not isinstance(item, str) or not item.strip() for item in needs):
                    errors.append(f"{where}: needs 必须是非空字符串的数组")
                    needs = []
                for field in ("category", "name", "name_en", "summary", "prompt"):
                    value = style.get(field)
                    if not isinstance(value, str):
                        errors.append(f"{where}: {field} 必须是字符串")
                    elif not value.strip() and field not in needs:
                        errors.append(f"{where}: {field} 为空且 needs 未注明")
                summary = style.get("summary")
                if isinstance(summary, str) and len(summary) > 40:
                    errors.append(f"{where}: summary 超过 40 字")
                token = "topic" if fn == "image" else "script"
                prompt = style.get("prompt")
                if style.get("listed") is True and (not isinstance(prompt, str) or "{" + token + "}" not in prompt):
                    errors.append(f"{where}: listed 为 true 时 prompt 必须包含 {{{token}}}")
                if isinstance(prompt, str) and "{" + token + "}" not in prompt and "prompt" not in needs:
                    errors.append(f"{where}: prompt 没有 {{{token}}} 且 needs 未注明 prompt")
                if style.get("inputs") != [token]:
                    errors.append(f"{where}: inputs 必须是 [{token!r}]")
                if style.get("aspect") not in _ASPECTS:
                    errors.append(f"{where}: aspect 不在允许值中")
                if not _relative_path(style.get("path")):
                    errors.append(f"{where}: path 必须是原仓库相对路径")
                if style.get("preview") is not None and not _relative_path(style["preview"]):
                    errors.append(f"{where}: preview 必须是原仓库相对路径或 null")
                attribution = style.get("attribution")
                if attribution is not None and not isinstance(attribution, str):
                    errors.append(f"{where}: attribution 必须是字符串或 null")
                if handraw and attribution != _HANDRAW_ATTRIBUTION:
                    errors.append(f"{where}: handraw attribution 缺少指定署名")
                if style.get("status") != "draft":
                    errors.append(f"{where}: status 必须是 draft")
    return errors
