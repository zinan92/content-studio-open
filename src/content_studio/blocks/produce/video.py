"""加工中 · 剪辑进度：视频项目（建、关联、导入剪映导出）、成片 → 字幕 → 标 Hook 的工作台、后台跑流程和审批门。"""
from __future__ import annotations

import json
import os
import threading
from typing import Any
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from datetime import date
from ... import video_project
from ...store import now_iso
from ...video_project import VideoProjectError
from ...web import ApproveBody, DropBody, VideoLinkBody, logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（core/blocks.py 当场核对）
NEEDS: tuple[str, ...] = ("places", "runner_command", "runs_dir", "store", "writing", "writing_lock")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    runner_command = ctx.runner_command
    runs_dir = ctx.runs_dir
    store = ctx.store
    writing = ctx.writing
    writing_lock = ctx.writing_lock
    _koubo_dir = places.project_dir
    linked_project = places.linked_project
    video_root = places.video_root

    @app.get("/api/video-projects")
    def list_video_projects() -> dict[str, Any]:
        try:
            root = video_root()
        except VideoProjectError as exc:
            return {"root": store.settings()["video_projects_root"] or str(video_project.DEFAULT_ROOTS[0]), "error": str(exc), "projects": []}
        linked = {t["video_project"]: t["id"] for t in store.topics(include_archived=True) if t.get("video_project")}
        return {"root": str(root), "error": None, "projects": [{**p, "topic_id": linked.get(p["name"])} for p in video_project.list_projects(root)]}

    @app.get("/api/topics/{topic_id}/video-project")
    def topic_video_project(topic_id: int) -> dict[str, Any]:
        topic = store.topic(topic_id)
        if not topic.get("video_project"):
            raise HTTPException(status_code=404, detail="这个选题还没有关联视频项目")
        return video_project.inspect(video_root(), topic["video_project"])

    @app.put("/api/topics/{topic_id}/video-project")
    def link_video_project(topic_id: int, body: VideoLinkBody) -> dict[str, Any]:
        store.topic(topic_id)
        if body.name:
            video_project.project_dir(video_root(), body.name)
        topic = store.update_topic(topic_id, video_project=body.name or None)
        if body.name:
            _video_in(topic_id)
        return topic

    def _new_project(topic_id: int) -> str:
        from ... import outline

        topic = store.topic(topic_id)
        draft = outline.read_outline(topic)
        name = video_project.create_project(
            video_root(), title=topic["title"], today=date.today().isoformat(), outline_markdown=draft["markdown"] if draft else None
        )
        store.update_topic(topic_id, video_project=name)
        return name

    @app.post("/api/topics/{topic_id}/video-project")
    def create_video_project(topic_id: int) -> dict[str, Any]:
        if store.topic(topic_id).get("video_project"):
            raise ValueError("这个选题已经关联了视频项目")
        return video_project.inspect(video_root(), _new_project(topic_id))

    # -- Step 3–4：成片 → 字幕 → 可以标 Hook 的工作台 ---------------------

    _koubo_dir = places.project_dir

    @app.get("/api/topics/{topic_id}/video-project/media")
    def koubo_media(topic_id: int) -> dict[str, Any]:
        from ... import koubo

        return koubo.state(_koubo_dir(topic_id))

    @app.post("/api/topics/{topic_id}/video-project/init")
    def koubo_init(topic_id: int) -> dict[str, Any]:
        """补一份 project.json。没有它，14 步进度算不出来，「开始跑」也会被拒。"""
        from ... import koubo

        data = koubo.init_project(_koubo_dir(topic_id))
        store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》的项目初始化好了，可以按 14 步跑", topic_id)
        return {"presets": data["presets"], "message": "project.json 写好了，现在可以按 14 步跑"}

    @app.post("/api/topics/{topic_id}/video-project/skip-hook")
    def koubo_skip_hook(topic_id: int) -> dict[str, Any]:
        """这条不剪 Hook。

        Hook 那四步存在的唯一理由，是补救一个不够抓人的开头。骨架里已经给了暴论候选，
        录的时候第一句就说它，这四步就没必要了。
        """
        from ... import koubo

        base = _koubo_dir(topic_id)
        changed = koubo.skip_hook(base)
        store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》这条不剪 Hook，直接进正文", topic_id)
        return {"steps": changed, "message": "记下了：这条不剪 Hook，Step 5/7/8/9 跳过"}

    @app.post("/api/topics/{topic_id}/video-project/external")
    def koubo_external(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """在外面做完的：Hook（给出剪好的 Hook 视频）或整条（成片已在 final/ 或给出路径）。"""
        from ... import koubo

        what = str(payload.get("what") or "")
        raw = str(payload.get("path") or "").strip()
        base = _koubo_dir(topic_id)
        try:
            result = koubo.mark_external(base, what, source=Path(raw) if raw else None)
        except koubo.KouboError as exc:
            raise ValueError(str(exc)) from None
        title = store.topic(topic_id)["title"][:24]
        store.log_event("edit", f"《{title}》{'Hook' if what == 'hook' else '整条'}在外面做完了，已记下", topic_id)
        return {**result, "message": "记下了：Hook 在外面剪好了" if what == "hook" else "记下了：整条在外面做完了，可以去打包"}

    @app.put("/api/topics/{topic_id}/video-project/spec")
    def koubo_spec(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """作者 从剪映导出后手动选的剪辑规格：Hook、字幕、版式、背景音乐、音效。"""
        from ... import koubo

        try:
            spec = koubo.set_spec(_koubo_dir(topic_id), {k: v for k, v in payload.items() if v is not None})
        except koubo.KouboError as exc:
            raise ValueError(str(exc)) from None
        return {"spec": spec}

    @app.put("/api/topics/{topic_id}/video-project/visual-target")
    def koubo_visual_target(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        from ... import koubo

        try:
            top = payload.get("max")
            value = koubo.set_visual_target(_koubo_dir(topic_id), float(payload.get("percent")),
                                            None if top in (None, "") else float(top))
        except (koubo.KouboError, TypeError, ValueError) as exc:
            raise ValueError(str(exc) or "比例要是一个数") from None
        text = f"{round(value * 100)}%" if top in (None, "") or float(top) == value * 100 else f"{round(value * 100)}–{round(float(top))}%"
        return {"visual_target": value, "message": f"记下了：动效占正文 {text}"}

    @app.get("/api/topics/{topic_id}/video-project/activity")
    def koubo_activity(topic_id: int) -> dict[str, Any]:
        """谁在这个项目里干活、最后写了什么、这一步做了多久。不管是工作台、Codex 还是 Claude 在跑。"""
        from ... import activity

        _topic, path, info = linked_project(topic_id)
        contract_path = path / "project.json"
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.is_file() else {}
        except (OSError, ValueError):
            contract = {}
        return activity.activity(path, contract=contract, current=info.get("current_step"),
                                 gate=info.get("gate"), delivered=bool(info.get("delivered")))

    @app.get("/api/topics/{topic_id}/video-project/latest-export")
    def koubo_latest_export(topic_id: int) -> dict[str, Any]:
        """剪映导出里最新的那一条。名字全是日期，所以带上时长和大小给 作者 核对。"""
        from ... import koubo

        root = koubo.exports_root(video_root())
        return {"root": str(root), "latest": koubo.latest_export(root)}

    @app.post("/api/topics/{topic_id}/video-project/drop")
    def koubo_drop(topic_id: int, body: DropBody) -> dict[str, Any]:
        """作者 把剪映导出的文件夹拖进页面：还没项目就建一个、关联上，再把视频和字幕放进去。

        浏览器拖进来的文件拿不到路径，只有名字和大小；视频动辄一两个 G，也不往本机再传一遍，
        而是按名字和大小去剪映导出目录（和桌面、下载、影片）里找回原文件，同一块盘上秒拷不占空间。
        """
        from ... import koubo

        videos = [f for f in body.files if Path(f.name).suffix.lower() in koubo.VIDEO_SUFFIXES]
        if not videos:
            raise ValueError("拖进来的东西里没有视频（.mp4 / .mov）")
        exports = koubo.exports_root(video_root())
        home = Path.home()
        roots = [(exports, koubo.EXPORT_DEPTH), (exports.parent, 1),
                 (home / "Desktop", 2), (home / "Downloads", 2), (home / "Movies", 3)]
        pick = max(videos, key=lambda f: f.size)
        video = koubo.locate(roots, pick.name, pick.size)
        if video is None:
            raise ValueError(f"在剪映导出目录（{exports}）、桌面、下载、影片里都没找到 {pick.name}。"
                             "拖剪映导出位置里的那个文件夹进来，或者先把它挪进剪映导出目录")
        srt = None
        dropped_srts = [f for f in body.files if Path(f.name).suffix.lower() == ".srt"]
        if dropped_srts:
            same = next((f for f in dropped_srts if Path(f.name).stem == video.stem), dropped_srts[0])
            srt = koubo.locate([(video.parent, 0)], same.name, same.size)
        srt = srt or koubo.srt_for(video, exports)
        created = None
        if not store.topic(topic_id).get("video_project"):
            created = _new_project(topic_id)
        result = koubo.adopt(video, _koubo_dir(topic_id), srt=srt)
        store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》放进了粗剪 {video.name}", topic_id)
        said = f"{video.name}{' 和字幕' if result.get('srt') else '（没带字幕）'}已经放进项目"
        more = _video_in(topic_id)
        if more:
            said += f"；{more}"
        return {**result, "created": created, "source": str(video),
                "message": f"建好项目 {created}，{said}" if created else said}

    def _after_transcript(topic_id: int) -> None:
        """有逐字稿了：拍后批注（10/13）和口播稿（10/19）都自动出，各自判断该不该做。"""
        for key in ("topic_review_start", "topic_script_auto"):
            start = getattr(app.state, key, None)
            if not start:
                continue
            try:
                start(topic_id)
            except Exception as exc:  # noqa: BLE001 - 出不来不影响视频那边
                logger.warning("%s %s: %s", key, topic_id, exc)

    def _start_transcribe(topic_id: int) -> dict[str, Any]:
        from ... import koubo

        base = _koubo_dir(topic_id)
        video = koubo.find_video(base)
        if video is None:
            raise ValueError("项目目录里没找到成片，先把粗剪放进去")
        with writing_lock:
            key = 10_000 + topic_id
            if key in writing:
                return {"started": False, "message": "正在转写"}
            writing.add(key)

        def run() -> None:
            from ... import koubo as k

            try:
                srt = k.transcribe(video, base)
                k.build_worktable(base, srt=srt)
                store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》转写完了，口播稿接着自动出", topic_id)
                _after_transcript(topic_id)
            except Exception as exc:  # noqa: BLE001 - 结果在 media 状态里看
                logger.warning("koubo transcribe %s failed: %s", topic_id, exc)
                store.log_event("edit", f"《{store.topic(topic_id)['title'][:24]}》转写失败：{str(exc)[:80]}", topic_id)
            finally:
                with writing_lock:
                    writing.discard(10_000 + topic_id)

        threading.Thread(target=run, name=f"koubo-{topic_id}", daemon=True).start()
        return {"started": True, "message": f"开始转写 {video.name}，15 分钟的片子大概 2–3 分钟"}

    def _video_in(topic_id: int) -> str:
        """视频进了项目（拖进来、点「就是它」、关联已有的项目）：带字幕就直接出口播稿，没带就本机 whisper 转写。

        10/19 作者 定的：拍完文案就该在那儿，不再先问「要不要转写」。返回一句给页面看的话。"""
        from ... import koubo

        try:
            base = _koubo_dir(topic_id)
            if koubo.find_srt(base) is not None:
                _after_transcript(topic_id)
                return "口播稿照字幕自动出"
            if koubo.find_video(base) is None or os.environ.get("CONTENT_STUDIO_NO_AUTO_TRANSCRIBE"):
                return ""
            return "没带字幕，本机开始转写，转完口播稿自动出" if _start_transcribe(topic_id)["started"] else "正在转写"
        except Exception as exc:  # noqa: BLE001 - 转写起不来不影响放进项目
            logger.warning("video in %s: %s", topic_id, exc)
            return ""

    @app.post("/api/topics/{topic_id}/video-project/transcribe")
    def koubo_transcribe(topic_id: int) -> dict[str, Any]:
        """本机跑 whisper。10/19 起视频一进项目就自动跑（_video_in），这个按钮只用来重转。"""
        return _start_transcribe(topic_id)

    @app.get("/api/topics/{topic_id}/video-project/transcribe")
    def koubo_transcribe_state(topic_id: int) -> dict[str, Any]:
        with writing_lock:
            return {"running": (10_000 + topic_id) in writing}

    @app.post("/api/topics/{topic_id}/video-project/build-worktable")
    def koubo_build(topic_id: int) -> dict[str, Any]:
        """已经有 SRT 的时候单独建表，不用重新转写。"""
        from ... import koubo

        base = _koubo_dir(topic_id)
        srt = koubo.find_srt(base)
        if srt is None:
            raise ValueError("项目目录里没有 SRT")
        koubo.build_worktable(base, srt=srt)
        return {"ok": True, "message": "工作台建好了"}

    @app.get("/api/topics/{topic_id}/video-project/worktable.html", response_class=HTMLResponse)
    def koubo_worktable(topic_id: int) -> str:
        """把 ask-park-video 那张表原样开在工作台里，只多挂一颗「保存到项目」。

        以前这一步是：在别处打开 HTML → 导出 JSON 落进下载文件夹 → 手动拷回
        analysis/worktable.json。现在点一下就写回去了。
        """
        from ... import koubo

        return koubo.worktable_html(_koubo_dir(topic_id), save_url=f"/api/topics/{topic_id}/video-project/worktable")

    # -- 这次怎么剪（10/19 作者）：一张卡两个开关，进度只列勾上的块 ----------------

    def _plan_view(topic_id: int) -> dict[str, Any]:
        from ... import cutplan, koubo

        topic = store.topic(topic_id)
        default = cutplan.clean(store.settings().get("cut_plan_default") or {})
        if not topic.get("video_project"):
            return {"plan": default, "chosen": False, "locked": False, "route": cutplan.route(default),
                    "blocks": [], "has_video": False, "project": None, "title": topic["title"]}
        base = _koubo_dir(topic_id)
        info = video_project.inspect(video_root(), topic["video_project"])
        plan, locked = cutplan.from_project(info, cutplan.read(base))
        shown = plan or default
        return {"plan": shown, "chosen": plan is not None, "locked": locked, "route": cutplan.route(shown),
                "blocks": cutplan.blocks(info, plan, base, has_srt=koubo.find_srt(base) is not None),
                "has_video": koubo.find_video(base) is not None, "project": topic["video_project"], "title": topic["title"],
                "can_back": info.get("layout") == "v2" or (info.get("layout") in ("fresh", "legacy") and bool(info.get("delivered")))}

    def _plan_save(topic_id: int, raw: dict[str, Any], *, started: bool) -> dict[str, Any]:
        from ... import cutplan

        view = _plan_view(topic_id)
        if view["locked"]:
            raise ValueError("这一条已经开始剪了，要改先「退回去选」")
        if not view["project"]:
            raise ValueError("先把剪映导出的视频放进来")
        try:
            plan = cutplan.clean(raw, view["plan"])
        except cutplan.CutPlanError as exc:
            raise ValueError(str(exc)) from None
        cutplan.write(_koubo_dir(topic_id), plan, started=started)
        store.update_settings({"cut_plan_default": plan})  # 下一条默认照这一次
        return plan

    @app.get("/api/topics/{topic_id}/video-project/plan")
    def get_cut_plan(topic_id: int) -> dict[str, Any]:
        return _plan_view(topic_id)

    @app.put("/api/topics/{topic_id}/video-project/plan")
    def put_cut_plan(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        _plan_save(topic_id, payload, started=False)
        return _plan_view(topic_id)

    @app.post("/api/topics/{topic_id}/video-project/plan/start")
    def start_cut_plan(topic_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """按勾上的块开始：落到哪个后台见 cutplan 模块说明。后台本身不改。"""
        from ... import cutplan, koubo
        from ...extras.motion import video_v2

        if not _plan_view(topic_id)["has_video"]:
            raise ValueError("项目里还没有粗剪：先把剪映导出放进来")
        plan = _plan_save(topic_id, payload or {}, started=False)
        base = _koubo_dir(topic_id)
        title = store.topic(topic_id)["title"][:24]
        r = cutplan.route(plan)
        try:
            if r == "plain":
                koubo.mark_external(base, "all")
                message = "粗剪就是成片，去定标题和封面"
            elif r == "motion":
                video_v2.init(base)
                message = "开始做动效：在下面定这条的动效设置"
            else:  # hook / full：10/21 起都先标 Hook、切片（park-video-v2 的 pv2.py worktable / hook）；full 拼好以后再做动效
                srt = koubo.find_srt(base)
                if srt is not None and not (base / "analysis" / "worktable.html").is_file():
                    def build() -> None:
                        try:
                            koubo.build_worktable(base, srt=srt)
                        except Exception as exc:  # noqa: BLE001 - 页面上「做 Hook 表」能重来
                            logger.warning("worktable %s: %s", topic_id, exc)
                    threading.Thread(target=build, name=f"worktable-{topic_id}", daemon=True).start()
                message = "只剪 Hook：先在下面标 Hook" if r == "hook" else "先在下面标 Hook、切片；在剪映里拼好再做动效"
        except (koubo.KouboError, video_v2.VideoV2Error) as exc:
            raise ValueError(str(exc)) from None
        cutplan.write(base, plan, started=True)
        said = {"plain": "不剪 Hook、不加动效", "motion": "只加动效", "full": "剪 Hook + 加动效", "hook": "只剪 Hook"}[r]
        store.log_event("edit", f"《{title}》这次怎么剪：{said}", topic_id)
        return {**_plan_view(topic_id), "message": message}

    # -- 只剪 Hook（10/19 作者）：页面上点一下，后台切 h1…hN，不碰正文 ----------------

    hook_cuts: dict[int, dict[str, Any]] = {}

    def _hook_view(topic_id: int) -> dict[str, Any]:
        base = _koubo_dir(topic_id)
        try:
            qa = json.loads((base / "part-a-hook" / "qa.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            qa = None
        with writing_lock:
            run = dict(hook_cuts.get(topic_id) or {})
        return {"running": bool(run.get("running")), "stage": run.get("stage"), "error": run.get("error"),
                "flags": (qa or {}).get("flags") or [], "at": (qa or {}).get("at")}

    @app.get("/api/topics/{topic_id}/video-project/hook-clips")
    def hook_clips_state(topic_id: int) -> dict[str, Any]:
        return _hook_view(topic_id)

    @app.post("/api/topics/{topic_id}/video-project/hook-clips")
    def hook_clips_start(topic_id: int) -> dict[str, Any]:
        """照工作台标好的 Hook 切 part-a-hook/individual/h1.mp4…，写 edit.json / qa.json。几十秒，后台跑。"""
        from ... import hookcut

        view = _plan_view(topic_id)
        if not (view["locked"] and view["route"] in ("hook", "full")):
            raise ValueError("这一条没选剪 Hook")
        base = _koubo_dir(topic_id)
        try:
            hookcut.picked(base)  # 没标 Hook 直接说，不进后台
        except hookcut.HookCutError as exc:
            raise ValueError(str(exc)) from None
        with writing_lock:
            if (hook_cuts.get(topic_id) or {}).get("running"):
                raise HTTPException(status_code=409, detail="正在切 Hook")
            hook_cuts[topic_id] = {"running": True, "stage": "准备", "error": None}
        title = store.topic(topic_id)["title"][:24]
        # 剪映粗剪的字幕是烧进去的、切不掉，开头落在字幕中间要提醒。不看 cut-plan 的 captions：
        # 只剪 Hook 这张卡不显示那一项，那个值是上一条「剪 Hook + 加动效」留下的默认。项目里明说没烧录才不查。
        try:
            burned = (json.loads((base / "project.json").read_text(encoding="utf-8")).get("media_inspection") or {}).get("burned_in_captions") is not False
        except (OSError, ValueError, AttributeError):
            burned = True

        def stage(name: str) -> None:
            with writing_lock:
                hook_cuts[topic_id] = {**hook_cuts[topic_id], "stage": name}

        def run() -> None:
            try:
                qa = hookcut.run(base, captions_burned_in=burned, progress=stage)
                n, flagged = len(qa["clips"]), len(qa["flags"])
                store.log_event("edit", f"《{title}》Hook 切好了 {n} 段" + (f"，{flagged} 段要听一下" if flagged else ""), topic_id)
                with writing_lock:
                    hook_cuts[topic_id] = {"running": False, "stage": None, "error": None}
            except Exception as exc:  # noqa: BLE001 - 原因在卡片上看
                logger.warning("hook clips %s failed: %s", topic_id, exc)
                said = str(exc) if isinstance(exc, hookcut.HookCutError) else f"切 Hook 出错：{str(exc)[:120]}"
                store.log_event("edit", f"《{title}》切 Hook 失败：{said[:80]}", topic_id)
                with writing_lock:
                    hook_cuts[topic_id] = {"running": False, "stage": None, "error": said}

        threading.Thread(target=run, name=f"hook-clips-{topic_id}", daemon=True).start()
        return {**_hook_view(topic_id), "message": "开始切 Hook，几十秒"}

    # -- background workflow runs & gate approvals -----------------------

    def run_view(run: dict[str, Any]) -> dict[str, Any]:
        from ...extras.motion import workflow_runner

        if not run.get("log_path"):
            return {**run, "log_tail": ""}
        current = workflow_runner.status(run)
        if current["state"] != run["state"] and run["state"] in ("starting", "running"):
            store.update_run(run["id"], state=current["state"], finished_at=None if current["state"] == "running" else now_iso())
        return current


    @app.get("/api/topics/{topic_id}/video-project/run")
    def get_run(topic_id: int) -> dict[str, Any]:
        runs = store.runs(topic_id=topic_id)
        active_elsewhere = [r for r in store.runs(active_only=True) if r["topic_id"] != topic_id]
        return {"run": run_view(runs[0]) if runs else None, "busy_elsewhere": bool(active_elsewhere and run_view(active_elsewhere[0])["state"] == "running")}

    @app.post("/api/topics/{topic_id}/video-project/run")
    def start_run(topic_id: int) -> dict[str, Any]:
        from ...extras.motion import workflow_runner

        topic, path, info = linked_project(topic_id)
        for active in store.runs(active_only=True):
            if run_view(active)["state"] == "running":
                raise ValueError("已经有一个口播项目在后台跑，等它停下或先中止")
        if info["layout"] == "legacy":
            raise ValueError("这是旧版目录，没有 project.json，不能按 14 步继续")
        if info.get("delivered"):
            raise ValueError("这个项目已经交付了")
        if info.get("gate"):
            raise ValueError(f"项目停在 {info['gate']['key']}：{info['gate']['title']}。先处理审批门再继续")
        run_id = store.create_run(topic_id, topic["video_project"])
        started = workflow_runner.start(path, run_id=run_id, runs_dir=runs_dir or workflow_runner.DEFAULT_RUNS_DIR, command=runner_command)
        run = store.update_run(run_id, state="running", **started)
        return {"run": run_view(run), "message": "开始在后台跑口播 workflow，停在下一个审批门会提醒你"}

    @app.delete("/api/topics/{topic_id}/video-project/run")
    def cancel_run(topic_id: int) -> dict[str, Any]:
        from ...extras.motion import workflow_runner

        runs = [r for r in store.runs(topic_id=topic_id, active_only=True)]
        if not runs:
            raise ValueError("没有正在跑的任务")
        workflow_runner.cancel(runs[0])
        return {"run": run_view(store.update_run(runs[0]["id"], state="cancelled", finished_at=now_iso()))}

    @app.get("/api/topics/{topic_id}/video-project/gate")
    def gate_review(topic_id: int) -> dict[str, Any]:
        from ...extras.motion import workflow_runner

        _topic, path, info = linked_project(topic_id)
        if not info.get("gate"):
            raise ValueError("现在没有等待你的审批门")
        return {"gate": info["gate"], "review": workflow_runner.gate_review(path, info["gate"]["key"])}

    @app.post("/api/topics/{topic_id}/video-project/approve")
    def approve_gate(topic_id: int, body: ApproveBody) -> dict[str, Any]:
        from ...extras.motion import workflow_runner

        _topic, path, info = linked_project(topic_id)
        gate = info.get("gate")
        if not gate or gate["key"] != body.gate:
            raise ValueError("这个审批门现在不在等待批准")
        if body.gate == "H1" and not (path / "analysis" / "worktable.json").is_file():
            raise ValueError("先在 worktable 里选 Hook 并导入，再批准")
        record = workflow_runner.approve(path, body.gate, note=body.note)
        return {"approval": record, "project": video_project.inspect(video_root(), _topic["video_project"])}

    @app.post("/api/topics/{topic_id}/video-project/back")
    def video_choice_back(topic_id: int) -> dict[str, Any]:
        """选了「做动效」或「不加动效」之后反悔：退回到加不加动效那一步。"""
        from ... import cutplan

        topic, path, _info = linked_project(topic_id)
        message = video_project.back_to_choice(path)
        saved = cutplan.read(path)
        if saved:  # 退回去 = 「这次怎么剪」又能改了
            cutplan.write(path, cutplan.clean({k: saved[k] for k in cutplan.DEFAULT if k in saved}), started=False)
        store.log_event("edit", f"《{topic['title'][:24]}》退回到加不加动效", topic_id)
        return {"message": message, "project": video_project.inspect(video_root(), topic["video_project"])}
