"""积木怎么挂：主线积木（blocks/）和加购积木（extras/）共用。

每块在文件开头写 NEEDS（从主线拿什么，主线给的全在 web.BLOCK_API）和 PROVIDES（递给后面
哪几块用）。没写进 NEEDS 的拿不到、没写进 PROVIDES 的递不出去，当场报错——谁靠谁一眼看得见。
"""
from __future__ import annotations

import importlib
from typing import Any


class BlockContext:
    """一块积木看得到的主线：只有它写进 NEEDS 的；只能把写进 PROVIDES 的递给后面的积木。"""

    def __init__(self, block: str, shared: dict[str, Any], needs: tuple[str, ...], provides: tuple[str, ...]) -> None:
        object.__setattr__(self, "_block", block)
        object.__setattr__(self, "_shared", shared)
        object.__setattr__(self, "_needs", frozenset(needs))
        object.__setattr__(self, "_provides", frozenset(provides))

    def __getattr__(self, name: str) -> Any:
        if name not in self._needs:
            raise AttributeError(f"积木 {self._block} 要用 {name}，但没写进它的 NEEDS")
        try:
            return self._shared[name]
        except KeyError:
            raise AttributeError(f"积木 {self._block} 要的 {name} 主线没给（web.BLOCK_API），前面的积木也没递过来") from None

    def __setattr__(self, name: str, value: Any) -> None:
        if name not in self._provides:
            raise AttributeError(f"积木 {self._block} 要递出 {name}，但没写进它的 PROVIDES")
        self._shared[name] = value


def mount(package: str, modules: tuple[str, ...], app: Any, shared: dict[str, Any], *, optional: bool) -> list[str]:
    """照顺序挂上 package 下的每一块。optional：文件不在就当没有这一块（加购积木）；否则少了就报错。
    shared 是主线给的东西，也装着前面几块递出来的——同一个 dict，主线积木递的加购积木也拿得到。"""
    loaded = []
    for name in modules:
        try:
            mod = importlib.import_module(f"{package}.{name}")
        except ModuleNotFoundError as exc:
            full = f"{package}.{name}"
            # 整个文件夹不在（试用版删掉了 extras/team）或只少了 routes.py，都算没有这一块；它里面 import 别的东西失败照样报
            if optional and exc.name and exc.name.startswith(package + ".") and (full == exc.name or full.startswith(exc.name + ".")):
                continue
            raise
        mod.register(app, BlockContext(name, shared, getattr(mod, "NEEDS", ()), getattr(mod, "PROVIDES", ())))
        loaded.append(name)
    return loaded
