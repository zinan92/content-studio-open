"""单点功能（10/9 作者：「先把这个网页做出来，先做 10 个试试」）：/tools 一页，10 个功能各一张卡片，
填进去交给后台队列，一次跑一个，页面轮询结果。试用版没有这一块。"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent

# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = ("startup",)
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    from . import tools

    queue = tools.Queue()
    app.state.tools_queue = queue  # 测试换文件夹、直接跑队列用
    ctx.startup.append(queue.recover)

    def _call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except tools.ToolError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/tools")
    def tools_page() -> FileResponse:
        return FileResponse(HERE / "page.html", headers={"Cache-Control": "no-store"})

    # -- 风格画廊和打磨台（10/10）：要排在 /tools/{name} 前面 --
    @app.get("/tools/styles")
    def styles_page() -> FileResponse:
        return FileResponse(HERE / "gallery.html", headers={"Cache-Control": "no-store"})

    @app.get("/tools/styles.json")
    def styles_list() -> dict[str, Any]:
        from . import gallery

        return gallery.catalog()

    @app.get("/tools/styles/sample/{style_id}.webp")
    def styles_sample(style_id: str) -> FileResponse:
        from . import gallery

        path = gallery.sample_path(style_id)
        if path is None:
            raise HTTPException(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})

    @app.post("/api/tools/styles/{style_id}/review")
    def styles_review(style_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from . import gallery

        try:
            mark = gallery.review(style_id, str(body.get("verdict") or ""), str(body.get("note") or ""))
        except KeyError:
            raise HTTPException(status_code=404, detail="没有这个风格") from None
        except ValueError:
            raise HTTPException(status_code=400, detail="只能是通过、重做或撤回") from None
        return {"id": style_id, "review": mark}

    @app.get("/tools/examples/{name}")
    def tools_example(name: str) -> FileResponse:
        """10 个功能各一份真跑出来的样例（examples/，scripts/tools-examples.py 从真实运行里收进来）。"""
        path = HERE / "examples" / name
        if not re.fullmatch(r"[\w.-]+\.(json|webp|jpg|png)", name) or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/tools/videos/{name}")
    def tools_video(name: str) -> FileResponse:
        """视频样片的成片和封面，放本机 tool-videos/（videos.py），清单里有的才给。"""
        from . import videos

        path = videos.videos_dir() / name
        if name not in videos.files() or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/tools/{name}")
    def tools_asset(name: str) -> FileResponse:
        if name not in ("page.js", "page.css", "usecases.json", "videos.json", "gallery.js", "gallery.css"):
            raise HTTPException(status_code=404)
        return FileResponse(HERE / name, headers={"Cache-Control": "no-cache"})

    @app.get("/api/tools")
    def tools_list() -> dict[str, Any]:
        return {"tools": tools.catalog(), "styles": tools.STYLES, "runs": queue.runs()}

    @app.post("/api/tools/{key}/run")
    def tools_run(key: str, body: dict[str, Any]) -> dict[str, Any]:
        return _call(lambda: queue.submit(key, body))

    @app.get("/api/tools/runs/{run_id}")
    def tools_get(run_id: str) -> dict[str, Any]:
        return _call(lambda: queue.read(run_id))

    @app.get("/api/tools/runs/{run_id}/file/{rel:path}")
    def tools_file(run_id: str, rel: str) -> FileResponse:
        return FileResponse(_call(lambda: queue.file(run_id, rel)), headers={"Cache-Control": "no-store"})
