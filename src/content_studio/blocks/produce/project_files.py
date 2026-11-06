"""加工中 · 视频项目里的文件：原片、成片按地址取（页面播放、下载用），只认项目文件夹里面的。"""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from ... import video_project
from ...video_project import VideoProjectError


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = ("places",)
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    video_root = places.video_root

    @app.get("/api/video-projects/{name}/raw/{relative:path}")
    def project_raw(name: str, relative: str):
        """按路径服务项目文件，只读。审批页里的相对地址靠它解析；视频支持拖动进度（Range）。"""
        from urllib.parse import quote

        try:
            path = video_project.raw_file(video_root(), name, relative)
        except VideoProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        kind = video_project.RAW_TYPES[path.suffix.lower()]
        headers = {"X-Content-Type-Options": "nosniff"}
        if path.suffix.lower() in {".html", ".svg"}:
            # 能跑脚本的文件一律放进隔离的源：就算在新标签页直接打开，也碰不到工作台的接口。
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups"
        if path.suffix.lower() == ".html":
            base = video_project.project_dir(video_root(), name)
            prefix = f"/api/video-projects/{quote(name)}/raw/"
            html = video_project.rewrite_local_urls(path.read_text(encoding="utf-8", errors="replace"), base, prefix)
            return Response(content=html, media_type=kind, headers=headers)
        return FileResponse(path, media_type=kind, headers=headers)
    @app.get("/api/video-projects/{name}/file")
    def video_project_file(name: str, path: str) -> Response:
        target = video_project.safe_file(video_root(), name, path)
        headers = {"Cache-Control": "no-store"}
        if path == "analysis/worktable.html":
            # The skill's own worktable keeps 作者's picks in localStorage, which a sandboxed origin cannot use.
            pass
        elif target.suffix.lower() == ".html":
            # Worktable pages need their own scripts and JSON export, but must not reach this app's API.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-downloads allow-popups"
        return FileResponse(target, headers=headers)
