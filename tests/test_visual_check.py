from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio import visual_check


@pytest.fixture
def shots_root(tmp_path: Path) -> Path:
    root = tmp_path / "shots"
    (root / "data").mkdir(parents=True)
    (root / "data" / "odometer-digit-roll.md").write_text(
        "---\nname: odometer-digit-roll\n一句话: 数字滚动\n适用: 定量\n时长: 约5.0s（150f@30fps）\n能量: 中\n---\n正文\n",
        encoding="utf-8",
    )
    (root / "data" / "list-reveal.md").write_text(
        "---\nname: list-reveal\n时长: 约2.0s（60f@30fps）\n---\n", encoding="utf-8"
    )
    return root


def _plan(tmp_path: Path, shots: list[dict]) -> Path:
    path = tmp_path / "visual-plan.json"
    path.write_text(json.dumps({"shots": shots}, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_shot_that_does_not_fit_its_window_is_caught(tmp_path: Path, shots_root: Path) -> None:
    """真发生过：odometer 一遍 5 秒，要依次亮 10/20/30 三个值，窗口只有 6.7 秒。

    这是乘法，不该占用一次模型评审往返。
    """
    plan = _plan(tmp_path, [{
        "id": "V02", "start": 91.5, "end": 98.2,
        "recipe": {"name": "odometer-digit-roll"}, "relabel_stages": [92.0, 94.0, 96.0],
    }])
    out = visual_check.run(plan, shots_root=shots_root)
    assert out["status"] == "fail"
    f = next(x for x in out["findings"] if x["kind"] == "over-budget")
    assert "5 秒 × 3 段 = 15 秒" in f["detail"] and "6.7 秒" in f["detail"]

    # 窗口拉够就不该再报
    wide = _plan(tmp_path, [{
        "id": "V02", "start": 91.5, "end": 120.0,
        "recipe": {"name": "odometer-digit-roll"}, "relabel_stages": [92.0, 94.0, 96.0],
    }])
    assert visual_check.run(wide, shots_root=shots_root)["status"] == "pass"

    # 段数只认结构化字段。从 motion 散文里数数字试过，在真实 plan 上误报成 10 段——
    # 会误报的检查比没有检查更糟，它会让 agent 去修一个不存在的问题。
    prose = _plan(tmp_path, [{
        "id": "V02", "start": 91.5, "end": 98.2,
        "recipe": {"name": "odometer-digit-roll"}, "motion": "终值依次为10、20、30，减速16f、回弹6f",
    }])
    assert visual_check.run(prose, shots_root=shots_root)["status"] == "pass"


def test_a_shot_anchored_to_the_wrong_second_is_caught(tmp_path: Path, shots_root: Path) -> None:
    """真发生过：镜头开在 550.9s，那句话其实是 563s 说的，差 12 秒。

    只有拿到词级时间才查得了——用插值出来的时间去校验插值，没有意义。
    """
    words = tmp_path / "words.json"
    words.write_text(json.dumps({"words": [
        {"w": "从产品", "start": 563.0, "end": 563.6},
        {"w": "哪里", "start": 563.6, "end": 564.1},
        {"w": "出发呢", "start": 564.1, "end": 565.0},
    ]}, ensure_ascii=False), encoding="utf-8")
    plan = _plan(tmp_path, [{"id": "V07", "start": 550.9, "end": 573.5, "quote": "从产品哪里出发呢"}])
    out = visual_check.run(plan, shots_root=shots_root, words_path=words)
    assert out["had_word_timings"] is True
    f = next(x for x in out["findings"] if x["kind"] == "anchor-drift")
    assert "550.9s" in f["detail"] and "563.0s" in f["detail"] and "12.1 秒" in f["detail"]

    # 对上了就不报；标点不一致也要能匹配上
    ok = _plan(tmp_path, [{"id": "V07", "start": 563.0, "end": 565.0, "quote": "从产品，哪里出发呢？"}])
    assert visual_check.run(ok, shots_root=shots_root, words_path=words)["status"] == "pass"


def test_quoting_something_that_was_never_said(tmp_path: Path, shots_root: Path) -> None:
    words = tmp_path / "words.json"
    words.write_text(json.dumps({"words": [{"w": "他说", "start": 1.0, "end": 1.5}]}, ensure_ascii=False), encoding="utf-8")
    plan = _plan(tmp_path, [{"id": "V01", "start": 1.0, "end": 3.0, "quote": "这句话根本没说过"}])
    out = visual_check.run(plan, shots_root=shots_root, words_path=words)
    assert out["findings"][0]["kind"] == "anchor-missing"


def test_a_card_that_does_not_exist_is_caught(tmp_path: Path, shots_root: Path) -> None:
    """名字对不上，说明那张卡根本没被读过——评审的原话是 a name alone is not use evidence。"""
    plan = _plan(tmp_path, [{"id": "V03", "start": 0, "end": 10, "recipe": {"name": "我编的卡"}}])
    out = visual_check.run(plan, shots_root=shots_root)
    assert out["findings"][0]["kind"] == "card-missing" and "我编的卡" in out["findings"][0]["detail"]


def test_quantitative_shots_must_say_how_to_verify(tmp_path: Path, shots_root: Path) -> None:
    """画错了没人发现，是因为没人说过「画完怎么量」。"""
    bare = _plan(tmp_path, [{"id": "V05", "start": 0, "end": 20, "quantitative": True,
                             "recipe": {"name": "list-reveal"}}])
    assert visual_check.run(bare, shots_root=shots_root)["findings"][0]["kind"] == "no-verification"

    # 抽了帧，但漏掉了这个镜头的关键阶段
    gap = _plan(tmp_path, [{"id": "V09", "start": 443, "end": 471, "quantitative": True,
                            "recipe": {"name": "list-reveal"}, "relabel_stages": [453.5, 456.6, 465.6],
                            "chart": {"rendered_verification": {"frames": [449.0, 452.5]}}}])
    f = visual_check.run(gap, shots_root=shots_root)["findings"][0]
    assert f["kind"] == "verification-gap" and "453.5" in f["detail"]

    good = _plan(tmp_path, [{"id": "V09", "start": 443, "end": 471, "quantitative": True,
                             "recipe": {"name": "list-reveal"}, "relabel_stages": [453.5, 465.6],
                             "chart": {"rendered_verification": {"frames": [449.0, 455.0, 466.0]}}}])
    assert visual_check.run(good, shots_root=shots_root)["status"] == "pass"

    # 非定量镜头不要求
    plain = _plan(tmp_path, [{"id": "V01", "start": 0, "end": 20, "recipe": {"name": "list-reveal"}}])
    assert visual_check.run(plain, shots_root=shots_root)["status"] == "pass"
