"""The skills 作者 uses for content, grouped by step, editable from 「设置与 Skills」.

The repo ships a seed (`config/skills.json`, generic and public). The first time the
workbench reads the list it copies the seed to the user's own file
(`<config_dir>/skills.json`); from then on every add / edit / delete goes to that file, so
作者's own frameworks and local paths never land in the public repo.

Third-party skills are listed by name, author and repository only; their files are never
copied into this repository. A card can show the skill's own Markdown (its SKILL.md, or the
framework file it points at) read-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from . import writing_rules

from .paths import config_dir
from .vault import parse_frontmatter

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "skills.json"
USER_FILE = "skills.json"
SKILL_ROOTS = (Path("~/.agents/skills"), Path("~/.claude/skills"), Path("~/.codex/skills"))
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_DOC_CHARS = 60000


class SkillsError(ValueError):
    """Shown to 作者 as-is."""


def user_path(root: Path | None = None) -> Path:
    return (root or config_dir()) / USER_FILE


def _read_registry(seed: Path, user: Path | None) -> dict[str, Any]:
    if user is not None and user.is_file():
        return json.loads(user.read_text(encoding="utf-8"))
    return json.loads(seed.read_text(encoding="utf-8"))


def _write_registry(user: Path, data: dict[str, Any]) -> None:
    user.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(user.parent), prefix=".skills-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, user)


def _description(skill_md: Path) -> str | None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.match(r"\A---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None
    block = match.group(1)
    folded = re.search(r"^description:\s*[|>][-+]?\s*\n((?:[ \t]+.*\n?)+)", block, re.MULTILINE)
    if folded:
        return " ".join(line.strip() for line in folded.group(1).splitlines() if line.strip())[:300]
    meta, _ = parse_frontmatter(text)
    return (meta.get("description") or None) and meta["description"][:300]


ANNA_ROLE_ENV = "CONTENT_STUDIO_ANNA_ROLE"
WORKFLOWS_ENV = "CONTENT_STUDIO_WORKFLOWS"


def doc_roots(roots: tuple[Path, ...] = SKILL_ROOTS) -> list[Path]:
    """Where a card's Markdown may come from: the skill folders, and Anna's own folder
    (her knowledge and the writing frameworks). Nothing else — the vault holds _secrets,
    and the site is reachable with a password."""
    out = [r.expanduser() for r in roots]
    role = os.environ.get(ANNA_ROLE_ENV)
    if role:
        out.append(Path(role).expanduser().with_suffix(""))
    wf = os.environ.get(WORKFLOWS_ENV)
    if wf:
        out.append(Path(wf).expanduser())
    return out


def safe_doc_path(raw: str, roots: tuple[Path, ...] = SKILL_ROOTS) -> Path | None:
    try:
        p = Path(raw).expanduser().resolve()
    except OSError:
        return None
    for base in doc_roots(roots):
        try:
            p.relative_to(base.resolve())
        except (OSError, ValueError):
            continue
        return p if p.is_file() and p.suffix.lower() == ".md" else None
    return None


def _local_doc(entry: dict[str, Any], roots: tuple[Path, ...]) -> Path | None:
    """The Markdown a card shows: a framework file the entry points at, else the skill's SKILL.md."""
    if entry.get("path"):
        return safe_doc_path(entry["path"], roots)
    if entry.get("dir"):
        for root in roots:
            candidate = root.expanduser() / entry["dir"] / "SKILL.md"
            if candidate.is_file():
                return candidate
    return None


def load_skills(registry_path: Path = REGISTRY_PATH, roots: tuple[Path, ...] = SKILL_ROOTS, user: Path | None = None) -> dict[str, Any]:
    registry = _read_registry(registry_path, user)
    stages = {stage["key"] for stage in registry["stages"]}
    skills = []
    for entry in registry["skills"]:
        if entry["stage"] not in stages:
            raise ValueError(f"skill {entry['name']} has unknown stage {entry['stage']}")
        doc = _local_doc(entry, roots)
        skills.append(
            {
                **entry,
                "installed": doc is not None,
                "local_path": str(doc).replace(str(Path.home()), "~") if doc else None,
                "description": _description(doc) if doc and doc.name == "SKILL.md" else None,
                "source_known": bool(entry.get("author") and (entry.get("repo") or entry.get("path"))),
            }
        )
    return {"stages": registry["stages"], "skills": skills, "editable": user is not None,
            "file": str(user).replace(str(Path.home()), "~") if user is not None else None}


FIELDS = ("name", "title", "stage", "use", "invoke", "author", "repo", "dir", "path", "own")


