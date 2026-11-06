"""证据：骨架页「按论点找证据」（新闻、数据、原推，逐字核对、截高亮），打包页「找证据图」，以及每晚的证据队列（10/2–10/5）。试用版没有这一块。"""
from __future__ import annotations

import json
import threading
from typing import Any
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pathlib import Path
from ... import video_project
from ...store import now_iso
from ...video_project import VideoProjectError
from ...web import logger


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = (
    "downloads_dir", "drafts_root", "evidence_fn", "feature_on", "get_backfill", "hooks", "places", "proof_fn", "startup",
    "stop_auto",
    "store", "writing", "writing_lock",
)
AUTO_PROOF_SECONDS = 60  # 多久看一次「正在做」的那条该不该自己开始找证据
PROVIDES: tuple[str, ...] = ("_picked",)


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    _article_path = places.article_path
    downloads_dir = ctx.downloads_dir
    drafts_root = ctx.drafts_root
    evidence_fn = ctx.evidence_fn
    final_video_path = places.final_video_path
    get_backfill = ctx.get_backfill
    proof_fn = ctx.proof_fn
    store = ctx.store
    hooks = ctx.hooks
    startup = ctx.startup
    stop_auto = ctx.stop_auto
    video_root = places.video_root
    writing = ctx.writing
    writing_lock = ctx.writing_lock

    def _evidence_inputs(topic: dict[str, Any], video_id: str | None = None) -> dict[str, Any]:
        """找证据图要的三样：文章、视频（剪辑前的原片更清楚）、字幕。缺了说为什么。"""
        from ... import cover

        art = _article_path(topic)
        video = final_video_path(topic)
        row: dict[str, Any] = {"article": str(art) if art else None, "video": None, "transcript": None, "skip": None}
        if art is None or not art.is_file():
            row["skip"] = "还没有文章"
        elif video is None or not video.is_file():
            row["skip"] = "找不到视频（作品库那块硬盘没插？）"
        else:
            if topic.get("video_project"):
                try:
                    video = cover.source_video(video_project.project_dir(video_root(), topic["video_project"]), video)
                except VideoProjectError:
                    pass
            row["video"] = str(video)
            vid = video_id or topic.get("published_video_id")
            found = sorted((downloads_dir / "douyin").glob(f"*/{vid}/transcript.json")) if vid else []
            row["transcript"] = str(found[0]) if found else None
        return row

    @app.get("/api/evidence/queue")
    def evidence_queue() -> dict[str, Any]:
        """命令行 `content-studio evidence` 一次跑一批用：还有平台没发的内容里，有文章、有视频的。
        提案比文章新（跑过了、文章没再改）或者文章里已经有证据图的，标 done，跳过。"""
        from . import evidence

        out = []
        for r in get_backfill()["videos"]:
            if r.get("cancelled") or not r["missing"] or not r["topic_id"]:
                continue
            topic = store.topic(r["topic_id"])
            row = {"topic_id": topic["id"], "title": r["headline"] or topic["title"], "done": False, **_evidence_inputs(topic, r["video_id"])}
            if not row["skip"]:
                art = Path(row["article"])
                proposal = art.parent / evidence.OUT / evidence.PROPOSAL
                row["done"] = (proposal.is_file() and proposal.stat().st_mtime >= art.stat().st_mtime) or bool(evidence.in_article(art.read_text(encoding="utf-8")))
            out.append(row)
        return {"topics": out}

    # 打包页「插图」那一步：要不要找证据图他点了才找；找完一张张挑（10/2 作者）
    evidence_errors: dict[int, str] = {}

    def _evidence_view(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import evidence

        topic = store.topic(topic_id)
        with writing_lock:
            running = 60_000 + topic_id in writing
        art = _article_path(topic)
        st = evidence.status(art) if art is not None and art.is_file() else {"state": "none", "items": [], "rejected": 0, "used": []}
        for i in st["items"]:
            i["src"] = f"/api/topics/{topic_id}/article-file/{evidence.OUT}/{quote(i['file'])}"
        return {"running": running, "error": evidence_errors.get(topic_id), "skip": _evidence_skip(topic, _evidence_inputs(topic)),
                "picked": len(_picked(topic_id)), **st}

    def _picked(topic_id: int) -> list[dict[str, Any]]:
        """他拍之前在骨架页点过「要」的证据（10/5）：文章配图、视频截图卡都先用这些。"""
        from . import proof

        return proof.chosen(drafts_root / f"topic-{topic_id}")

    def _evidence_skip(topic: dict[str, Any], inputs: dict[str, Any]) -> str | None:
        """没视频也能找：骨架页点过「要」的证据就够放（只是没有视频截帧）。"""
        if inputs["skip"] and inputs["article"] and not inputs["video"] and _picked(topic["id"]):
            return None
        return inputs["skip"]

    @app.get("/api/topics/{topic_id}/evidence")
    def evidence_state(topic_id: int) -> dict[str, Any]:
        return _evidence_view(topic_id)

    @app.post("/api/topics/{topic_id}/evidence")
    def evidence_start(topic_id: int) -> dict[str, Any]:
        """开始找证据图（后台跑，2–4 分钟）：视频里的笔记截图、名人原推。只出提案，文章不动。"""
        from . import evidence

        topic = store.topic(topic_id)
        inputs = _evidence_inputs(topic)
        skip = _evidence_skip(topic, inputs)
        if skip:
            raise ValueError(skip)
        if evidence.in_article(Path(inputs["article"]).read_text(encoding="utf-8")):
            raise ValueError("文章里已经放着证据图了：要重新找，先点「撤回」")
        with writing_lock:
            if 60_000 + topic_id in writing:
                return {"started": False, "message": "正在找"}
            writing.add(60_000 + topic_id)
        evidence_errors.pop(topic_id, None)

        def run() -> None:
            try:
                segments = []
                if inputs["transcript"]:
                    try:
                        segments = json.loads(Path(inputs["transcript"]).read_text(encoding="utf-8")).get("segments") or []
                    except (OSError, ValueError):
                        segments = []
                res = (evidence_fn or evidence.run_topic)(Path(inputs["article"]), Path(inputs["video"]) if inputs["video"] else None,
                                                          segments=segments, pool=_picked(topic_id))
                n = sum(1 for i in res["items"] if i.get("placed"))
                store.log_event("copy", f"《{topic['title'][:24]}》找了证据图：{n} 张等你挑", topic_id)
            except Exception as exc:  # noqa: BLE001 - 打包页显示
                logger.warning("evidence %s failed: %s", topic_id, exc)
                evidence_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                with writing_lock:
                    writing.discard(60_000 + topic_id)

        threading.Thread(target=run, name=f"evidence-{topic_id}", daemon=True).start()
        return {"started": True, "message": "开始找证据图：骨架页你要过的证据、视频里的笔记截图、名人原推，一般 2–4 分钟"}

    @app.post("/api/topics/{topic_id}/evidence/apply")
    def evidence_apply(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """他挑的放进文章；files 为空就是「这篇不要证据图」。放进去之后公众号排版作废，要重排。"""
        from . import evidence

        art = _article_path(store.topic(topic_id))
        if art is None or not art.is_file():
            raise ValueError("还没有文章")
        files = [str(f) for f in body.get("files") or []]
        try:
            evidence.apply(art, files, now=now_iso())
        except evidence.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _evidence_view(topic_id)

    @app.post("/api/topics/{topic_id}/evidence/undo")
    def evidence_undo(topic_id: int) -> dict[str, Any]:
        from . import evidence

        art = _article_path(store.topic(topic_id))
        if art is None or not art.is_file():
            raise ValueError("还没有文章")
        try:
            evidence.undo(art)
        except evidence.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _evidence_view(topic_id)

    # 骨架页「证据」：拍之前按论点找真东西（新闻、数据、原推），他自己的截图他传；点过「要」的才给视频和文章用（10/5 作者）
    proof_errors: dict[int, str] = {}

    def _proof_base(topic_id: int) -> Path:
        return drafts_root / f"topic-{topic_id}"

    def _skeleton(topic: dict[str, Any]) -> str:
        from ... import outline

        sk = outline.read_outline(topic)
        if not sk:
            raise ValueError("先写骨架，再按论点找证据")
        return sk["markdown"]

    def _proof_view(topic_id: int) -> dict[str, Any]:
        from urllib.parse import quote

        from . import proof

        topic = store.topic(topic_id)
        with writing_lock:
            running = 80_000 + topic_id in writing
        st = proof.view(_proof_base(topic_id), _skeleton(topic))
        for p in st["points"]:
            for i in p["items"]:
                i["src"] = f"/api/topics/{topic_id}/proof-file/{quote(i['file'])}"
                i["kind_label"] = proof.KINDS.get(i.get("kind"), "")
        return {"running": running, "error": proof_errors.get(topic_id), **st}

    @app.get("/api/topics/{topic_id}/proof")
    def proof_state(topic_id: int) -> dict[str, Any]:
        return _proof_view(topic_id)

    @app.post("/api/topics/{topic_id}/proof")
    def proof_start(topic_id: int) -> dict[str, Any]:
        """按骨架的论点找证据（后台跑，3–8 分钟）：只出候选，他点「要」才算数。"""
        from . import proof

        topic = store.topic(topic_id)
        skeleton = _skeleton(topic)
        if not proof.points(skeleton):
            raise ValueError("骨架里没有「### 论点」，不知道给哪儿找证据")
        if not _start_proof(topic, skeleton):
            return {"started": False, "message": "正在找"}
        return {"started": True, "message": "开始按论点找证据：新闻、数据、原推，逐条核对原话，一般 3–8 分钟"}

    def _start_proof(topic: dict[str, Any], skeleton: str) -> bool:
        from . import proof

        topic_id = topic["id"]
        with writing_lock:
            if 80_000 + topic_id in writing:
                return False
            writing.add(80_000 + topic_id)
        proof_errors.pop(topic_id, None)

        def run() -> None:
            try:
                res = (proof_fn or proof.run)(_proof_base(topic_id), topic["title"], skeleton, now=now_iso())
                n = sum(1 for p in res["points"] for i in p["items"] if i.get("kind") != "mine")
                store.log_event("outline", f"《{topic['title'][:24]}》按论点找了证据：{n} 条等你挑", topic_id)
            except Exception as exc:  # noqa: BLE001 - 骨架页显示
                logger.warning("proof %s failed: %s", topic_id, exc)
                proof_errors[topic_id] = str(exc)[:300] or type(exc).__name__
            finally:
                with writing_lock:
                    writing.discard(80_000 + topic_id)

        threading.Thread(target=run, name=f"proof-{topic_id}", daemon=True).start()
        return True

    # 10/9 作者（流程板）：进了「正在做」就自己出证据单，不用他去骨架页点。只起一次：
    # 找过了（有 proof.json）就不再自己跑，论点改了要不要再找由他点「再找一遍」；这次开机试过的也不再试。
    auto_tried: set[int] = set()

    def auto_proof_once() -> int | None:
        from ... import outline
        from . import proof

        from ...board import is_shipped

        if not ctx.feature_on("proof"):  # 用户在「设置 · 流程」里关了证据（10/9）
            return None
        topic = store.focus_topic()
        # 已经拍了（接上了视频项目）或发了的不自己出：老的那条不能一上线就被「还差你的截图」卡住
        if topic is None or topic["id"] in auto_tried or topic.get("video_project") or is_shipped(topic):
            return None
        sk = outline.read_outline(topic)
        if not sk or not proof.points(sk["markdown"]) or (proof.load(_proof_base(topic["id"])) or {}).get("searched_at"):
            return None
        auto_tried.add(topic["id"])
        if not _start_proof(topic, sk["markdown"]):
            return None
        store.log_event("outline", f"《{topic['title'][:24]}》是今天要拍的：自己开始按论点出证据单", topic["id"])
        return topic["id"]

    def _auto_proof_loop() -> None:
        stop_auto.wait(20)
        while not stop_auto.is_set():
            try:
                auto_proof_once()
            except Exception as exc:  # noqa: BLE001 - 下一轮再看
                logger.warning("auto proof: %s", exc)
            stop_auto.wait(AUTO_PROOF_SECONDS)

    startup.append(lambda: threading.Thread(target=_auto_proof_loop, name="auto-proof", daemon=True).start())
    app.state.auto_proof_once = auto_proof_once  # 测试里直接转一轮

    @app.post("/api/topics/{topic_id}/proof/use")
    def proof_use(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """他改某个论点用什么证明：你的截图 / 外面的证据 / 插图 / 不要证据。"""
        from . import proof

        topic = store.topic(topic_id)
        _proof_idle(topic_id)
        key = str(body.get("key") or "")
        title = next((p["title"] for p in proof.points(_skeleton(topic)) if p["key"] == key), "")
        if not title:
            raise ValueError("骨架里没有这个论点了，刷新一下")
        try:
            proof.set_use(_proof_base(topic_id), key, title, str(body.get("use") or ""))
        except proof.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _proof_view(topic_id)

    def _sheet_skeleton(topic_id: int) -> str | None:
        from ... import outline

        sk = outline.read_outline(store.topic(topic_id))
        return sk["markdown"] if sk else None

    def proof_hold(topic_id: int) -> str:
        """卡发：证据单定了「你的截图」还没传的，X、公众号先不发。说清差哪几条、去哪补。
        截图都齐了、可还没放进文章（打包页「插图」里「找证据图」是他点了才跑）也先不发：
        不然整篇截图优先的文章 AI 插图拿掉了、截图也没放，发出去一张图都没有。"""
        from . import evidence, proof

        skeleton = _sheet_skeleton(topic_id)
        if not skeleton:
            return ""
        short = proof.missing_shots(_proof_base(topic_id), skeleton)
        if short:
            keys = "、".join(p["key"] for p in short)
            return f"论点 {keys} 还差你的截图：去骨架页「证据」传上来，或者把那条改成别的"
        art = _article_path(store.topic(topic_id))
        if proof.view(_proof_base(topic_id), skeleton)["sheet"] and _picked(topic_id) and art is not None and art.is_file() \
                and evidence.status(art)["state"] == "none":
            return "证据还没放进文章：去打包页「插图」点「找证据图」，挑好放进去（或者整篇不要）"
        return ""

    def proof_sheet(topic_id: int) -> dict[str, list[str]] | None:
        from . import proof

        skeleton = _sheet_skeleton(topic_id)
        return proof.illustration_plan(_proof_base(topic_id), skeleton) if skeleton else None

    hooks["proof_hold"] = proof_hold
    app.state.proof_hold = proof_hold
    hooks["proof_sheet"] = proof_sheet

    def _proof_idle(topic_id: int) -> None:
        with writing_lock:
            if 80_000 + topic_id in writing:
                raise ValueError("正在找证据，找完再挑、再传（一般 3–8 分钟）")

    @app.post("/api/topics/{topic_id}/proof/pick")
    def proof_pick(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        from . import proof

        _proof_idle(topic_id)
        try:
            proof.pick(_proof_base(topic_id), str(body.get("file") or ""), bool(body.get("pick")))
        except proof.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _proof_view(topic_id)

    @app.post("/api/topics/{topic_id}/proof/mine")
    async def proof_mine(topic_id: int, request: Request) -> dict[str, Any]:
        """他自己截的图（后台、录屏、聊天）：传到哪个论点下面。"""
        from . import proof

        topic = store.topic(topic_id)
        _proof_idle(topic_id)
        form = await request.form()
        upload, key = form.get("file"), str(form.get("key") or "").strip()
        if upload is None or not getattr(upload, "filename", "") or not key:
            raise HTTPException(status_code=400, detail="没收到图，或者不知道是哪个论点的")
        title = next((p["title"] for p in proof.points(_skeleton(topic)) if p["key"] == key), "")
        try:
            proof.add_mine(_proof_base(topic_id), key, title, upload.filename, await upload.read(), now=now_iso())
        except proof.EvidenceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return _proof_view(topic_id)

    @app.post("/api/topics/{topic_id}/proof/remove")
    def proof_remove(topic_id: int, body: dict[str, Any]) -> dict[str, Any]:
        from . import proof

        _proof_idle(topic_id)
        try:
            proof.remove(_proof_base(topic_id), str(body.get("file") or ""))
        except proof.EvidenceError as exc:
            raise ValueError(str(exc)) from None
        return _proof_view(topic_id)

    @app.get("/api/topics/{topic_id}/proof-file/{name}")
    def proof_file(topic_id: int, name: str) -> Response:
        from . import proof

        base = proof.folder(_proof_base(topic_id)).resolve()
        path = (base / name).resolve()
        if path.parent != base or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".heic"}:
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, headers={"Cache-Control": "no-store"})


    ctx._picked = _picked  # 别的积木要用
