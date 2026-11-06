"""#590：带了产品的内容，发出去时描述最后加一行私信关键词或落地页。"""
from __future__ import annotations

from content_studio import copypack, publish_desk

TIANJI = {"name": "天机", "keyword": "天机", "landing": "https://example.com/products/tianji"}


def test_domestic_platforms_get_the_keyword_others_get_the_landing_page() -> None:
    assert copypack.product_line("douyin", TIANJI) == "天机：私信「天机」"
    assert copypack.product_line("xiaohongshu", TIANJI) == "天机：私信「天机」"
    assert copypack.product_line("youtube", TIANJI) == "天机：https://example.com/products/tianji"
    assert copypack.product_line("youtube", {**TIANJI, "landing": ""}) == "天机：私信「天机」"
    assert copypack.product_line("douyin", {**TIANJI, "keyword": ""}) == ""  # 抖音不放站外链接
    assert copypack.product_line("douyin", None) == ""


def test_the_line_is_added_once_and_never_pushes_past_the_cap() -> None:
    body = copypack.with_product("bilibili", "这一周我把算命网站做了出来。", TIANJI)
    assert body.endswith("\n\n天机：https://example.com/products/tianji")
    assert copypack.with_product("bilibili", body, TIANJI) == body
    full = "长" * 280
    assert copypack.with_product("x", full, TIANJI) == full


def test_the_desk_fill_carries_the_product_line() -> None:
    shared = {"title": "算命网站", "body": "做出来了。", "tags": ["AI"]}
    out = publish_desk.own_entry(None, "douyin", shared, None, TIANJI)
    assert out["body"] == "做出来了。\n\n天机：私信「天机」" and shared["body"] == "做出来了。"
    assert publish_desk.own_entry(None, "douyin", shared)["body"] == "做出来了。"
