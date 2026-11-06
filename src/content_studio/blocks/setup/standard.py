"""设置 · 内容标准：Anna 提的、他点了才记下的规则（standard.py），设置页 Skills 那一页读。"""
from __future__ import annotations

from typing import Any

from ...web import StandardBody


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = ()
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:

    @app.get("/api/standard")
    def get_standard() -> dict[str, Any]:
        from ... import standard

        path = standard.guide_path()
        return {"path": str(path), "exists": path.exists(), "rules": standard.rules()}
    @app.post("/api/standard")
    def post_standard(body: StandardBody) -> dict[str, Any]:
        """Write one rule into 作者's QA standard. The text comes from a teardown of someone
        else's video, so it is only ever written after 作者 clicks the button showing it."""
        from ... import standard

        rule = standard.add_rule(body.text, source=body.source)
        return {"rule": rule, "rules": standard.rules()}
    @app.delete("/api/standard/{rule_id}")
    def delete_standard(rule_id: str) -> dict[str, Any]:
        from ... import standard

        if not standard.remove_rule(rule_id):
            raise ValueError("这条标准已经不在了")
        return {"rules": standard.rules()}
