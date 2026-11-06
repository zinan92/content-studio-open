"""动效：口播视频加动效（park-video-v2 的 pv2.py 跑渲染，这里只管设置、开始、审批和素材目录）。试用版没有这一块，剪辑进度只剩「这就是成片」。"""
from __future__ import annotations

from typing import Any
from fastapi.responses import FileResponse
from pathlib import Path
from ... import video_project
from ...web import V2ApproveBody, V2SettingsBody, V2StartBody


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ("_picked", "places", "store")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    _picked = ctx._picked
    linked_project = places.linked_project
    store = ctx.store
    video_root = places.video_root

    # -- 口播动效 v2（park-video-v2）：进度和动作都在它自己的 pv2.py 里 ------------
    def v2_project(topic_id: int) -> tuple[dict[str, Any], Path]:
        from . import video_v2

        topic, path, info = linked_project(topic_id)
        if info["layout"] != "v2" or not video_v2.is_v2(path):
            raise ValueError("这不是 v2 项目（项目里没有 v2/brief.yaml，或者是旧流程的项目）")
        return topic, path

    @app.post("/api/topics/{topic_id}/video-project/v2/approve")
    def approve_v2(topic_id: int, body: V2ApproveBody) -> dict[str, Any]:
        from . import video_v2

        topic, path = v2_project(topic_id)
        record = video_v2.approve(path, body.gate, body.message)
        return {"approval": record, "project": video_project.inspect(video_root(), topic["video_project"])}

    @app.post("/api/topics/{topic_id}/video-project/v2/start")
    def start_v2(topic_id: int, body: V2StartBody) -> dict[str, Any]:
        from . import video_v2

        topic, path = v2_project(topic_id)
        message = video_v2.start(path, body.job)
        return {"message": message, "project": video_project.inspect(video_root(), topic["video_project"])}

    @app.post("/api/topics/{topic_id}/video-project/v2/init")
    def init_v2(topic_id: int) -> dict[str, Any]:
        """「做动效」：粗剪放进项目后，转成 park-video-v2 项目。只在 作者 点了才转——不加动效的那条不碰它。"""
        from . import video_v2

        topic, path, _info = linked_project(topic_id)
        result = video_v2.init(path)
        if not result["already"]:
            store.log_event("edit", f"《{topic['title'][:24]}》开始做动效（park-video-v2）", topic_id)
        return {**result, "project": video_project.inspect(video_root(), topic["video_project"])}

    @app.get("/api/topics/{topic_id}/video-project/v2/settings")
    def v2_settings(topic_id: int) -> dict[str, Any]:
        from . import video_v2

        _topic, path = v2_project(topic_id)
        return video_v2.settings(path)

    @app.post("/api/topics/{topic_id}/video-project/v2/settings")
    def save_v2_settings(topic_id: int, body: V2SettingsBody) -> dict[str, Any]:
        from . import video_v2

        _topic, path = v2_project(topic_id)
        if body.scope not in ("project", "default"):
            raise ValueError("scope 只能是 project（这条视频）或 default（以后的默认）")
        result = video_v2.save_settings(path if body.scope == "project" else None, body.values)
        return {"result": result, "settings": video_v2.settings(path)}

    @app.get("/api/topics/{topic_id}/video-project/v2/evidence")
    def v2_evidence(topic_id: int) -> dict[str, Any]:
        """骨架页点过「要」的证据，和这条视频里现在放着的，对不对得上。"""
        from . import video_v2

        _topic, path = v2_project(topic_id)
        return video_v2.evidence_state(path, _picked(topic_id))

    @app.post("/api/topics/{topic_id}/video-project/v2/evidence")
    def put_v2_evidence(topic_id: int) -> dict[str, Any]:
        """把骨架页点过「要」的证据放进这条视频（pv2.py evidence）：方案里的截图卡只能用这些。"""
        from . import video_v2

        _topic, path = v2_project(topic_id)
        video_v2.put_evidence(path, _picked(topic_id))
        return video_v2.evidence_state(path, _picked(topic_id))

    @app.get("/api/video-v2/settings")
    def v2_default_settings() -> dict[str, Any]:
        """设置页：以后每条视频的动效默认值（不看哪个项目）。"""
        from . import video_v2

        return video_v2.settings(None)

    @app.post("/api/video-v2/settings")
    def save_v2_default_settings(body: V2SettingsBody) -> dict[str, Any]:
        from . import video_v2

        if body.scope != "default":
            raise ValueError("这里只能改以后的默认；只改一条视频去那条视频的「剪辑进度」")
        result = video_v2.save_settings(None, body.values)
        return {"result": result, "settings": video_v2.settings(None)}

    @app.get("/api/video-v2/catalog")
    def v2_catalog() -> dict[str, Any]:
        from . import video_v2

        return video_v2.catalog()

    @app.get("/api/video-v2/media/{kind}/{file}")
    def v2_media(kind: str, file: str) -> FileResponse:
        from . import video_v2

        path = video_v2.media_path(kind, file)
        return FileResponse(path, media_type="video/mp4" if file.endswith(".mp4") else "image/jpeg")

    # -- AI 排动效（10/18，照选题工作台的「视频动效」）：稿子 → 每句一个 ShotCraft 动效 → 交给 park-video-v2 ------------
    from . import director as director_mod

    app.state.motion_director = director_mod.Director()  # 测试换文件夹、换假模型用

    def _director() -> "director_mod.Director":
        return app.state.motion_director

    @app.get("/api/topics/{topic_id}/motion-plan")
    def get_motion_plan(topic_id: int) -> dict[str, Any]:
        """方案里带着排的时候用的稿子（body），页面拿它和现在的稿子比，对不上就提示「稿子改过了」。"""
        store.topic(topic_id)
        plan = _director().get(topic_id)
        return {"plan": plan, "project": bool(_v2_dir(topic_id))}

    @app.post("/api/topics/{topic_id}/motion-plan")
    def make_motion_plan(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """body.text：这条的口播稿（页面从「口播稿」页签读的那份）。同步跑，20–60 秒。"""
        store.topic(topic_id)
        plan = _director().make(topic_id, str(body.get("text") or ""))
        store.log_event("edit", f"排了动效：{len(plan['beats'])} 个镜头", topic_id)
        return {"plan": plan}

    @app.put("/api/topics/{topic_id}/motion-plan/beats/{index}")
    def swap_motion_beat(topic_id: int, index: int, body: dict[str, Any]) -> dict[str, Any]:
        return {"plan": _director().swap(topic_id, index, str(body.get("card") or ""))}

    @app.get("/api/topics/{topic_id}/motion-plan.json")
    def export_motion_plan(topic_id: int) -> dict[str, Any]:
        return _director().picks(topic_id)

    @app.post("/api/topics/{topic_id}/motion-plan/hand-off")
    def hand_off_motion_plan(topic_id: int) -> dict[str, Any]:
        path = _v2_dir(topic_id)
        if not path:
            raise ValueError("这条还没有视频项目：先把剪映导出拖进下面，点「做动效」，再交过去")
        return _director().hand_off(topic_id, path)

    def _v2_dir(topic_id: int) -> Path | None:
        try:
            _topic, path, _info = linked_project(topic_id)
        except Exception:  # noqa: BLE001 —— 没关联项目就当没有
            return None
        return path if (path / "v2").is_dir() else None
