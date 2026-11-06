"""Read the state of an ask-park-video (口播 workflow v2.6 layout) project from its artifacts.

This module only reads. Running the workflow to its next gate lives in workflow_runner.py;
nothing here edits a project. The artifact names and step numbers below are the contract
with the skill (SUPPORTED_LAYOUT); when the skill changes its layout, bump this together
with the tests in tests/test_video_project.py. A status label in
project.json only counts where the workflow itself has no required artifact; for every
other step the artifact is the evidence (the skill's own rule).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Callable

# Only used when neither profile.yaml nor the settings page names a directory.
DEFAULT_ROOTS = (Path("~/Movies/口播项目"),)
SUPPORTED_LAYOUT = "v2.6"
DONE_LABELS = {"pass", "approved", "skipped"}
STAGES = (
    ("A", "准备", (1, 2, 3, 4)),
    ("B", "Hook 与成品 A", (5, 6, 7, 8, 9)),
    ("C", "正文与视觉", (10, 11)),
    ("D", "声音与成品 B", (12, 13)),
    ("E", "合成交付", (14,)),
)
STEP_NAMES = {
    1: "项目设置", 2: "素材保全", 3: "媒体与字幕检查", 4: "字幕校准与 worktable",
    5: "选 Hook（H1）", 6: "正文 Content Map", 7: "Hook 精确截取", 8: "Hook 拼接与字幕",
    9: "成品 A 与 QA", 10: "正文 Picture Lock", 11: "视觉轨道（H2）", 12: "声音轨道",
    13: "成品 B 与 QA", 14: "合成、终审 QA（H3）",
}
# 剪映默认导出 .mov：成片是 .mov 时打包、发布也要读得到。
READABLE = {".html", ".json", ".md", ".mp4", ".mov", ".m4v", ".srt", ".txt", ".png", ".jpg"}


class VideoProjectError(ValueError):
    """Root missing or a path outside the projects root."""


def resolve_root(raw: str | None) -> Path:
    candidates = [Path(raw).expanduser()] if raw else [p.expanduser() for p in DEFAULT_ROOTS]
    for candidate in candidates:
        if candidate.is_dir():
            from . import icloud

            try:
                icloud.refuse_synced_root(candidate)
            except ValueError as exc:
                raise VideoProjectError(str(exc)) from None
            return candidate.resolve()
    shown = raw or str(DEFAULT_ROOTS[0])
    hint = "（外接硬盘可能没接上）" if shown.startswith("/Volumes/") else ""
    raise VideoProjectError(f"找不到视频项目目录：{shown}{hint}")


def project_dir(root: Path, name: str) -> Path:
    if not name or "/" in name or name.startswith(".") or "\x00" in name:
        raise VideoProjectError("视频项目名无效")
    path = (root / name).resolve()
    if path.parent != root or not path.is_dir():
        raise VideoProjectError("视频项目不存在")
    return path


def safe_file(root: Path, name: str, relative: str) -> Path:
    base = project_dir(root, name)
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise VideoProjectError("文件路径无效")
    path = (base / relative).resolve()
    if base not in path.parents or not path.is_file() or path.suffix.lower() not in READABLE:
        raise VideoProjectError("文件不存在")
    from . import icloud

    try:
        return icloud.ensure_local(path)
    except icloud.NotLocalError as exc:
        raise VideoProjectError(str(exc)) from None


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def qa_passed(path: Path) -> bool:
    data = _json(path)
    if not isinstance(data, dict):
        return False
    for key in ("pass", "passed", "ok"):
        if data.get(key) is True:
            return True
    for key in ("status", "verdict", "result"):
        if str(data.get(key) or "").lower() in {"pass", "passed", "ok", "通过"}:
            return True
    return False


def _nonempty_dir(path: Path) -> bool:
    return path.is_dir() and any(not p.name.startswith(".") for p in path.iterdir())


@dataclass
class Evidence:
    ok: bool
    note: str


def _step_checks(base: Path, contract: dict[str, Any]) -> dict[int, Callable[[], Evidence]]:
    exists = lambda rel: (base / rel).is_file()  # noqa: E731
    status = contract.get("step_status") or {}
    approvals = contract.get("approvals") or {}
    labelled = lambda n: str(status.get(str(n)) or status.get(n) or "").lower() in DONE_LABELS  # noqa: E731
    # 跳过也是一种「这步不用做了」。原来只有 Step 11 认 skipped，Hook 那四步（5/7/8/9）
    # 只看文件在不在——于是真跳过 Hook 的话，进度永远停在 Step 5，后面的动效走不到。
    skipped = lambda n: str(status.get(str(n)) or status.get(n) or "").lower() == "skipped"  # noqa: E731
    presets = contract.get("presets") or {}

    def clean_master_ok() -> Evidence:
        # 剪映粗剪本身就是 Clean Master 时，agent 不转码不复制，只在 edit.json 里指向它——这也算。
        # 只认项目目录里的文件。
        note = "part-b-body/clean-master.mp4（或 edit.json 指向的粗剪）+ edit.json"
        if not exists("part-b-body/edit.json"):
            return Evidence(False, note)
        if exists("part-b-body/clean-master.mp4"):
            return Evidence(True, note)
        edit = _json(base / "part-b-body/edit.json")
        master = edit.get("clean_master") if isinstance(edit, dict) else None
        rel = str(master.get("path") or "") if isinstance(master, dict) else ""
        target = (base / rel).resolve() if rel else None
        inside = target is not None and target.is_relative_to(base.resolve())
        return Evidence(bool(inside and target.is_file()), note)

    def presets_ok() -> Evidence:
        missing = [k for k in ("media", "audio", "caption_style", "caption_layout") if not presets.get(k)]
        return Evidence(bool(contract) and not missing, "project.json 与四个 preset" if not missing else f"project.json 缺 preset：{'、'.join(missing)}")

    return {
        1: presets_ok,
        2: lambda: Evidence(labelled(2), "素材清点记录（project.json step_status）"),
        3: lambda: Evidence(labelled(3), "媒体规格与硬字幕检查（project.json step_status）"),
        4: lambda: Evidence(
            exists("subtitles/source.srt") and exists("subtitles/transcript.sentences.json") and exists("analysis/worktable.html"),
            "subtitles/source.srt + transcript.sentences.json + analysis/worktable.html",
        ),
        5: lambda: Evidence(skipped(5) or (exists("analysis/worktable.json") and bool(approvals.get("hook"))), "analysis/worktable.json + Hook 批准记录（或记录为不做 Hook）"),
        6: lambda: Evidence(exists("analysis/content-map.md") or exists("analysis/content-map.json"), "analysis/content-map"),
        7: lambda: Evidence(skipped(7) or (_nonempty_dir(base / "part-a-hook/individual")), "part-a-hook/individual/ 截好的 Hook 片段（或记录为不做 Hook）"),
        8: lambda: Evidence(skipped(8) or (exists("part-a-hook/edit.json") and exists("part-a-hook/subtitles.srt")), "part-a-hook/edit.json + subtitles.srt（或记录为不做 Hook）"),
        9: lambda: Evidence(skipped(9) or (exists("part-a-hook/video.mp4") and qa_passed(base / "part-a-hook/qa.json")), "part-a-hook/video.mp4 + QA A 通过（或记录为不做 Hook）"),
        10: clean_master_ok,
        11: lambda: Evidence(
            (exists("part-b-body/visual-plan.json") and bool(approvals.get("visual_spec"))) or str(status.get("11") or "").lower() == "skipped",
            "visual-plan.json + 视觉规格批准（或记录为不加视觉）",
        ),
        12: lambda: Evidence(labelled(12) or exists("part-b-body/audio-plan.json"), "声音 preset 已应用（step_status 或 audio-plan.json）"),
        13: lambda: Evidence(exists("part-b-body/video.mp4") and qa_passed(base / "part-b-body/qa.json"), "part-b-body/video.mp4 + QA B 通过"),
        14: lambda: Evidence(exists("final/video.mp4") and qa_passed(base / "final/qa.json") and bool(approvals.get("final")), "final/video.mp4 + QA Final + 终审批准"),
    }


def _gate(base: Path, step: int | None, contract: dict[str, Any]) -> dict[str, str] | None:
    approvals = contract.get("approvals") or {}
    if step == 5 and (base / "analysis/worktable.html").is_file() and not (base / "analysis/worktable.json").is_file():
        return {"key": "H1", "title": "等你在 worktable 里选 Hook", "action": "打开 worktable，选 Hook、写画面备注，导出后放到 analysis/worktable.json"}
    if step == 5 and (base / "analysis/worktable.json").is_file() and not approvals.get("hook"):
        return {"key": "H1", "title": "等你批准 Hook 的句子和顺序", "action": "在 Claude/Codex 里看 Hook 候选并批准"}
    if step == 11 and (base / "part-b-body/visual-plan.json").is_file() and not approvals.get("visual_spec"):
        return {"key": "H2", "title": "等你批准视觉规格表", "action": "看视觉规格表，逐条确认采纳/调整/拒绝"}
    if step == 14 and (base / "final/video.mp4").is_file() and qa_passed(base / "final/qa.json") and not approvals.get("final"):
        return {"key": "H3", "title": "等你终审成片", "action": "看成片，确认可以交付"}
    return None


def process_log_tail(base: Path, limit: int = 5) -> list[dict[str, str]]:
    path = base / "process-log.md"
    if not path.is_file():
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            current = {"title": heading.group(1).strip(), "status": ""}
            entries.append(current)
            continue
        found = re.match(r"^-\s*status:\s*(\S+)", line.strip())
        if found and current is not None and not current["status"]:
            current["status"] = found.group(1)
    return entries[-limit:]


def inspect(root: Path, name: str) -> dict[str, Any]:
    base = project_dir(root, name)
    contract_path = base / "project.json"
    contract = _json(contract_path) if contract_path.is_file() else None
    artifacts = {
        rel: (base / rel).is_file()
        for rel in (
            "analysis/worktable.html", "analysis/worktable.json", "part-a-hook/video.mp4",
            "part-b-body/video.mp4", "final/video.mp4", "process-log.md",
        )
    }
    common = {
        "name": name,
        "path": str(base),
        "modified_at": datetime.fromtimestamp(base.stat().st_mtime).isoformat(timespec="minutes"),
        "continue_command": f"旧流程（14 步，10/21 已归档）的项目：在剪映里剪完，把成片放进 {base}/final/",
        "log": process_log_tail(base),
    }
    from .extras.motion import video_v2

    if video_v2.is_v2(base):
        st = video_v2.status(base)
        waiting = st.get("waiting_for")
        summary = st["step"] + (f" · 等 {waiting}" if waiting else (f" · {st['percent']}%" if st.get("percent") is not None else ""))
        if st.get("failed"):
            summary += f" · 出错：{st.get('detail')}"
        return {
            **common,
            "layout": "v2",
            "continue_command": f"用 park-video-v2 给这个口播项目加动效：{base}",
            "v2": st,
            "delivered": st["step"] == "已交付",
            "final_video": st.get("final"),
            "summary": summary,
            "steps": [],
            "stages": video_v2.stages(st),
            "current_step": None,
            "gate": None,
            "artifacts": {},
            "blocked_reason": None,
        }
    if not isinstance(contract, dict):
        from . import release

        final = release.find_video(base)
        entries = [p for p in base.iterdir() if not p.name.startswith(".")]
        fresh = all(p.name in ("README.md", "拍摄提纲.md") for p in entries)
        if final:
            summary = "成片在 final/ 里，可以去打包"
        elif fresh:
            summary = "还没开始：把剪映导出的粗剪放进来"
        else:
            summary = "粗剪已放进来：选这次怎么剪"
        return {
            **common,
            # 还没成片的新目录走 park-video-v2；旧版已交付的目录才是 ask-park-video 做的。
            **({} if final else {"continue_command": f"用 park-video-v2 给这个口播项目加动效：{base}"}),
            "layout": "fresh" if fresh and not final else "legacy",
            "delivered": bool(final),
            "final_video": final,
            "summary": summary,
            "steps": [],
            "stages": [],
            "current_step": None,
            "gate": None,
            "artifacts": {k: v for k, v in artifacts.items() if v},
            "blocked_reason": None,
        }
    checks = _step_checks(base, contract)
    # 在外面（剪映、Codex、手工）做完的步骤：作者 说了算，不再要求本目录里有机器产物。
    status = contract.get("step_status") or {}
    for n in list(checks):
        if str(status.get(str(n)) or "").lower() == "external":
            checks[n] = lambda: Evidence(True, "在外面做完了（记录在 project.json）")
    steps = []
    current = None
    for number in range(1, 15):
        evidence = checks[number]()
        if not evidence.ok and current is None:
            current = number
        steps.append({"step": number, "name": STEP_NAMES[number], "done": evidence.ok and (current is None or number < current), "evidence": evidence.note})
    stages = []
    for key, label, numbers in STAGES:
        passed = sum(1 for s in steps if s["step"] in numbers and s["done"])
        if passed == len(numbers):
            state = "done"
        elif current in numbers:
            state = "current"
        else:
            state = "todo"
        stages.append({"key": key, "label": label, "steps": list(numbers), "passed": passed, "total": len(numbers), "state": state})
    from . import release

    gate = _gate(base, current, contract)
    delivered = current is None
    return {
        **common,
        "layout": SUPPORTED_LAYOUT,
        "delivered": delivered,
        # 只用于显示和发布：认 final/ 下真实交付的那一个。Step 14 的判据不变，仍看 final/video.mp4。
        "final_video": release.find_video(base),
        "release": release.find_release(base),
        "h2_review": find_h2_review(base),
        "visual_target": contract.get("visual_coverage_target"),
        "visual_max": contract.get("visual_coverage_max"),
        "spec": contract.get("spec") or {},
        "hook_skipped": (contract.get("approvals") or {}).get("hook") == "skipped",
        "summary": "已交付" if delivered else (STEP_NAMES[current] + (f" · {gate['title']}" if gate else "")),
        "steps": steps,
        "stages": stages,
        "current_step": current,
        "gate": gate,
        "artifacts": {k: v for k, v in artifacts.items() if v},
        "blocked_reason": contract.get("blocked_reason"),
    }


# create_project names every folder 「日期_标题」. The exports drive also holds things other
# tools dropped there (npm/pip caches, cloned repos), so only that shape counts as a project —
# otherwise a 1.7 GB node_modules folder shows up in 剪辑进度 as a video waiting to be edited.
PROJECT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def is_project_name(name: str) -> bool:
    return bool(PROJECT_NAME.match(name))


def list_projects(root: Path, limit: int = 40) -> list[dict[str, Any]]:
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and is_project_name(p.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    results = []
    for path in dirs[:limit]:
        try:
            info = inspect(root, path.name)
        except (OSError, VideoProjectError):
            continue
        results.append({k: info[k] for k in ("name", "layout", "summary", "delivered", "current_step", "gate", "modified_at")})
    return results


def slug(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|#\s]+", "", title)[:24]
    return cleaned or "口播"


def back_to_choice(base: Path) -> str:
    """退回「粗剪放好了：加不加动效？」那一步。

    10/7 作者 点了「做动效」想退回来，只能取消关联。选了之后留下的东西——做动效转出来的 v2/、
    不加动效拷进 final/ 的成片——挪进一个点开头的「撤回」目录，不删：反悔了还能从那里找回来。
    """
    from . import release
    from .extras.motion import video_v2

    if (base / "project.json").is_file():
        raise ValueError("这是旧流程（14 步）的项目，没有「加不加动效」这一步")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if video_v2.is_v2(base):
        st = video_v2.status(base)
        if st.get("percent") is not None and not st.get("waiting_for") and not st.get("failed") and st.get("step") != "已交付":
            raise ValueError("正在渲染：等它跑完或者出错了再退回")
        (base / "v2").rename(base / f".v2-撤回-{stamp}")
        return f"退回了：动效的设置和产物收进了项目里的 .v2-撤回-{stamp}，没删"
    final = release.find_video(base)
    if final and final.startswith("final/"):
        (base / "final").rename(base / f".final-撤回-{stamp}")
        return f"退回了：拷进 final/ 的成片收进了项目里的 .final-撤回-{stamp}，粗剪还在"
    raise ValueError("这一条还没选做不做动效，不用退回")


def create_project(root: Path, *, title: str, today: str, outline_markdown: str | None = None) -> str:
    name = f"{today}_{slug(title)}"
    candidate, n = name, 2
    while (root / candidate).exists():
        candidate, n = f"{name}-{n}", n + 1
    base = root / candidate
    base.mkdir()
    (base / "README.md").write_text(
        f"# {title}\n\n由内容工作台创建。\n\n1. 把剪映粗剪视频和剪映导出的 SRT 放进这个文件夹（原始录制视频也可以放一份只读备份）。\n"
        f"2. 在 Claude 或 Codex 里说：用 park-video-v2 给这个口播项目加动效：{base}\n"
        "3. 进度会自动显示在内容工作台的「视频 → 剪辑进度」里。\n",
        encoding="utf-8",
    )
    if outline_markdown:
        (base / "拍摄提纲.md").write_text(outline_markdown, encoding="utf-8")
    return candidate


WORKTABLE_SCHEMA = "park-video-worktable/v1"
def import_worktable(root: Path, name: str, *, text: str, source: str = "粘贴", overwrite: bool = False) -> dict[str, Any]:
    """Save 作者's worktable export into analysis/worktable.json.

    The browser reads the exported file; the service never scans ~/Downloads, because a
    launchd process touching Downloads triggers a macOS privacy prompt and blocks.
    """
    base = project_dir(root, name)
    page = base / "analysis" / "worktable.html"
    if not page.is_file():
        raise VideoProjectError("这个项目还没有 worktable（Step 4 之后才有）")
    target = base / "analysis" / "worktable.json"
    if target.exists() and not overwrite:
        raise ValueError("analysis/worktable.json 已经存在；确认要覆盖再导入")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError("不是有效的 JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != WORKTABLE_SCHEMA:
        raise ValueError(f"不是 worktable 导出的文件（schema 应为 {WORKTABLE_SCHEMA}）")
    contract = _json(base / "project.json") or {}
    expected = contract.get("project") or contract.get("name")
    if expected and data.get("project") and data["project"] != expected:
        raise ValueError(f"这份 worktable 属于「{data['project']}」，不是这个项目「{expected}」")
    hooks = data.get("hooks") or []
    notes = data.get("visual_notes") or []
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    flagged = [h for h in hooks if h.get("anchor_status") != "ok"] + [n for n in notes if n.get("anchor_status") != "ok"]
    return {"source": source, "hooks": len(hooks), "visual_notes": len(notes), "needs_review": len(flagged), "path": str(target)}


# -- H2 审批页 ----------------------------------------------------------------
# 审批页引用了一大堆素材（Codex 那版 58 MB：18 个样片、36 张对照图）。按路径服务，
# 页面里的相对地址才解析得开；绝对的 file:// 地址在网页里会被浏览器拦掉，服务时改写。

RAW_TYPES = {
    ".html": "text/html; charset=utf-8", ".json": "application/json", ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".srt": "text/plain; charset=utf-8", ".vtt": "text/vtt",
    ".ts": "text/plain; charset=utf-8", ".tsx": "text/plain; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".woff": "font/woff", ".woff2": "font/woff2",
}


def raw_file(root: Path, name: str, relative: str) -> Path:
    """项目目录里的一个文件，给按路径的只读路由用。越界、隐藏目录、占位文件都拒。"""
    base = project_dir(root, name)
    parts = [p for p in relative.split("/") if p]
    if not parts or any(p in ("..", ".") or p.startswith(".") for p in parts) or "\x00" in relative:
        raise VideoProjectError("文件路径无效")
    path = (base / "/".join(parts)).resolve()
    # resolve 之后再比：符号链接指到项目外面也算越界。
    if base not in path.parents or not path.is_file() or path.suffix.lower() not in RAW_TYPES:
        raise VideoProjectError("文件不存在")
    from . import icloud

    try:
        return icloud.ensure_local(path)
    except icloud.NotLocalError as exc:
        raise VideoProjectError(str(exc)) from None


def find_h2_review(base: Path) -> str | None:
    """H2 审批页：优先 skill 的标准产物，其次 Codex 那种 h2-visual-review*.html，取最新。"""
    analysis = base / "analysis"
    standard = sorted((analysis / "visual-preview").glob("**/review*.html")) if (analysis / "visual-preview").is_dir() else []
    loose = sorted(analysis.glob("h2-visual-review*.html")) if analysis.is_dir() else []
    for group in (standard, loose):
        if group:
            return str(max(group, key=lambda p: p.stat().st_mtime).relative_to(base))
    return None


def rewrite_local_urls(html: str, base: Path, prefix: str) -> str:
    """把指向项目目录的 file:// 地址改成工作台路由。编码和未编码两种写法都有。"""
    from urllib.parse import quote

    for local in (quote(str(base)), str(base)):
        html = html.replace(f"file://{local}/", prefix)
    return html
