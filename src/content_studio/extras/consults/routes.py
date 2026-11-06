"""咨询客户：上传咨询录音 → 转写 + 分析 → 纪要和客户版 PDF；客户档案（10/5 起）。试用版没有这一块。"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pathlib import Path
from ... import vault
from ...store import now_iso
from ...web import logger
from ...core.dates import parse_day


# 这一块从主线拿什么（web.BLOCK_API）、递给后面哪几块用（features/__init__.py 当场核对）
NEEDS: tuple[str, ...] = ("_open_in_browser", "hooks", "places")
PROVIDES: tuple[str, ...] = ()


def register(app: Any, ctx: Any) -> None:
    places = ctx.places
    _open_in_browser = ctx._open_in_browser
    vault_path = places.vault_path
    hooks = ctx.hooks

    # -- 咨询录音：上传 → 转写 + 分析 → vault 010_咨询/ 一篇左右对照的笔记 --------
    consult_running: set[str] = set()
    consult_lock = threading.Lock()

    def _consult_row(row: dict[str, Any]) -> dict[str, Any]:
        from urllib.parse import quote

        with consult_lock:
            running = row["slug"] in consult_running
        stage = row.get("stage")
        if stage in ("queued", "transcribing", "analyzing", "client") and not running:
            stage = "interrupted"
        note = row.get("note")
        slug_q = quote(row["slug"])
        return {
            "slug": row["slug"], "name": row.get("name"), "day": row.get("day"), "stage": stage, "running": running,
            "error": row.get("error"), "minutes": row.get("minutes"), "note": note, "missing": row.get("missing") or [],
            "obsidian": f"obsidian://open?path={quote(note)}" if note else None,
            "client": f"/api/consults/{slug_q}/client.html" if row.get("client") else None,
            "pdf": f"/api/consults/{slug_q}/client.pdf" if row.get("pdf") else None,
            "client_file": row.get("client"),
        }

    def start_consult(slug: str) -> bool:
        from urllib.parse import quote

        from . import consult

        folder = consult.root() / slug
        with consult_lock:
            if slug in consult_running:
                return False
            consult_running.add(slug)
        consult.save_state(folder, stage="queued", error=None)

        def run() -> None:
            try:
                note = consult.run(folder, vault.vault_root(vault_path()))
                _open_in_browser(f"obsidian://open?path={quote(str(note))}")
            except Exception as exc:  # noqa: BLE001 - shown to 作者 on the card
                logger.warning("consult %s failed: %s", slug, exc)
                consult.save_state(folder, stage="failed", error=str(exc)[:300] or type(exc).__name__, pid=None)
            finally:
                with consult_lock:
                    consult_running.discard(slug)

        threading.Thread(target=run, name=f"consult-{slug}", daemon=True).start()
        return True

    @app.get("/api/consults")
    def get_consults() -> dict[str, Any]:
        from . import consult

        return {"consults": [_consult_row(r) for r in consult.jobs()][:20]}

    @app.get("/api/consults/playbook")
    def consult_playbook() -> dict[str, Any]:
        """做咨询时照着过的「诊断流程」：vault 010_咨询/诊断流程.md，每次打开都重新读。"""
        from urllib.parse import quote

        from . import consult

        doc = consult.playbook(vault.vault_root(vault_path()))
        return {**doc, "obsidian": "obsidian://open?path=" + quote(doc["path"])}

    @app.get("/api/consults/scripts")
    def consult_scripts() -> dict[str, Any]:
        """回微信用的「统一话术」：vault 010_咨询/统一话术.md，每次打开都重新读。"""
        from urllib.parse import quote

        from . import consult

        doc = consult.playbook(vault.vault_root(vault_path()), consult.SCRIPTS)
        return {**doc, "obsidian": "obsidian://open?path=" + quote(doc["path"])}

    @app.post("/api/consults")
    async def post_consult(request: Request) -> dict[str, Any]:
        from . import consult

        form = await request.form()
        upload, name = form.get("file"), str(form.get("name") or "").strip()
        if upload is None or not getattr(upload, "filename", ""):
            raise HTTPException(status_code=400, detail="没收到录音文件")
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in consult.MEDIA_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"不认识这种文件：{suffix or '没有扩展名'}（支持 m4a、mp3、wav、mp4、mov 等）")
        if not name:
            raise HTTPException(status_code=400, detail="写一下客户是谁")
        day = parse_day(str(form.get("day") or "") or None)
        slug = consult.slug(name, day)
        folder = consult.root() / slug
        with consult_lock:
            if slug in consult_running:
                raise HTTPException(status_code=409, detail="这一场正在处理，等它做完")
        folder.mkdir(parents=True, exist_ok=True)
        # 同一场重新上传：原件和之前的转写、分析、客户版都作废
        for old in [*folder.glob("audio.*"), *folder.glob(f"{consult.ORIGINAL}.*")]:
            old.unlink()
        for cache in ("transcript.json", consult.TEXT_FILE, "analysis.json", "client.json", "客户版.html"):
            (folder / cache).unlink(missing_ok=True)
        with (folder / f"{consult.ORIGINAL}{suffix}").open("wb") as out:
            while chunk := await upload.read(1 << 20):
                out.write(chunk)
        consult.save_state(folder, name=consult.slug(name, day)[5:], day=day.isoformat(), original=upload.filename,
                           created_at=now_iso(), note=None, missing=[])
        start_consult(slug)
        return {"consult": _consult_row({"slug": slug, **consult.load_state(folder)})}

    def _consult_folder(slug: str) -> Path:
        from . import consult

        folder = consult.root() / slug
        if folder.parent != consult.root() or not (folder / "state.json").is_file():
            raise HTTPException(status_code=404, detail="找不到这一场")
        return folder

    @app.get("/api/consults/{slug}/client.html")
    def consult_client(slug: str) -> Response:
        page = _consult_folder(slug) / "客户版.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="客户版还没做好")
        return FileResponse(page, media_type="text/html; charset=utf-8")

    @app.get("/api/consults/{slug}/client.pdf")
    def consult_client_pdf(slug: str) -> Response:
        from . import consult

        pdf = consult.load_state(_consult_folder(slug)).get("pdf")
        if not pdf or not Path(pdf).is_file():
            raise HTTPException(status_code=404, detail="客户版 PDF 还没做好")
        return FileResponse(pdf, media_type="application/pdf")

    @app.get("/api/clients")
    def get_clients() -> dict[str, Any]:
        """「客户」页：一个客户一行，档案 + 每一场咨询的两份 summary。"""
        from . import consult

        from urllib.parse import quote

        root = vault.vault_root(vault_path())
        rows = consult.clients(root)
        for row in rows:
            row["consults"] = [_consult_row(c) for c in row["consults"]]
            row["consults"].sort(key=lambda c: c.get("day") or "", reverse=True)
            base = f"/api/clients/{quote(row['name'])}/file/"
            for day in row["files"]:
                for doc in day["sent"]:
                    doc["pdf_url"] = base + quote(doc["pdf"]) if doc["pdf"] else None
                    doc["html_url"] = base + quote(doc["html"]) if doc["html"] else None
                for doc in day["mine"]:
                    doc["obsidian"] = "obsidian://open?path=" + quote(str(consult.client_dir(root, row["name"]) / doc["file"]))
        return {"clients": rows, "fields": list(consult.PROFILE_FIELDS)}

    def _client_file(name: str, file: str) -> Path:
        from . import consult

        home = consult.client_dir(vault.vault_root(vault_path()), name)
        path = home / file
        if home.name != name or "/" in file or file.startswith(".") or not path.is_file():
            raise HTTPException(status_code=404, detail="找不到这个文件")
        return path

    @app.get("/api/clients/{name}/file/{file}")
    def client_file(name: str, file: str) -> Response:
        path = _client_file(name, file)
        media = {".pdf": "application/pdf", ".html": "text/html; charset=utf-8", ".md": "text/markdown; charset=utf-8"}
        return FileResponse(path, media_type=media.get(path.suffix, "application/octet-stream"))

    @app.post("/api/clients/{name}/reveal")
    def reveal_client_file(name: str, file: str) -> dict[str, Any]:
        """在 Finder 里选中这个文件（拖进微信发给客户）。"""
        path = _client_file(name, file)
        if sys.platform == "darwin" and not os.environ.get("CONTENT_STUDIO_NO_OPEN"):
            subprocess.Popen(["open", "-R", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"path": str(path)}

    @app.put("/api/clients/{name}")
    def put_client(name: str, body: dict[str, Any]) -> dict[str, Any]:
        from . import consult

        home = consult.client_dir(vault.vault_root(vault_path()), name)
        if home.name != name:
            raise HTTPException(status_code=400, detail="客户名里有不能用的字符")
        return {"profile": consult.write_profile(home, body)}

    @app.delete("/api/clients/{name}")
    def delete_client(name: str) -> dict[str, Any]:
        from . import consult

        root = vault.vault_root(vault_path())
        if consult.client_dir(root, name).name != name:
            raise HTTPException(status_code=400, detail="客户名里有不能用的字符")
        with consult_lock:
            if any(j["slug"] in consult_running and consult.client_dir(root, j.get("name") or "").name == name
                   for j in consult.jobs()):
                raise HTTPException(status_code=409, detail="这个客户有一场正在转写/分析，等它做完再删")
        try:
            moved = consult.delete_client(root, name)
        except consult.ConsultError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"trashed": [str(p) for p in moved]}

    @app.post("/api/consults/{slug}/reveal")
    def reveal_consult(slug: str, what: str = "folder") -> dict[str, Any]:
        """在 Finder 里指给 作者 看：客户版 PDF（发给客户用）或本机留的原件和文字。"""
        from . import consult

        folder = _consult_folder(slug)
        state = consult.load_state(folder)
        client = state.get("pdf") or state.get("client")
        target = Path(client) if what == "client" and client else (consult.audio_of(folder) or folder)
        if sys.platform == "darwin" and not os.environ.get("CONTENT_STUDIO_NO_OPEN"):
            subprocess.Popen(["open", "-R", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"path": str(target)}

    @app.post("/api/consults/{slug}/retry")
    def retry_consult(slug: str) -> dict[str, Any]:
        from . import consult

        folder = _consult_folder(slug)
        start_consult(slug)
        return {"consult": _consult_row({"slug": slug, **consult.load_state(folder)})}

    def _rows() -> list[dict[str, Any]]:
        from . import consult

        return [_consult_row(r) for r in consult.jobs()]

    hooks["consult_rows"] = _rows  # 今天页的本月咨询、每日待办里「把客户版 PDF 发过去」
