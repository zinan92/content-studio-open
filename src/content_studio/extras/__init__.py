"""加购积木（10/8）：每个文件夹是一块能整块拿掉的功能——接口在 routes.py，用到的业务模块也在这个文件夹里。

create_app 最后照 MODULES 的顺序挂上；文件不在就当没有这一块——content-studio-trial 就是把
整个 extras/ 删掉剪出来的（见 edition.py 和 scripts/build-trial.py）。每块只有一个入口
register(app, ctx)：app 是 FastAPI，ctx 是这一块看得到的主线。

每块开头写 NEEDS / PROVIDES，怎么核对见 core/blocks.py。
"""
from __future__ import annotations

from typing import Any

from ..core.blocks import BlockContext, mount

MODULES: tuple[str, ...] = ("portal", "products", "dailies", "xline", "positioning", "team", "proof", "motion", "consults", "series", "autopost", "tools", "materials", "tree", "moments")


def register_all(app: Any, ctx: dict[str, Any]) -> list[str]:
    """挂上找得到的每一块，返回挂上了哪些。ctx 是主线给积木的那些东西（名字 → 值）。"""
    return [name.removesuffix(".routes") for name in mount(__name__, tuple(f"{m}.routes" for m in MODULES), app, ctx, optional=True)]
