"""The processing board: where each video in progress sits, derived from facts on disk.

Stages follow the shoot: 提纲 → 录制 → 剪辑 → 待发. Nothing asks 作者 to move a card;
the outline file, the linked project and its 14-step evidence decide the column.
"""
from __future__ import annotations

from typing import Any

STAGES = (
    ("outline", "提纲"),
    ("record", "录制"),
    ("edit", "剪辑"),
    ("ready", "待发"),
)
# The pipeline 作者 sees on the focus card: 选题 is "picked, no outline yet"; 已发出 closes it.
MILESTONES = (("topic", "选题"), ("outline", "提纲"), ("record", "录制"), ("edit", "剪辑"), ("ready", "待发"), ("shipped", "已发出"))
# Where a person is still needed. 剪辑 is the AI's, 待发 is whoever publishes.
MINE_STAGES = ("outline", "record")
SNOOZE_DAYS = 14


def is_shipped(topic: dict[str, Any]) -> bool:
    # A linked Douyin video ships a card; so does 作者 pressing 「发布完毕」 on the publish desk
    # (9/25: 发到 9 个平台、小宇宙先不发，这条就算结了). status=published can mean only the article went out.
    return bool(topic.get("published_video_id") or topic.get("closed_at"))


def stage_for(topic: dict[str, Any], project: dict[str, Any] | None, published: bool = False) -> str:
    # 10/20 作者 走查：进度看产物，不看机器 14 步跑到第几步。有成片（在外面剪完放进项目的也算）
    # 或者已经发出去一个平台，就是该发了；不然加工中会让人把剪好的视频再剪一遍。
    if published or (project and (project.get("delivered") or project.get("final_video"))):
        return "ready"
    if project and (project.get("current_step") or 0) >= 3:
        return "edit"
    if project and project.get("layout") == "legacy":
        return "edit"
    if project:
        return "record"
    if topic.get("outline_path"):
        # 作者 stepped back ("录到一半发现不行"): the outline exists but he wants to rework it first.
        return "outline" if topic.get("manual_stage") == "outline" else "record"
    return "outline"


def next_action(topic: dict[str, Any], stage: str, project: dict[str, Any] | None, opening: dict[str, Any] | None, qa: dict[str, Any] | None = None) -> dict[str, Any]:
    """One line telling 作者 what this card is waiting for, and whether it is waiting on him."""
    if topic.get("outline_state") == "running":
        return {"text": "提纲生成中", "mine": False}
    if topic.get("outline_state") == "failed":
        return {"text": "提纲生成失败，点开重试", "mine": True}
    if stage == "outline":
        return {"text": "写拍摄提纲", "mine": True}
    if stage == "record":
        if not project:
            # A verdict of thin/patch means the outline exists but the QA gate hasn't cleared it —
            # "提纲好了" would tell 作者 it's ready when the QA panel right below says the opposite.
            if qa and qa.get("verdict") == "thin":
                return {"text": "素材太薄，先补一处再录", "mine": True}
            if qa and qa.get("verdict") == "patch":
                return {"text": "三点没过，先补再录", "mine": True}
            return {"text": "提纲好了，可以录", "mine": True}
        return {"text": "录完把粗剪和字幕放进项目文件夹", "mine": True}
    if stage == "edit" and project and project.get("gate"):
        gate = project["gate"]
        return {"text": f"等你拍板：{gate['key']} {gate['title']}", "mine": True}
    if stage == "edit":
        return {"text": project.get("summary") or "剪辑中", "mine": False}
    if opening is not None and not opening.get("passed"):
        return {"text": "开头 15 秒没过，发之前看一眼", "mine": True}
    return {"text": "成片好了，去发", "mine": True}


def is_snoozed(topic: dict[str, Any], today: str) -> bool:
    return bool(topic.get("snoozed_until")) and str(topic["snoozed_until"]) > today


def milestone_index(topic: dict[str, Any], stage: str) -> int:
    if is_shipped(topic):
        return 5
    if stage == "outline" and not topic.get("outline_path"):
        return 0
    return {"outline": 1, "record": 2, "edit": 3, "ready": 4}[stage]


def card(topic: dict[str, Any], project: dict[str, Any] | None, opening: dict[str, Any] | None = None, qa: dict[str, Any] | None = None, published: bool = False) -> dict[str, Any]:
    stage = stage_for(topic, project, published)
    return {
        "focus": bool(topic.get("is_focus")),
        "snoozed_until": topic.get("snoozed_until"),
        "manual_stage": topic.get("manual_stage"),
        "milestone": milestone_index(topic, stage),
        "mine": stage in MINE_STAGES,
        "id": topic["id"],
        "title": topic["title"],
        "stage": stage,
        "created_at": topic["created_at"],
        "updated_at": topic.get("updated_at"),
        "has_outline": bool(topic.get("outline_path")),
        "has_article": bool(topic.get("article_path")),
        "project": {k: project.get(k) for k in ("name", "summary", "current_step", "delivered")} | {"has_final": bool(project.get("final_video"))} if project else None,
        "gate": project.get("gate") if project else None,
        "opening": {"passed": opening.get("passed"), "stated_at": opening.get("stated_at")} if opening else None,
        "qa": {"total": qa.get("total"), "verdict": qa.get("verdict")} if qa else None,
        "next": next_action(topic, stage, project, opening, qa),
    }
