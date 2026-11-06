from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from content_studio import xhs_cards

ARTICLE = "# 产品越来越便宜，信任越来越贵，自媒体的下半场才刚刚开始\n\n" + "\n\n".join(
    [f"第{i}段。卖课是我讲一次，这个课就过去了。我想再赚新的钱，我得再重新做一遍。**信任是最贵的产品。**" for i in range(1, 30)]
    + ["先说区别在哪。", "> 用便宜的东西，换贵的东西。", "- 第一条\n- 第二条"])


def test_title_breaks_at_commas_without_splitting_words() -> None:
    assert xhs_cards.title_lines("产品越来越便宜，信任越来越贵，自媒体的下半场才刚刚开始") == ["产品越来越便宜，", "信任越来越贵，", "自媒体的下半场", "才刚刚开始"]


def test_parse_keeps_text_and_marks_short_lines() -> None:
    title, blocks = xhs_cards.parse(ARTICLE)
    assert title.startswith("产品越来越便宜")
    kinds = {b["text"]: b["kind"] for b in blocks}
    assert kinds["先说区别在哪。"] == "lead" and kinds["用便宜的东西，换贵的东西。"] == "q" and kinds["- 第一条\n- 第二条"] == "li"
    with pytest.raises(xhs_cards.XhsError, match="# 标题"):
        xhs_cards.parse("没有标题")


@pytest.mark.skipif(importlib.util.find_spec("playwright") is None, reason="playwright missing")
def test_cards_keep_every_word_and_go_stale_when_the_article_changes(tmp_path: Path) -> None:
    article = tmp_path / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    meta = xhs_cards.make_cards(article)  # 抽回来的字和原文不一致会直接报错
    images = sorted((tmp_path / "xhs").glob("*.png"))
    assert meta["images"] == len(images) >= 3 and images[0].name == "01.png" and not meta["over_limit"]
    st = xhs_cards.state(article)
    assert st["images"] == [p.name for p in images] and st["stale"] is False
    article.write_text(ARTICLE + "\n\n再补一段。", encoding="utf-8")
    assert xhs_cards.state(article)["stale"] is True
