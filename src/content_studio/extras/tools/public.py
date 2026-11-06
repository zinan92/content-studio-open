"""对外的单点功能服务（10/10 作者：「给我一个码，现在用这个码可以有 5 刀的额度，先给几个朋友和销售」）。

和工作台是两个进程、两套接口：这里只有 10 个功能的几个接口，没有工作台的任何别的东西（cookies、发布、笔记库都不在这个进程里）。
对外的任务在 macOS 沙盒里跑 Codex：

- 读不到你的主目录（除 ~/.codex 和这一次的任务目录）、读不到 /Volumes，写不进主目录（除同样两处）；
- 文字：Codex 自己的沙盒在外层沙盒里起不来，等于没有 shell，注入进去的命令跑不了；
- 出图：只用 image_gen，图落在 ~/.codex/generated_images/<会话>/，由这里在沙盒外取走，不让它自己存文件。

跑起来：python -m content_studio.extras.tools.public serve --port 8783
发码：  python -m content_studio.extras.tools.public codes add --name 张三 --dollars 5
急停：  touch ~/.config/content-studio/tools-public.off（接口立刻回「暂时关了」，删掉文件就恢复）
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from ...paths import config_dir
from . import codes, tools

ORIGINS = ("https://example.com", "https://www.example.com")
MAX_ACTIVE_PER_CODE = 2   # 一个码同时最多排两个
MAX_WAITING = 12          # 整个队列最多排 12 个，再多就说晚点再试
MAX_TEXT = 8000           # 对外的输入比本机的 2 万字短
MAX_TEXT_FIELD = {"illustrate": 5000}
KEEP_DAYS = 14
FAIL_WINDOW = 600         # 10 分钟里同一个来源输错 10 次码，先歇一会
FAIL_LIMIT = 10
IMAGE_TIMEOUT = 20 * 60
TEXT_TIMEOUT = 10 * 60


def base_dir() -> Path:
    return config_dir() / "tools-public"


def kill_file() -> Path:
    return config_dir() / "tools-public.off"


# -- 沙盒 ----------------------------------------------------------------------

def sandbox_profile(job_dir: Path, home: Path | None = None) -> str:
    home = home or Path.home()
    job = job_dir.resolve()
    codex = home / ".codex"
    return f"""(version 1)