def clean_entry(raw: dict[str, Any], stages: set[str]) -> dict[str, Any]:
    entry = {k: raw.get(k) for k in FIELDS}
    entry["name"] = str(entry["name"] or "").strip()
    if not NAME.match(entry["name"]):
        raise SkillsError("名字只能用字母、数字、点、横线和下划线，比如 khazix-writer")
    entry["title"] = str(entry["title"] or "").strip()[:40] or entry["name"]
    if entry["stage"] not in stages:
        raise SkillsError("选一个它用在哪一步")
    entry["use"] = str(entry["use"] or "").strip()[:300]
    if not entry["use"]:
        raise SkillsError("写一句它用来做什么")
    entry["invoke"] = str(entry["invoke"] or "").strip()[:300] or f"在 Claude 里说：用 {entry['name']}"
    entry["author"] = (str(entry["author"]).strip()[:60] or None) if entry["author"] else None
    repo = str(entry["repo"] or "").strip()
    if repo and not repo.startswith("https://"):
        raise SkillsError("链接要以 https:// 开头，比如 GitHub 仓库地址")
    entry["repo"] = repo or None
    entry["dir"] = (str(entry["dir"]).strip() or None) if entry["dir"] else None
    if entry["dir"] and not NAME.match(entry["dir"]):
        raise SkillsError("本机 skill 目录名只写文件夹名，比如 khazix-writer")
    path = str(entry["path"] or "").strip()
    if path and not (path.startswith("~/") and path.endswith(".md")):
        raise SkillsError("本机文件写成 ~/ 开头的 .md 路径")
    entry["path"] = path or None
    entry["own"] = bool(entry["own"])
    return entry


def upsert(raw: dict[str, Any], *, user: Path, registry_path: Path = REGISTRY_PATH, previous: str | None = None) -> dict[str, Any]:
    data = _read_registry(registry_path, user)
    entry = clean_entry(raw, {s["key"] for s in data["stages"]})
    names = [s["name"] for s in data["skills"]]
    target = previous or entry["name"]
    if entry["name"] != target and entry["name"] in names:
        raise SkillsError("已经有一个同名的 skill")
    if target in names:
        data["skills"][names.index(target)] = entry
    else:
        if entry["name"] in names:
            raise SkillsError("已经有一个同名的 skill")
        data["skills"].append(entry)
    _write_registry(user, data)
    return entry


def remove(name: str, *, user: Path, registry_path: Path = REGISTRY_PATH) -> bool:
    data = _read_registry(registry_path, user)
    kept = [s for s in data["skills"] if s["name"] != name]
    if len(kept) == len(data["skills"]):
        return False
    data["skills"] = kept
    _write_registry(user, data)
    return True


def read_doc(name: str, *, user: Path | None, registry_path: Path = REGISTRY_PATH, roots: tuple[Path, ...] = SKILL_ROOTS) -> dict[str, Any]:
    """A listed skill's Markdown, read-only. Only files that belong to a listed entry."""
    data = _read_registry(registry_path, user)
    entry = next((s for s in data["skills"] if s["name"] == name), None)
    if entry is None:
        raise SkillsError("没有这个 skill")
    doc = _local_doc(entry, roots)
    if doc is None:
        raise SkillsError("本机没有这个 skill 的文件")
    meta, body = parse_frontmatter(doc.read_text(encoding="utf-8", errors="replace"))
    return {"name": entry.get("title") or name, "path": str(doc).replace(str(Path.home()), "~"), "body": body[:MAX_DOC_CHARS]}


# -- 流程图：哪一步真在调用哪个 skill -------------------------------------------------
# 10/5 作者：设置页要看出 skill 挂在流程哪一步、哪些在用哪些没用。「在不在流程中」不让人填：
# 接线从各模块自己的常量读（换了 skill，这里跟着变），清单里有、哪一步都没接的，就是不在流程中。
# 阶段和步骤照左栏 01–05（10/19 排期拿掉，那一段改叫「写稿」；以后左栏改了，改这一处）。group 相同且相邻的步骤是同时进行的几条路。

