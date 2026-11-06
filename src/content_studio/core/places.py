"""工作台的东西放在哪：笔记库、视频盘、成片存档、每条内容的草稿目录、拆解报告。

原来是 create_app 里十几个小函数，主线和积木到处在用（video_root 22 处、vault_path 16 处）。
只认两样东西：store 里的设置（他在设置页填的路径），和启动时给的目录（草稿、数据、报告）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import vault, video_project
from ..store import StudioStore
from ..video_project import VideoProjectError


class Places:
    def __init__(self, store: StudioStore, *, drafts_root: Path, data_dir: Path, report_dirs: list[Path]) -> None:
        self.store = store
        self.drafts_root = drafts_root
        self.report_dirs = report_dirs
        self.backfill_root = data_dir / "backfill"

    # -- 他在设置里填的 --------------------------------------------------------------
    def vault_path(self) -> str:
        return self.store.settings()["obsidian_vault"]

    def video_root(self) -> Path:
        return video_project.resolve_root(self.store.settings()["video_projects_root"] or None)

    def archive_root(self) -> Path | None:
        from .. import archive

        return archive.usable_root(self.store.settings().get("douyin_archive"))

    def raw_root(self) -> Path:
        """笔记库里「我的原始输出」那个文件夹。"""
        raw = next((src for src in vault.INBOX_SOURCES if src.key == "raw"), None)
        if raw is None:
            raise ValueError("没配原始输出文件夹")
        return vault.vault_root(self.vault_path()) / raw.folder

    # -- 一条内容的东西 ----------------------------------------------------------------
    def topic_dir(self, topic_id: int) -> Path:
        """这条内容的草稿目录（口播、骨架、证据都在这）。"""
        return self.drafts_root / f"topic-{topic_id}"

    def article_path(self, topic: dict[str, Any]) -> Path | None:
        return Path(topic["article_path"]) if topic.get("article_path") else None

    def project_dir(self, topic_id: int) -> Path:
        """这条内容关联的视频项目文件夹。"""
        topic = self.store.topic(topic_id)
        if not topic.get("video_project"):
            raise ValueError("这个选题还没有关联视频项目")
        return video_project.project_dir(self.video_root(), topic["video_project"])

    def linked_project(self, topic_id: int) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        topic = self.store.topic(topic_id)
        if not topic.get("video_project"):
            raise ValueError("这个选题还没有关联视频项目")
        root = self.video_root()
        info = video_project.inspect(root, topic["video_project"])
        return topic, video_project.project_dir(root, topic["video_project"]), info

    def media_base(self, topic: dict[str, Any]) -> Path:
        """封面这类发布用的文件放哪：有视频项目就在项目里；补发的旧视频没有项目，放它自己的草稿目录。"""
        if topic.get("video_project"):
            return video_project.project_dir(self.video_root(), topic["video_project"])
        base = self.topic_dir(topic["id"])
        base.mkdir(parents=True, exist_ok=True)
        return base

    def final_video_path(self, topic: dict[str, Any]) -> Path | None:
        if not topic.get("video_project"):
            # 补发的旧视频：抖音成片存档里的那一份（或早先 backfill 目录里的）。只认这两个目录。
            from .. import archive

            vid = topic.get("published_video_id")
            if vid:
                found = archive.video_file(self.archive_root(), vid)
                if found is not None:
                    return found
            if topic.get("video_file"):
                try:
                    path = Path(topic["video_file"]).resolve()
                except OSError:
                    return None
                for base in [b for b in (self.archive_root(), self.backfill_root) if b is not None]:
                    try:
                        path.relative_to(base.resolve())
                    except (OSError, ValueError):
                        continue
                    return path if path.is_file() else None
            return None
        try:
            root = self.video_root()
            info = video_project.inspect(root, topic["video_project"])
        except VideoProjectError:
            return None
        if not info.get("final_video"):
            return None
        return video_project.safe_file(root, topic["video_project"], info["final_video"])

    # -- 拆解报告 ------------------------------------------------------------------------
    def report_file(self, video_id: str) -> Path | None:
        if not video_id.isdigit():
            return None
        for base in self.report_dirs:
            candidate = base / "reports" / video_id / "report.json"
            if candidate.is_file():
                return candidate
        return None

    def load_report(self, video_id: str) -> dict[str, Any] | None:
        """读一份拆解报告；老格式（schema_version < 2）当没有。"""
        path = self.report_file(video_id)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if data.get("schema_version", 1) >= 2 else None
