from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import titles
from content_studio.writer import WriterError

MATERIAL = "我看了 dontbesilent 开源 dbskill，一条视频 3 个私信。越想赚钱，越要先送产品。"


def _out(rows: list[str], people: str = "dontbesilent、dbskill") -> str:
    body = "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1))
    return f"<<<ARTICLE>>>\n## 点名的人\n{people}\n\n## 候选\n{body}\n<<<END>>>"


GOOD = [
    "我终于理解了dontbesilent为什么开源dbskill！｜借力点名｜依据：「我看了 dontbesilent 开源 dbskill」",
    "越想赚钱，越要先送产品｜悖论｜依据：「越想赚钱，越要先送产品」",
    "一条视频3个私信，靠什么活？｜算账｜依据：「一条视频 3 个私信」",
    "卖课这条路已经走到头了｜绝对否定｜依据：「……」",
    "知识博主最大的误会，是觉得内容就是产品｜攻击流行说法｜依据：「……」",
    "开源不是慈善，是最贵的广告｜悖论｜依据：「……」",
]


def test_parse_reads_people_and_candidates() -> None:
    r = titles.parse(_out(GOOD), material=MATERIAL)
    assert r["people"] == ["dontbesilent", "dbskill"]
    assert len(r["candidates"]) == 6
    assert r["candidates"][0] == {"title": "我终于理解了dontbesilent为什么开源dbskill！", "pattern": "借力点名",
                                  "basis": "「我看了 dontbesilent 开源 dbskill」", "over": True}  # 31 字：标出来，不退回
    assert not any(c["over"] for c in r["candidates"][1:])



def test_park_writing_heading_is_read_and_opening_candidates_are_not() -> None:
    # 10/20：park-writing 的「开头.md」让模型写「## 标题候选」，解析只认「## 候选」，一条都没读到
    body = "\n".join(f"{i}. {r}" for i, r in enumerate(GOOD, 1))
    out = ("<<<ARTICLE>>>\n## 开头候选\n推荐：数字\n1. 数字：「一条视频 3 个私信」（依据：「一条视频 3 个私信」）\n\n"
           f"## 点名的人\ndontbesilent、dbskill\n\n## 标题候选\n{body}\n\n## 话题\n自媒体，开源，私信，变现\n<<<END>>>")
    r = titles.parse(out, material=MATERIAL)
    assert [c["title"] for c in r["candidates"]] == [g.split("｜")[0] for g in GOOD]
    assert r["tags"] == ["自媒体", "开源", "私信", "变现"]
    with pytest.raises(WriterError, match="标题候选"):
        titles.parse(out.replace("## 标题候选", "## 标题"), material=MATERIAL)


def test_prompt_names_the_heading_parse_reads() -> None:
    prompt = titles.build_prompt({"title": "一句话"}, framework="## 输出\n## 开头候选", transcript="", skeleton="")
    assert "## 标题候选" in prompt and "不出开头候选" in prompt

def test_named_people_need_a_borrow_candidate() -> None:
    rows = [r for r in GOOD if "借力" not in r] + ["别再卖课了｜绝对否定｜依据：「……」"]
    with pytest.raises(WriterError, match="借力点名"):
        titles.parse(_out(rows), material=MATERIAL)
    assert titles.parse(_out(rows, people="无"), material=MATERIAL)["people"] == []


def test_numbers_must_come_from_the_material() -> None:
    rows = GOOD[:-1] + ["一条视频30个私信｜算账｜依据：「……」"]
    with pytest.raises(WriterError, match="数字原文里没有"):
        titles.parse(_out(rows), material=MATERIAL)


def test_count_limits() -> None:
    with pytest.raises(WriterError, match="6–10"):
        titles.parse(_out(GOOD[:4]), material=MATERIAL)
    with pytest.raises(WriterError, match="6–10"):
        titles.parse(_out(GOOD * 2), material=MATERIAL)


def test_write_titles_retries_once_then_saves(tmp_path: Path) -> None:
    (tmp_path / "wf").mkdir()
    (tmp_path / "wf" / "标题.md").write_text("---\nname: 标题\n---\n# 标题\n暴论。", encoding="utf-8")
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return _out(GOOD[:3]) if len(calls) == 1 else _out(GOOD)

    r = titles.write_titles({"id": 7, "title": "dbskill"}, transcript=MATERIAL, drafts_dir=tmp_path / "d",
                            write_fn=fn, workflows=tmp_path / "wf")
    assert len(calls) == 2 and "上一次输出有问题" in calls[1] and "暴论。" in calls[0] and MATERIAL in calls[0]
    assert titles.read_titles(tmp_path / "d", 7)["candidates"] == r["candidates"] and r["had_transcript"]


def test_missing_workflow_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(WriterError, match="找不到标题工作流"):
        titles.load_framework(tmp_path)


def test_srt_text_keeps_only_words(tmp_path: Path) -> None:
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n\n2\n00:00:01,000 --> 00:00:02,000\n世界\n", encoding="utf-8")
    assert titles.srt_text(srt) == "你好世界"


def test_parse_reads_content_tags_when_given_and_tolerates_none() -> None:
    """10/2：出标题顺带出内容话题，各平台都带。没给或太少不退回，标题照用。"""
    with_tags = _out(GOOD).replace("<<<END>>>", "\n## 话题\n#开源，dbskill，知识付费、个人IP，这是一个超过十二个字的太长话题\n<<<END>>>")
    assert titles.parse(with_tags, material=MATERIAL)["tags"] == ["开源", "dbskill", "知识付费", "个人IP"]
    assert titles.parse(_out(GOOD), material=MATERIAL)["tags"] == []
    two = _out(GOOD).replace("<<<END>>>", "\n## 话题\n开源，dbskill\n<<<END>>>")
    assert titles.parse(two, material=MATERIAL)["tags"] == []


def test_prompt_asks_for_content_tags_not_traffic_tags() -> None:
    prompt = titles.build_prompt({"title": "t"}, framework="f", transcript="", skeleton="")
    assert "## 话题" in prompt and "流量话题" in prompt
