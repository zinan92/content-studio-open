"""主线积木（拆积木第 3 步起）：左栏每一站一个文件夹，每个文件是这一站的一块。

进项 intake/ · 排期 plan/ · 加工中 produce/ · 平台 publish/ · 汇总 review/ · 设置 setup/。
这些每个版本都有（试用版也有），少了一块就是装坏了，当场报错。加购的在 extras/。
"""
from __future__ import annotations

from typing import Any

from ..core.blocks import mount

MODULES: tuple[str, ...] = ("produce.video", "review.summary", "setup.settings", "intake.sources", "setup.standard", "produce.project_files")


def register_all(app: Any, ctx: dict[str, Any]) -> list[str]:
    return mount(__name__, MODULES, app, ctx, optional=False)
