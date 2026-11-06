from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from content_studio import review

NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def _inputs():
    own = [
        {"video_id": "a", "title": "AI越强", "published_at": (NOW - timedelta(days=6)).isoformat(), "likes": 1729, "collects": 900, "is_image_post": 0},
        {"video_id": "b", "title": "盯盘", "published_at": (NOW - timedelta(days=5)).isoformat(), "likes": 338, "collects": 50, "is_image_post": 0},
        {"video_id": "old", "title": "旧", "published_at": (NOW - timedelta(days=30)).isoformat(), "likes": 5, "is_image_post": 0},
    ]
    reports = {"a": {"thesis": {"text": "主线"}, "why_boom": [{"text": "开头直给"}], "why_scatter": [{"text": "中段推荐别人"}], "drift": {"share": 0.2}}}
    breakouts = [{"video_id": "x", "title": "对标爆款", "account_nickname": "千雪", "multiple": 12.0, "published_at": (NOW - timedelta(days=2)).isoformat()}]
    topics = [{"title": "已发选题", "published_at": (NOW - timedelta(days=1)).isoformat()}, {"title": "没发", "published_at": None}]
    return review.gather_inputs(own_videos=own, median_likes=266, creator={"a": {"fan_increment": 430, "avg_view_second": 25.3, "bounce_rate_2s": 0.38}},
                                reports=reports, topics=topics, breakouts=breakouts, now=NOW)


def _good():
    return {"summary": "s", "wins": [{"text": "6.5 倍", "video_ids": ["a"]}], "problems": [{"text": "盯盘开头慢", "video_ids": ["b"]}],
            "next_week": ["开头 15 秒内说出主线，看 2 秒跳出"]}


def test_inputs_keep_last_week_with_computed_numbers() -> None:
    inputs = _inputs()
    assert [v["video_id"] for v in inputs["videos"]] == ["a", "b"]
    a = inputs["videos"][0]
    assert a["multiple"] == 6.5 and a["fans"] == 430 and a["avg_watch_seconds"] == 25 and a["report"]["why_scatter"] == ["中段推荐别人"]
    assert inputs["topics_done"] == ["已发选题"] and inputs["breakouts"][0]["account"] == "千雪"
    prompt = review.build_prompt(inputs)
    assert "id a｜AI越强" in prompt and "中段推荐别人" in prompt and "千雪" in prompt


def test_generate_attaches_titles_and_rejects_unknown_ids() -> None:
    inputs = _inputs()
    result = review.generate_review(inputs, review_fn=lambda p: _good(), now=NOW)
    assert result["wins"][0]["videos"] == [{"video_id": "a", "title": "AI越强"}] and result["week"] == "2026-W38"
    bad = _good()
    bad["wins"][0]["video_ids"] = ["invented"]
    assert any("video_ids" in p for p in review.validate(bad, inputs))
    two = {**_good(), "next_week": ["一", "二"]}
    assert "next_week 需要恰好 1 条" in review.validate(two, inputs)
    assert "patterns" not in review.generate_review(inputs, review_fn=lambda p: {**_good(), "patterns": ["x"]}, now=NOW)
    with pytest.raises(review.ReviewError, match="连续 3 次"):
        review.generate_review(inputs, review_fn=lambda p: bad)


def test_empty_week_is_explained() -> None:
    inputs = review.gather_inputs(own_videos=[], median_likes=None, creator={}, reports={}, topics=[], breakouts=[], now=NOW)
    with pytest.raises(review.ReviewError, match="没有发视频"):
        review.generate_review(inputs, review_fn=lambda p: _good())


def test_review_sees_all_nine_numbers_and_his_own_baseline() -> None:
    """9/29 作者：复盘要看播放、平均观看、封面点击率、2 秒跳出、5 秒完播……并且和自己平时比。"""
    own = [
        {"video_id": "a", "title": "本周", "published_at": (NOW - timedelta(days=2)).isoformat(), "likes": 200, "collects": 100, "is_image_post": 0},
        {"video_id": "o1", "title": "旧1", "published_at": (NOW - timedelta(days=20)).isoformat(), "likes": 100, "collects": 20, "is_image_post": 0},
        {"video_id": "o2", "title": "旧2", "published_at": (NOW - timedelta(days=40)).isoformat(), "likes": 300, "collects": 30, "is_image_post": 0},
        {"video_id": "gone", "title": "太老", "published_at": (NOW - timedelta(days=200)).isoformat(), "likes": 9999, "is_image_post": 0},
    ]
    m = lambda v, c5, ctr, b2: {"view_count": v, "completion_rate_5s": c5, "cover_click_rate": ctr, "bounce_rate_2s": b2, "avg_view_second": 20.0, "fan_increment": 10}  # noqa: E731
    creator = {"a": m(11239, 0.279, 0.444, 0.434), "o1": m(5000, 0.30, 0.40, 0.46), "o2": m(9000, 0.25, 0.50, 0.50), "gone": m(1, 0.9, 0.9, 0.1)}
    inputs = review.gather_inputs(own_videos=own, median_likes=200, creator=creator, reports={}, topics=[], breakouts=[], now=NOW)
    v = inputs["videos"][0]
    assert (v["plays"], v["completion_5s"], v["cover_ctr"], v["bounce_2s"]) == (11239, 0.279, 0.444, 0.434)
    base = inputs["baseline"]
    assert base["videos"] == 3  # 200 天前那条不算
    assert base["plays"] == 9000 and base["bounce_2s"] == 0.46 and base["likes"] == 200
    prompt = review.build_prompt(inputs)
    assert "播放 11239" in prompt and "封面点击率 44.4%" in prompt and "5 秒完播 27.9%" in prompt
    assert "近 90 天 3 条视频的中位数" in prompt and "2 秒跳出 46.0%" in prompt


def test_private_video_zero_plays_is_missing_not_zero() -> None:
    own = [{"video_id": "p", "title": "藏了", "published_at": (NOW - timedelta(days=1)).isoformat(), "likes": 69, "is_image_post": 0}]
    inputs = review.gather_inputs(own_videos=own, median_likes=100, creator={"p": {"view_count": 0}}, reports={}, topics=[], breakouts=[], now=NOW)
    assert inputs["videos"][0]["plays"] is None and inputs["baseline"]["plays"] is None
    assert "播放 —" in review.build_prompt(inputs)