STAGE_FLOW: tuple[dict[str, Any], ...] = (
    {"key": "in", "label": "选题", "sub": "看什么热", "steps": (
        {"key": "sources", "label": "对标 · 日报 · 收藏 · Clippings", "note": "几路同时进来，你点进去看"},
        {"key": "teardown", "label": "拆解", "note": "转写 + Claude 判断，不用 skill", "group": "看完三个出口"},
        {"key": "take", "label": "做这个", "note": "变成选题", "group": "看完三个出口"},
        {"key": "xpost", "label": "发 X", "note": "按「X 写作风格.md」写建议稿，你点了才发", "group": "看完三个出口"},
    )},
    {"key": "plan", "label": "写稿", "sub": "点「做这条」之后", "steps": (
        {"key": "pick", "label": "做这条", "note": "一次只有一条，发完才轮到下一条"},
        {"key": "outline", "label": "写骨架", "made": "skeleton.md", "note": "只写有你原话的"},
        {"key": "qa", "label": "三点评分", "made": "qa.json"},
        {"key": "coupon", "label": "密度", "made": "coupon.md"},
    )},
    {"key": "work", "label": "加工中", "sub": "今天这一条", "steps": (
        {"key": "evidence", "label": "按论点找证据", "note": "你点「要」才算"},
        {"key": "project", "label": "建项目 → 录 → 剪映", "note": "项目结构和字幕预设"},
        {"key": "motion", "label": "动效", "made": "v2/"},
    )},
    {"key": "pack", "label": "打包", "sub": "你只定标题，其余排队一个个做", "steps": (
        {"key": "titles", "label": "定标题", "made": "titles.json"},
        {"key": "copy", "label": "描述 + 话题", "note": "各平台一次填好"},
        {"key": "cover", "label": "封面", "made": "covers/"},
        {"key": "article", "label": "文章", "made": "article.md"},
        {"key": "figs", "label": "插图", "made": "illustrations/"},
        {"key": "wx", "label": "公众号排版", "made": "article.gzh.html"},
    )},
    {"key": "pub", "label": "发布", "sub": "没有 skill", "steps": (
        {"key": "x", "label": "X 先发"},
        {"key": "core", "label": "抖音 · 小红书 · 视频号", "note": "你传", "group": "同时"},
        {"key": "rest", "label": "B 站 · YouTube · 公众号", "note": "最后，自动"},
    )},
    {"key": "out", "label": "已发出", "sub": "没有 skill", "steps": (
        {"key": "track", "label": "全平台追踪"},
        {"key": "metrics", "label": "数据回流 · 出摊"},
    )},
)
USAGE_DAYS = 14


def wiring(writer_skill: str = "") -> dict[str, list[dict[str, Any]]]:
    """step key → the skills that step calls today, read off each module's own constants.

    A wired skill is matched to a list entry by its folder (`dir`) or by the framework file's
    name (`file`); `name`/`title`/`use` only fill in a card when the list doesn't have it."""
    from . import coupon, gzh_layout, illustrate, koubo, outline, qa, titles
    from .extras.motion import video_v2

    qa_dir = Path(os.environ.get(qa.QA_GUIDE_ENV) or qa.DEFAULT_GUIDE).expanduser().parent.name
    koubo_dir = koubo.skill_dir().name
    wired: dict[str, list[dict[str, Any]]] = {
        "outline": [{"file": outline.FRAMEWORK_FILE, "name": "yigou-skeleton", "title": outline.LABEL, "use": "写提纲用的框架：主线、开头候选、论点、结尾"}],
        "qa": [{"dir": qa_dir, "name": qa_dir, "title": "三点评分", "use": "痛点具象、认知反差、交付可行三点打分"}],
        "coupon": [{"file": coupon.FRAMEWORK_FILE, "name": "coupon-frame", "title": coupon.LABEL, "use": "口播稿：开头发债、每段付息、结尾兑付"}],
        "project": [{"dir": koubo_dir, "name": koubo_dir, "title": "口播视频全流程", "use": "标 Hook 的表、切 Hook、封面风格参考（10/21 起和动效同一个 skill）"}],
        "motion": [{"dir": video_v2.home().name, "name": video_v2.home().name, "title": "口播动效", "use": "给口播视频加动效：方案、10 秒样片、整条、质检"},
                   {"dir": video_v2.SHOTCRAFT, "name": video_v2.SHOTCRAFT, "title": "镜头配方视频", "use": "动效组件的样式来源"}],
        "titles": [{"file": titles.FRAMEWORK_FILE, "name": "titles-frame", "title": "标题框架", "use": "出标题候选时读的框架"}],
        "cover": [{"dir": koubo_dir, "name": koubo_dir, "title": "口播视频全流程", "use": "封面的风格参考图"}],
        "figs": [_figs_skill()],
        "wx": [{"dir": gzh_layout.SKILL_DIR.name, "name": gzh_layout.SKILL_DIR.name, "title": "公众号排版", "use": "Markdown → 公众号 HTML"}],
    }
    if writer_skill:
        wired["article"] = [{"dir": writer_skill, "name": writer_skill, "title": writer_skill, "use": "写文章用的 skill（设置里选的）"}]
    return wired


def _figs_skill() -> dict[str, Any]:
    """配图用哪个 skill：有自己的形象 skill（<slug>-ip-illustrations）就是它，没有就是小黑（10/7）。"""
    from . import illustrate
    from .extras.positioning import persona

    own = persona.skill()
    if own:
        name = persona.character()["name"]
        return {"dir": own, "name": own, "title": f"{name} IP 配图", "use": f"小黑的画法，主角换成 {name}；给文章配 4–8 张"}
    return {"dir": illustrate.SKILL, "name": illustrate.SKILL, "title": "小黑正文配图", "use": "给文章配 4–8 张手绘图"}


