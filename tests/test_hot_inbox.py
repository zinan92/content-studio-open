from __future__ import annotations

from content_studio import hot


def _outlier(video_id: str, multiple: float, likes: int, median: int, who: str) -> dict:
    return {"video_id": video_id, "multiple": multiple, "likes": likes, "account_median": median, "account_nickname": who}


def test_video_id_comes_out_of_the_note_frontmatter() -> None:
    """对标文字稿的 frontmatter 里写的是 `source: https://www.douyin.com/video/<id>`。"""
    assert hot.video_id_in("https://www.douyin.com/video/7412345678901234567") == "7412345678901234567"
    assert hot.video_id_in("https://www.douyin.com/video/7412345678901234567?from=main") == "7412345678901234567"
    for miss in (None, "", "https://www.douyin.com/user/MS4wLjABAAAA", "https://mp.weixin.qq.com/s/abc"):
        assert hot.video_id_in(miss) is None


def test_only_the_breakouts_get_marked() -> None:
    items = [
        {"path": "a.md", "url": "https://www.douyin.com/video/111"},
        {"path": "b.md", "url": "https://www.douyin.com/video/222"},
        {"path": "c.md", "url": None},
    ]
    marked = hot.mark_breakouts(items, [_outlier("111", 5.3, 6360, 1200, "一勾工作号")])
    assert marked[0]["breakout"] == {"multiple": 5.3, "likes": 6360, "median": 1200, "account": "一勾工作号"}
    # 倍数只有和「他平时多少」一起看才有意义，所以两个数都要带出去。
    assert marked[0]["breakout"]["median"] == 1200
    assert "breakout" not in marked[1] and "breakout" not in marked[2]
    assert [m["path"] for m in marked] == ["a.md", "b.md", "c.md"]


def test_marking_does_not_drop_or_reorder_anything() -> None:
    items = [{"path": f"{i}.md", "url": f"https://www.douyin.com/video/{i}", "triage": None} for i in range(5)]
    marked = hot.mark_breakouts(items, [_outlier("3", 9.1, 900, 99, "谁")])
    assert len(marked) == 5 and [m["path"] for m in marked] == [f"{i}.md" for i in range(5)]
    assert all("triage" in m for m in marked)
    assert hot.mark_breakouts([], [_outlier("1", 2.0, 2, 1, "x")]) == []
