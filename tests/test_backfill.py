from __future__ import annotations

from content_studio import backfill as b


def test_split_douyin_title_drops_activity_tags_and_finds_the_headline() -> None:
    s = b.split_douyin_title("某某问题的答案比你想的简单 第二句是描述。 #认知 #青年创作者成长计划 #某某新星计划")
    assert s["title"] == "某某问题的答案比你想的简单" and s["body"] == "第二句是描述。"
    assert s["tags"] == ["认知"]
    assert b.split_douyin_title("how to win #认知")["title"] == "how to win"
    assert b.split_douyin_title("测试哪个coding agent最听话！ 后面是描述")["title"] == "测试哪个coding agent最听话！"


def test_link_prefers_published_video_id_then_a_similar_titled_topic_with_a_douyin_record() -> None:
    videos = [{"video_id": "v1", "title": "我终于想明白了一件事 #话题"}, {"video_id": "v2", "title": "完全不相关的内容"}, {"video_id": "v3", "title": "直接连上的"}]
    topics = [{"id": 1, "title": "内部选题名", "published_video_id": None}, {"id": 2, "title": "没发过抖音", "published_video_id": None},
              {"id": 3, "title": "x", "published_video_id": "v3"}]
    records = {1: {"douyin": {}}, 2: {}}
    links = b.link_topics(videos, topics, records, {1: "我终于想明白了一件事！"})
    assert links == {"v1": 1, "v3": 3}


def test_queue_counts_gaps_on_every_platform_newest_first() -> None:
    videos = [{"video_id": "a", "title": "a", "likes": 10, "published_at": "2026-09-01T00:00:00+00:00"},
              {"video_id": "b", "title": "b", "likes": 500, "published_at": "2026-09-20T00:00:00+00:00"},
              {"video_id": "c", "title": "c", "likes": 900, "published_at": "2026-03-01T00:00:00+00:00"}]
    records = {7: {k: {} for k in ("douyin", *b.PLATFORMS)}}
    rows = b.queue(videos, links={"c": 7}, records=records, marks={"b": {"youtube", "x"}}, median=100)
    assert [r["video_id"] for r in rows] == ["b", "a", "c"]  # 新的在前，和点赞、缺不缺都无关
    b_row = rows[0]
    assert b_row["done"]["youtube"] == "mark" and b_row["done"]["x"] == "mark" and "youtube" not in b_row["missing"]
    assert b_row["missing"] == ["channels", "xiaohongshu", "bilibili", "wechat_mp", "miniprogram", "xiaoyuzhou"] and b_row["multiple"] == 5.0
    assert set(b.KIND) == set(b.PLATFORMS)
    assert rows[-1]["missing"] == []


def test_old_form_records_leave_the_cell_empty_but_keep_the_link() -> None:
    """9/29：小红书从图文改成视频。之前发的图文不算这一格发过（等补发视频），链接留在 old_links。"""
    from content_studio import backfill

    videos = [{"video_id": "v1", "title": "t", "published_at": "2026-09-20", "likes": 10}]
    records = {1: {"xiaohongshu": {"url": "https://xhs/1", "form": "cards"}, "x": {"url": "https://x/1", "form": None}}}
    rows = backfill.queue(videos, links={"v1": 1}, records=records, marks={}, median=10, platforms=("xiaohongshu", "x"),
                          forms={"xiaohongshu": "video", "x": "text"})
    r = rows[0]
    assert r["done"] == {"xiaohongshu": None, "x": "record"}
    assert r["missing"] == ["xiaohongshu"] and r["old_links"] == {"xiaohongshu": "https://xhs/1"}
    # 形式一致就照旧算
    rows = backfill.queue(videos, links={"v1": 1}, records=records, marks={}, median=10, platforms=("xiaohongshu",), forms={"xiaohongshu": "cards"})
    assert rows[0]["done"]["xiaohongshu"] == "record"