def _matches(entry: dict[str, Any], spec: dict[str, Any]) -> bool:
    if spec.get("dir") and spec["dir"] in (entry.get("dir"), entry.get("name")):
        return True
    return bool(spec.get("file") and entry.get("path") and Path(entry["path"]).name == spec["file"])


def _home_path(path: Path) -> str | None:
    """A path `clean_entry` accepts (~/….md), or None when it lives outside home."""
    try:
        return "~/" + str(path.expanduser().resolve().relative_to(Path.home().resolve()))
    except (OSError, ValueError):
        return None


def _scan(root: Path, made: set[str], since: float) -> dict[str, list[float]]:
    """mtimes of the files / folders each step leaves behind, one topic folder at a time."""
    hits: dict[str, list[float]] = {m: [] for m in made}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (n + "/" for n in dirnames):
            if name in made:
                t = (Path(dirpath) / name).stat().st_mtime
                if t >= since:
                    hits[name].append(t)
        for name in filenames:
            if name in made:
                t = (Path(dirpath) / name).stat().st_mtime
                if t >= since:
                    hits[name].append(t)
        dirnames[:] = [d for d in dirnames if d + "/" not in made]  # don't descend into what we counted
    return hits


def usage(drafts: Path | None, video_root: Path | None, *, now: float | None = None) -> dict[str, dict[str, Any]]:
    """step key → {count, last} over the last USAGE_DAYS days. Cheap and never raises:
    the drafts folder by mtime, video projects only one level deep (`root/*/v2`)."""
    import time

    now = now or time.time()
    since = now - USAGE_DAYS * 86400
    steps = [s for st in STAGE_FLOW for s in st["steps"] if s.get("made")]
    out: dict[str, dict[str, Any]] = {}

    def put(key: str, times: list[float]) -> None:
        out[key] = {"count": len(times), "last": time.strftime("%m/%d", time.localtime(max(times))) if times else None}

    hits: dict[str, list[float]] = {}
    if drafts is not None:
        try:
            hits = _scan(drafts.expanduser(), {s["made"] for s in steps if s["made"] != "v2/"}, since)
        except OSError:
            hits = {}
    for s in steps:
        if s["made"] == "v2/":
            continue
        put(s["key"], hits.get(s["made"], []))
    if video_root is None:
        out["motion"] = {"count": None, "last": None, "missing": "视频盘没接上"}
    else:
        try:
            root = video_root.expanduser()
            if not root.is_dir():
                out["motion"] = {"count": None, "last": None, "missing": "视频盘没接上"}
            else:
                times = [p.stat().st_mtime for p in (d / "v2" for d in root.iterdir() if d.is_dir()) if p.is_dir()]
                put("motion", [t for t in times if t >= since])
        except OSError:
            out["motion"] = {"count": None, "last": None, "missing": "视频盘读不了"}
    return out


def flow_view(skills: list[dict[str, Any]], stages: list[dict[str, Any]], *, writer_skill: str = "",
              drafts: Path | None = None, video_root: Path | None = None) -> dict[str, Any]:
    """The flow with each step's skills, and every listed skill marked in or out of it.

    Skills a step calls but the list doesn't have come back as extra cards (`listed: False`),
    with what 「加进清单」 needs to prefill the form."""

    wired = wiring(writer_skill)
    used = usage(drafts, video_root)
    stage_label = {s["key"]: s["label"] for s in stages}
    cards = [{**s, "listed": True, "in_flow": False, "steps": []} for s in skills]
    flow = []
    for stage in STAGE_FLOW:
        steps = []
        for step in stage["steps"]:
            names = []
            for spec in wired.get(step["key"], []):
                card = next((c for c in cards if _matches(c, spec)), None)
                if card is None:
                    path = _home_path(writing_rules.current_path(spec["file"])) if spec.get("file") else None
                    card = {"name": spec["name"], "title": spec["title"], "use": spec["use"], "dir": spec.get("dir"),
                            "path": path, "listed": False, "in_flow": False, "steps": [], "own": bool(spec.get("file")),
                            "installed": False, "stage": None}
                    cards.append(card)
                card["in_flow"] = True
                if step["label"] not in card["steps"]:
                    card["steps"].append(step["label"])
                names.append(card["name"])
            steps.append({k: step.get(k) for k in ("key", "label", "note", "group")} | {"skills": names, "used": used.get(step["key"])})
        flow.append({"key": stage["key"], "label": stage["label"], "sub": stage["sub"], "steps": steps})
    for c in cards:
        c["was"] = stage_label.get(c.get("stage"))
    return {"flow": flow, "cards": cards, "usage_days": USAGE_DAYS}
