"""02 排期（10/6 作者）：进项把东西放进选题池 → 排期定哪天拍哪一包 → 到了那天进加工中。

10/19 作者 拿掉了排期页：开始做只有「我的选题」里点「做这条」一个入口，整条流水线一次一条。
下面判断「有没有他的原话」「稿子模式」的函数照旧在用；日历那一半（清单顺序）留着不删，不再驱动正在做。

一个选题 = 一包：开头（暴论候选）、骨架、付息稿。规矩都是 作者 10/6 拍的板：
- 日历不留空档。日期不存，仍是「接下来要拍的」清单从第一个空着的日子往后一天一条（driver.queue_days）。
- 正在做 = 今天：正在做的那条永远在清单第一位；清单第一条也就是正在做的那条。
- 「写开头和骨架」只写有他原话的包：笔记在他的原始输出文件夹里（说过的系列集也存在那里）。
  别人的材料（日报快讯、Clippings、收藏）不算；还没说的跳过，告诉他跳过了几包。已经写好的不覆盖。
- 10/12 作者：已经有他自己的话（说过、写过、录过）的内容，不再写骨架、密度——那条路是给还没写出来的内容的。
  有他原话的包（content_mode = own）直接拿原话走 park-writing 第一轮（口播稿 + 批注视图）；骨架、密度只在他点「更多」时做。
  判断默认自动（挂了原始输出里的笔记、或者已经有视频），他在这条内容上能改（存在 drafts/topic-N/flow.json）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .board import is_shipped

STATE_FILE = "_schedule_write.json"  # 批量写的进度，放在 drafts 根下；服务重启后接着写


def own_words(topic: dict[str, Any], raw_folder: str) -> bool:
    """这包里有没有 作者自己的话：note_paths 里有一篇在他的原始输出文件夹下。"""
    prefix = raw_folder.strip("/") + "/"
    return any(str(p).startswith(prefix) for p in topic.get("note_paths") or [])


MODE_FILE = "flow.json"
MODES = ("own", "draft")


def mode_override(drafts_root: Path, topic_id: int) -> str | None:
    import json

    try:
        mode = json.loads((drafts_root / f"topic-{topic_id}" / MODE_FILE).read_text(encoding="utf-8")).get("mode")
    except (OSError, ValueError, AttributeError):
        return None
    return mode if mode in MODES else None


def set_mode(drafts_root: Path, topic_id: int, mode: str | None) -> None:
    """他在这条内容上改了「已经有我的话 / 还没有」；None = 回到自动判断。"""
    import json

    path = drafts_root / f"topic-{topic_id}" / MODE_FILE
    if mode is None:
        try:
            path.unlink()
        except OSError:
            pass
        return
    if mode not in MODES:
        raise ValueError("只能是「已经有我的话」或「还没有」")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mode": mode}), encoding="utf-8")


def content_mode(topic: dict[str, Any], raw_folder: str, drafts_root: Path) -> dict[str, Any]:
    """这条内容是不是已经有他自己的话了：own = 有（直接走第一轮）；draft = 还没有（才写骨架、密度）。"""
    override = mode_override(drafts_root, topic["id"])
    if override:
        return {"mode": override, "auto": False, "why": "你在这条内容上选的"}
    if own_words(topic, raw_folder):
        return {"mode": "own", "auto": True, "why": "挂了你原始输出里的笔记"}
    if topic.get("video_project") or topic.get("published_video_id"):
        return {"mode": "own", "auto": True, "why": "已经有视频，拍出来的话就是你的原话"}
    return {"mode": "draft", "auto": True, "why": "还没有你自己的话"}


def script_path(drafts_root: Path, topic_id: int) -> Path:
    return drafts_root / f"topic-{topic_id}" / "script.md"


def coupon_path(drafts_root: Path, topic_id: int) -> Path:
    from .coupon import FILENAME

    return drafts_root / f"topic-{topic_id}" / FILENAME


def has_hooks(topic: dict[str, Any]) -> bool:
    """骨架里有没有「开头候选」那一节（骨架的框架文件要求有；他手改掉了就算没有）。"""
    path = topic.get("outline_path")
    if not path:
        return False
    try:
        return "开头" in "".join(line for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines() if line.startswith("#"))
    except OSError:
        return False


def needs_writing(topic: dict[str, Any], drafts_root: Path, *, coupon: bool = True) -> bool:
    """还要写：没骨架，或者付息稿开着（10/9 能关）却还没写。"""
    return not topic.get("outline_path") or (coupon and not coupon_path(drafts_root, topic["id"]).is_file())


def focus_first(store: Any) -> None:
    """正在做的那条放到清单第一位（没有就加一行）。
    10/19 作者 拿掉排期：反过来那一半（没有正在做的，就让清单第一条成为正在做的）不要了——
    开始做只有一个入口：选题里点「做这条」。发完以后不会自动接上旧清单里的下一条。"""
    focus = store.focus_topic()
    if focus is None or is_shipped(focus):
        return
    notes = store.shoot_list()
    mine = next((n for n in notes if n.get("topic_id") == focus["id"]), None)
    if mine is None:
        store.add_shoot_item(focus["title"], topic_id=focus["id"], top=True)
    elif notes[0]["id"] != mine["id"]:
        store.place_shoot_item(mine["id"], 0)


def drop_notes(store: Any, topic_id: int) -> None:
    """这个选题从清单上拿掉（放回选题池 / 扔进回收站）。"""
    for note in store.shoot_list():
        if note.get("topic_id") == topic_id:
            store.delete_shoot_item(note["id"])


def targets(topics: list[dict[str, Any]], order: list[int], raw_folder: str, drafts_root: Path, *, coupon: bool = True,
            script: bool = False) -> dict[str, Any]:
    """按一下「准备稿子」会准备哪几包、跳过哪几包。order 是清单上的选题顺序：先写排得早的。
    script：这台机器能走 park-writing 第一轮（有 xline 块和带清单的 skill）。能走的话，有他原话的包准备的是口播稿，不写骨架、密度。"""
    rank = {tid: i for i, tid in enumerate(order)}
    todo, unspoken, others, empty = [], [], [], []
    for t in topics:
        if script and content_mode(t, raw_folder, drafts_root)["mode"] == "own":
            if not script_path(drafts_root, t["id"]).is_file():
                todo.append(t)
            continue
        if not needs_writing(t, drafts_root, coupon=coupon):
            continue
        if own_words(t, raw_folder):
            todo.append(t)
        elif t.get("_series"):
            unspoken.append(t["id"])
        elif t.get("note_paths"):
            others.append(t["id"])
        else:
            empty.append(t["id"])
    todo.sort(key=lambda t: (rank.get(t["id"], len(rank)), t["id"]))
    return {"ids": [t["id"] for t in todo], "unspoken": unspoken, "others": others, "empty": empty}


def skip_line(unspoken: int, others: int, empty: int = 0) -> str:
    parts = []
    if unspoken:
        parts.append(f"{unspoken} 包还没说，没有你的原话")
    if others:
        parts.append(f"{others} 包只有别人的材料")
    if empty:
        parts.append(f"{empty} 包还没有材料")
    return "，".join(parts)
