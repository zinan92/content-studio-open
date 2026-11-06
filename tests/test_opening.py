from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import opening
from content_studio.judge import JudgeLoginError

SRT = """1
00:00:00,133 --> 00:00:01,400
现在是 9 月 7 号

2
00:00:01,400 --> 00:00:02,533
今天来聊一下对于 AI

3
00:00:18,200 --> 00:00:20,000
不是 AI 不够强，是你只盯着它今天能干什么

4
00:01:05,000 --> 00:01:07,000
这一句超过 60 秒
"""


def _project(tmp_path: Path, rel: str = "subtitles/source.srt") -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SRT, encoding="utf-8")
    return tmp_path


def test_parse_and_prefer_finished_cut(tmp_path: Path) -> None:
    cues = opening.parse_srt(SRT)
    assert cues[0] == {"start": 0.133, "end": 1.4, "text": "现在是 9 月 7 号"} and cues[3]["start"] == 65
    _project(tmp_path)
    assert opening.find_subtitles(tmp_path)[1] == "原始录音"
    _project(tmp_path, "final-video.srt")
    assert opening.find_subtitles(tmp_path) == (tmp_path / "final-video.srt", "成片")


def test_thesis_comes_from_outline_main_line() -> None:
    md = "# 标题\n## 前 15 秒\n- a\n## 主线\n不是 AI 不够强\n\n## 第 1 段：x\n"
    assert opening.thesis_for(md, "标题") == "不是 AI 不够强"
    assert opening.thesis_for(None, "只有标题") == "只有标题"


def test_score_fails_when_thesis_lands_after_15_seconds(tmp_path: Path) -> None:
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"stated_at": 3.0, "quote": "编的话", "fixes": []}
        return {"stated_at": 18.2, "quote": "不是 AI 不够强，是你只盯着它今天能干什么", "before": "日期和寒暄", "fixes": ["删掉「现在是 9 月 7 号」，第一句直接说主线"]}

    result = opening.score_opening(_project(tmp_path), thesis="主线", opening_fn=fake)
    assert "stated_at 必须是" in prompts[1] and "超过 60 秒" not in prompts[0]
    assert result["passed"] is False and result["stated_at"] == 18.2 and result["source_label"] == "原始录音"
    assert result["first_15s"] == "现在是 9 月 7 号 今天来聊一下对于 AI"
    opening.save(tmp_path / "drafts", 3, result)
    assert opening.load(tmp_path / "drafts", 3)["fixes"] == result["fixes"]


def test_score_passes_early_and_handles_missing_or_logout(tmp_path: Path) -> None:
    good = {"stated_at": 1.4, "quote": "今天来聊一下对于 AI", "before": "", "fixes": ["保持"]}
    assert opening.score_opening(_project(tmp_path), thesis="t", opening_fn=lambda p: good)["passed"] is True
    with pytest.raises(opening.OpeningError, match="字幕文件"):
        opening.score_opening(tmp_path / "empty", thesis="t", opening_fn=lambda p: good)

    def logout(prompt):
        raise JudgeLoginError("login")

    with pytest.raises(JudgeLoginError):
        opening.score_opening(tmp_path, thesis="t", opening_fn=logout)
