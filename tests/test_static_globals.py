"""前端的脚本都是普通 <script>，共用一个全局作用域：两个文件顶层各写一个同名 const，
后加载的那个整个文件都不执行（10/7：videoproject.js 又写了一个 mmss，加工中整页空白）。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "src/content_studio/static"
TOP = re.compile(r"^(?:const|let|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)


def test_top_level_names_are_not_declared_twice_across_scripts() -> None:
    seen: dict[str, list[str]] = defaultdict(list)
    for js in sorted(STATIC.glob("*.js")):
        for name in TOP.findall(js.read_text(encoding="utf-8")):
            seen[name].append(js.name)
    clash = {name: files for name, files in seen.items() if len(files) > 1}
    assert not clash, f"顶层同名声明会让后加载的脚本整个不跑：{clash}"