(allow default)
(deny file-read* (subpath "{home}") (subpath "/Volumes") (subpath "/Users/Shared"))
(allow file-read* (literal "{home}") (literal "{home.parent}") (subpath "{codex}") (subpath "{job}"))
(deny file-write* (subpath "{home}"))
(allow file-write* (subpath "{codex}") (subpath "{job}"))
"""


def sandboxed(argv: list[str], job_dir: Path) -> list[str]:
    profile = job_dir / ".sandbox.sb"
    profile.write_text(sandbox_profile(job_dir), encoding="utf-8")
    return ["/usr/bin/sandbox-exec", "-f", str(profile), *argv]


CURRENT: dict[str, Path | None] = {"dir": None}  # 正在跑的这一次的任务目录（队列一次只跑一个）


def _job_dir() -> Path:
    job = CURRENT["dir"]
    if job is None:
        raise tools.ToolError("没有正在跑的任务目录")
    return job


def _tail(done: subprocess.CompletedProcess) -> str:
    return " / ".join((done.stderr or done.stdout or "").strip().splitlines()[-2:])[:200]


def sandboxed_text(prompt: str) -> str:
    from ... import llm

    job = _job_dir()
    spec = llm.parse_claude(shlex.split(tools.TEXT_COMMAND))
    with tempfile.TemporaryDirectory(prefix="cs-pub-") as tmp:
        out = Path(tmp) / "answer.txt"
        cmd = sandboxed(llm.codex_argv(spec, str(out)), job)
        try:
            done = subprocess.run(cmd, input=llm.codex_prompt(spec, prompt), capture_output=True, text=True,
                                  timeout=TEXT_TIMEOUT, check=False, cwd=str(job))
        except subprocess.TimeoutExpired as exc:
            raise tools.ToolError("这一次超时了，没有退你的额度以外的损失，再试一次") from exc
        try:
            answer = out.read_text(encoding="utf-8").strip()
        except OSError:
            answer = ""
    if done.returncode != 0 or not answer:
        raise tools.ToolError("这一次没成：" + (_tail(done) or "Codex 没回话"))
    return answer + "\n"


def _thread_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            return event.get("thread_id")
    return None


def sandboxed_paint(prompt: str, cwd: Path) -> tuple[list[Path], str]:
    """用 image_gen 画，返回（画出来的图按先后，最后一条回复）。图在沙盒外从 generated_images 里取走。"""
    from ... import conf, llm

    job = _job_dir()
    shots_dir = job / "shots"
    shots_dir.mkdir(exist_ok=True)
    # Codex 在一个主目录外的空临时目录里跑：工作目录在 ~ 下面时，沙盒会挡住它启动时往上找仓库、读设置（10/10 出图全挂在这）。
    # 出图只用 image_gen，用不到任务目录里的东西；画好的图在沙盒外拷回 job/shots。
    with tempfile.TemporaryDirectory(prefix="cs-pub-") as tmp:
        work = Path(tmp).resolve()
        out = work / "answer.txt"
        argv = [llm.codex_bin(), "exec", "--json", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral",
                "-m", conf.value("codex.model"), "-c", "project_doc_max_bytes=0",
                "-c", 'model_reasoning_effort="medium"', "-c", 'sandbox_mode="read-only"', "-c", 'web_search="disabled"',
                "-o", str(out), "-C", str(work), "-"]
        try:
            done = subprocess.run(sandboxed(argv, work), input=prompt, capture_output=True, text=True,
                                  timeout=IMAGE_TIMEOUT, check=False, cwd=str(work))
        except subprocess.TimeoutExpired as exc:
            raise tools.ToolError(f"超过 {IMAGE_TIMEOUT // 60} 分钟还没画完，停了") from exc
        try:
            answer = out.read_text(encoding="utf-8").strip()
        except OSError:
            answer = ""
    thread = _thread_id(done.stdout or "")
    if done.returncode != 0:
        raise tools.ToolError("出图失败：" + (_tail(done) or "Codex 没回话"))
    gen = Path.home() / ".codex/generated_images" / (thread or "-")
    found = sorted(gen.glob("*.png"), key=lambda p: p.stat().st_mtime) if thread and gen.is_dir() else []
    shots = []
    for i, src in enumerate(found, 1):
        dst = shots_dir / f"{i:02d}.png"
        shutil.copy(src, dst)
        shots.append(dst)
    if gen.is_dir():
        shutil.rmtree(gen, ignore_errors=True)
    return shots, answer


# -- 队列：一次跑一个，记着每个码的钱 -------------------------------------------------

class PublicQueue(tools.Queue):
    def __init__(self, store: codes.CodeStore, base: Path | None = None) -> None:
        super().__init__(base or base_dir())
        self.store = store
        self.on_finish = self._settle

    def _settle(self, run: dict[str, Any]) -> None:
        if run.get("state") == "failed" and run.get("owner") and not run.get("refunded"):
            self.store.refund(run["owner"], int(run.get("price") or 0))
            run["refunded"] = True
            self._write(run)

    def recover(self) -> None:
        """服务重启时断掉的那次：标成失败，钱退回去。"""
        stuck = [r for r in self.runs() if r["state"] == "running"]
        super().recover()
        for run in stuck:
            run.update(state="failed")
            self._settle(run)

    def run_one(self, run: dict[str, Any]) -> dict[str, Any]:
        CURRENT["dir"] = self._path(run["id"])
        try:
            return super().run_one(run)
        finally:
            CURRENT["dir"] = None

    def prune(self, days: int = KEEP_DAYS) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        gone = 0
        for folder in self.dir().glob("*/"):
            try:
                stamp = datetime.strptime(folder.name[:15], "%Y%m%d-%H%M%S")
            except ValueError:
                continue
            if stamp < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                gone += 1
        return gone


def use_sandbox() -> None:
    """这个进程里的所有任务都走沙盒（本机自己用的工作台是另一个进程，不受影响）。"""
    tools.TEXT["fn"] = sandboxed_text
    tools.PAINT["fn"] = sandboxed_paint
    tools.PUBLIC["on"] = True


# -- 接口 ----------------------------------------------------------------------

def create_app(store: codes.CodeStore | None = None, queue: PublicQueue | None = None, *, origins: tuple[str, ...] = ORIGINS,
               killed=None) -> Any:
    store = store or codes.CodeStore()
    queue = queue or PublicQueue(store)
    origins = (*origins, *[o for o in os.environ.get("CONTENT_STUDIO_TOOLS_ORIGINS", "").split(",") if o.strip()])  # 本机测试用
    is_killed = killed or (lambda: kill_file().exists())
    fails: dict[str, list[float]] = {}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_methods=["GET", "POST"],
                       allow_headers=["x-access-code", "content-type"], max_age=600)
    app.state.queue = queue
    app.state.store = store

    def who(request: Request) -> str:
        return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")

    def authed(request: Request, code: str | None) -> tuple[str, dict[str, Any]]:
        if is_killed():
            raise HTTPException(status_code=503, detail="暂时关了，晚点再来")
        ip = who(request)
        now = time.time()
        recent = [t for t in fails.get(ip, []) if now - t < FAIL_WINDOW]
        fails[ip] = recent
        if len(recent) >= FAIL_LIMIT:
            raise HTTPException(status_code=429, detail="输错次数太多了，过十分钟再试")
        found = store.lookup(code or "") if code else None
        if not found:
            recent.append(now)
            raise HTTPException(status_code=401, detail="邀请码不对，或者已经停用了")
        return found

    def public(run: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in run.items() if k != "owner"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "open": not is_killed()}

    @app.get("/api/tools")
    def tools_list(request: Request, x_access_code: str | None = Header(default=None)) -> dict[str, Any]:
        h, entry = authed(request, x_access_code)
        return {"tools": tools.catalog(), "styles": tools.STYLES, "runs": [public(r) for r in queue.runs(owner=h)],
                "balance": entry["balance"], "name": entry["name"], "queue": sum(1 for r in queue.runs() if r["state"] in ("waiting", "running"))}

    @app.post("/api/tools/{key}/run")
    def tools_run(key: str, body: dict[str, Any], request: Request, x_access_code: str | None = Header(default=None)) -> dict[str, Any]:
        h, entry = authed(request, x_access_code)
        if key not in tools.BY_KEY:
            raise HTTPException(status_code=400, detail="没有这个功能")
        for name, value in body.items():
            if isinstance(value, str) and len(value) > MAX_TEXT_FIELD.get(key, MAX_TEXT):
                raise HTTPException(status_code=400, detail=f"这一项太长了，最多 {MAX_TEXT_FIELD.get(key, MAX_TEXT)} 字")
        try:
            tools.clean_input(key, body)
        except tools.ToolError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        active = [r for r in queue.runs(owner=h) if r["state"] in ("waiting", "running")]
        if len(active) >= MAX_ACTIVE_PER_CODE:
            raise HTTPException(status_code=429, detail=f"你已经有 {len(active)} 个在排队或在跑，等它们好了再交")
        if sum(1 for r in queue.runs() if r["state"] == "waiting") >= MAX_WAITING:
            raise HTTPException(status_code=503, detail="现在排队的人多，晚点再试")
        price = tools.PRICE[key]
        if not store.charge(h, price):
            left = (store.get(h) or {"balance": 0})["balance"]
            raise HTTPException(status_code=402, detail=f"余额不够：这个功能 {codes.money(price)}，还剩 {codes.money(left)}")
        try:
            run = queue.submit(key, body, extra={"owner": h, "price": price, "token": secrets.token_urlsafe(12)})
        except tools.ToolError as exc:
            store.refund(h, price)
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {**public(run), "balance": (store.get(h) or {"balance": 0})["balance"]}

    def own(run_id: str, h: str) -> dict[str, Any]:
        try:
            run = queue.read(run_id)
        except tools.ToolError:
            raise HTTPException(status_code=404, detail="没有这一次") from None
        if run.get("owner") != h:
            raise HTTPException(status_code=404, detail="没有这一次")
        return run

    @app.get("/api/tools/runs/{run_id}")
    def tools_get(run_id: str, request: Request, x_access_code: str | None = Header(default=None)) -> dict[str, Any]:
        h, _ = authed(request, x_access_code)
        return public(own(run_id, h))

    @app.get("/api/tools/runs/{run_id}/file/{rel:path}")
    def tools_file(run_id: str, rel: str, t: str = "") -> FileResponse:
        """图是 <img src> 拉的，带不了请求头：每一次有一个只属于它的 token。"""
        if is_killed():
            raise HTTPException(status_code=503, detail="暂时关了，晚点再来")
        try:
            run = queue.read(run_id)
            token = str(run.get("token") or "")
            if not token or not secrets.compare_digest(token, t):
                raise HTTPException(status_code=404, detail="没有这张图")
            path = queue.file(run_id, rel)
        except tools.ToolError:
            raise HTTPException(status_code=404, detail="没有这张图") from None
        return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})

    return app


# -- 命令行 --------------------------------------------------------------------

def _dollars(text: str) -> int:
    return round(float(text) * 100)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m content_studio.extras.tools.public")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="起对外的小服务（只听 127.0.0.1，经隧道出去）")
    s.add_argument("--port", type=int, default=8783)
    c = sub.add_parser("codes", help="邀请码")
    cs = c.add_subparsers(dest="what", required=True)
    add = cs.add_parser("add", help="发一个新码")
    add.add_argument("--name", required=True, help="发给谁")
    add.add_argument("--dollars", default="5", help="额度，美元（默认 5）")
    cs.add_parser("list", help="看所有码的余额")
    up = cs.add_parser("topup", help="加额度")
    up.add_argument("id")
    up.add_argument("--dollars", required=True)
    off = cs.add_parser("off", help="停用一个码")
    off.add_argument("id")
    on = cs.add_parser("on", help="恢复一个码")
    on.add_argument("id")
    args = ap.parse_args(argv)
    store = codes.CodeStore()
    try:
        if args.cmd == "serve":
            import uvicorn

            use_sandbox()
            queue = PublicQueue(store)
            queue.recover()
            queue.prune()
            uvicorn.run(create_app(store, queue), host="127.0.0.1", port=args.port, log_level="info")
            return 0
        if args.what == "add":
            code = store.issue(args.name, _dollars(args.dollars))
            print(f"{args.name}  {codes.money(_dollars(args.dollars))}\n{code}\n（只显示这一次，发给他就行）")
        elif args.what == "list":
            for r in store.rows():
                print(f"{r['id']}  {r['name']:<10} 余额 {codes.money(r['balance']):>7}  已用 {codes.money(r['spent']):>7}  "
                      f"{r['runs']} 次  {'已停用' if r['disabled'] else ''}  {r.get('last_used', '')}")
        elif args.what == "topup":
            e = store.topup(args.id, _dollars(args.dollars))
            print(f"{e['name']} 现在 {codes.money(e['balance'])}")
        else:
            store.set_disabled(args.id, args.what == "off")
            print("好了")
    except codes.CodeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
