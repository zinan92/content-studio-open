"""X 热榜（10/8 作者，#539）：读 xzhishu 的公开接口；X 页和进项共用；能引用、能收进进项。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from content_studio.extras.xline import xhot
from test_x_line import client_factory  # noqa: F401 - fixture

ARTICLE = {"rank": 1, "creator": {"name": "花叔", "handle": "@AlchainHust"}, "category": "AI", "content": "第一批用上 huashu-art-motion 的人",
           "articleTitle": "第一批用上huashu-art-motion的人，已经开始拿到结果了！", "articlePreview": "大家好，我是花叔。",
           "url": "https://x.com/AlchainHust/status/2107776021038764484", "publishedAt": 1791367938000,
           "reads": 47701, "likes": 239, "comments": 16, "reposts": 29, "bookmarks": 419}
TOPIC = {"id": "t1", "rank": 2, "title": "Claude订阅送API额度", "summary": "订阅用户送 API 额度", "heatDisplay": 91, "tweetCount": 36,
         "readsCount": 120000, "tags": ["Claude"], "sourceTweets": [{"id": "s1", "content": "Claude 订阅现在送 API 额度了\n细节如下",
                                                                    "url": "https://x.com/a/status/1", "creator": {"name": "甲", "handle": "@a"},
                                                                    "readsCount": 2151, "likesCount": 7, "publishedAt": 1791436904000}]}


def fake(calls: list[str]):
    def fetch(url: str):
        calls.append(url)
        if "/topics/hot" in url:
            return {"updatedAt": 1791445167547, "topics": [TOPIC]}
        if "dimension=nope" in url:
            return {"code": "invalid_request", "message": "请求参数格式不正确"}
        return {"updatedAt": 1791443747509, "items": [ARTICLE], "pagination": {}}
    return fetch


def test_board_reads_the_three_lists_with_filters_and_caches_ten_minutes() -> None:
    calls: list[str] = []
    now = [0.0]
    board = xhot.Board(fetch=fake(calls), clock=lambda: now[0])
    a = board.get("articles", "24h", "bookmarks", "ai")
    assert "contentType=article" in calls[0] and "dimension=bookmarks" in calls[0] and "category=ai" in calls[0]
    it = a["items"][0]
    assert it["title"].startswith("第一批用上") and it["author"] == "花叔" and it["bookmarks"] == 419 and it["url"].endswith("2107776021038764484")
    board.get("articles", "24h", "bookmarks", "ai")
    assert len(calls) == 1  # 10 分钟内同一组只读一次
    now[0] = 601
    board.get("articles", "24h", "bookmarks", "ai")
    assert len(calls) == 2
    board.get("tweets", "48h", "reads", "all")
    assert "contentType" not in calls[-1] and "category" not in calls[-1] and "period=48h" in calls[-1]  # 全部 = 不筛
    t = board.get("topics", "24h", "heat")["items"][0]
    assert t["title"] == "Claude订阅送API额度" and t["tweets"][0]["title"] == "Claude 订阅现在送 API 额度了" and t["heat"] == 91
    with pytest.raises(xhot.HotError, match="不能这样排"):
        board.get("topics", "24h", "bookmarks")
    with pytest.raises(xhot.HotError, match="没有这个分类"):
        board.get("tweets", "24h", "reads", "nsfw")


def test_save_writes_one_note_into_saved_and_never_twice(tmp_path: Path) -> None:
    item = xhot.post_item(ARTICLE, "articles")
    path, new = xhot.save(tmp_path / "002_个人收藏", item)
    assert new and path.name.endswith(".md") and "_X_" in path.name
    text = path.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["url"] == ARTICLE["url"] and meta["source_name"] == "X 热榜"
    assert "# 第一批用上huashu-art-motion的人，已经开始拿到结果了！" in text and "阅读 47701" in text
    again, new2 = xhot.save(tmp_path / "002_个人收藏", {**item, "title": "标题改了也是同一条"})
    assert again == path and not new2
    with pytest.raises(xhot.HotError, match="没有链接"):
        xhot.save(tmp_path, {"title": "x"})
    assert xhot.tweet_id("https://x.com/a/status/123?s=20") == "123" and xhot.tweet_id("https://x.com/a") is None


def test_external_links_and_obsidian_metadata_are_safe(tmp_path: Path) -> None:
    from content_studio import vault

    for url in ("javascript:alert(1)", "https://evil.test/status/123", "https://x.com@evil.test/a/status/123", "https://x.com/a/status/123oops"):
        assert xhot.post_item({**ARTICLE, "url": url}, "articles")["url"] == ""
        assert xhot.tweet_id(url) is None
        with pytest.raises(xhot.HotError):
            xhot.save(tmp_path, {"url": url})
    item = {**xhot.post_item(ARTICLE, "articles"), "author": 'AI: "观察"', "title": "长" * 100}
    path, _ = xhot.save(tmp_path, item)
    assert len(path.name.encode("utf-8")) <= 255
    text = path.read_text()
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["author"] == 'AI: "观察" @AlchainHust'
    parsed, body = vault.parse_frontmatter(text)
    assert parsed["author"] == meta["author"]
    assert parsed["url"] == ARTICLE["url"] and parsed["collected_at"]
    assert item["title"] in body
    same, new = xhot.save(tmp_path, {**item, "url": ARTICLE["url"].replace("x.com", "twitter.com") + "?s=20"})
    assert same == path and not new


def test_page_shows_the_board_saves_to_inbox_and_posts_quote_drafts(client_factory, tmp_path: Path,  # noqa: F811
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    (vault / "002_个人收藏").mkdir(parents=True)
    (vault / "003_原始输出").mkdir()
    (vault / "003_原始输出" / "a.md").write_text("慢就是快。简单的事情重复做。", encoding="utf-8")  # 风格从他自己的话里总结
    sent: list[tuple] = []
    prompts: list[str] = []

    def write(prompt: str) -> str:
        prompts.append(prompt)
        if "总结他的说话" in prompt:
            return "# X 写作风格\n" + "短句，先下判断。" * 20
        return "<<<POST>>>\n订阅送额度，说明模型公司开始抢开发者的钱包了。\n<<<END>>>"

    client: TestClient = client_factory(write_fn=write, x_fetch_fn=fake([]),
                                        x_post_fn=lambda t, **kw: sent.append((t, kw)) or {"url": "https://x.com/i/web/status/9"})
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    r = client.get("/api/xhot", params={"kind": "articles", "dimension": "reads"}).json()
    assert r["items"][0]["reads"] == 47701 and [k["key"] for k in r["kinds"]] == ["topics", "articles", "tweets"]
    assert client.get("/api/xhot", params={"kind": "tweets", "category": "nsfw"}).status_code == 400

    s = client.post("/api/xhot/save", json=r["items"][0]).json()
    assert s["new"] and s["path"].startswith("002_个人收藏/")
    assert client.post("/api/xhot/save", json=r["items"][0]).json()["new"] is False

    url = "https://x.com/a/status/1"
    d = client.post("/api/xline/suggest", json={"kind": "xhot", "quote": True, "url": url, "title": "Claude 订阅送额度",
                                                "author": "甲 @a", "text": "Claude 订阅现在送 API 额度了"}).json()
    post = d["posts"][0]
    assert url not in post and "引用帖" in prompts[-1]  # 引用帖：原帖跟着卡片出来，稿子里不贴链接
    out = client.post("/api/xline/post", json={"text": post, "source_id": d["source_id"], "quote_url": url}).json()
    assert sent == [(post, {"quote_tweet_id": "1"})] and out["post"]["url"].endswith("/9")
    assert client.post("/api/xline/post", json={"text": "x", "quote_url": "https://x.com/a"}).status_code == 400


def test_rising_keeps_what_held_attention_for_ten_hours_and_is_still_read() -> None:
    """10/9 作者：过去 10 小时持续获得注意力的。刚冒头的、早就过气的不算。"""
    steady = [0] + [1000] * 12                      # 12 小时一直有人看
    fading = [0, 50000, 30000, 9000, 2000, 500, 100, 50, 20, 10, 5, 5]  # 早高峰，后面没了
    fresh = [0, 80000, 90000]                         # 才 2 小时
    assert xhot.rising_score(steady) == (10000, True)
    assert xhot.rising_score(fading)[1] is False and xhot.rising_score(fresh)[1] is False
    mk = lambda u, t, kind="tweets": {"url": f"https://x.com/a/status/{u}", "kind": kind, "trend": t, "title": u, "text": u}  # noqa: E731
    out = xhot.rising([{"items": [mk("1", steady), mk("2", fading)]},
                       {"items": [mk("1", steady), mk("3", [0] + [3000] * 8, "articles"), mk("4", fresh)]}])
    assert [x["url"][-1] for x in out] == ["3", "1"] and out[0]["gained"] == 24000 and out[0]["hours"] == 8  # 去重、按近 10 小时排
    assert [x["rank"] for x in out] == [1, 2]


def test_rising_board_reads_velocity_pages_for_his_categories() -> None:
    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        return {"updatedAt": 1791445167547, "items": [{**ARTICLE, "url": f"https://x.com/a/status/{len(calls)}", "trafficTrend": [0] + [500] * 10}]}

    r = xhot.Board(fetch=fetch).rising()
    assert len(calls) == len(xhot.RISING_SOURCES) and all("dimension=velocity" in u for u in calls)
    assert any("category=ai" in u for u in calls) and any("contentType=article" in u for u in calls)
    assert r["kind"] == "rising" and len(r["items"]) == len(calls) and r["items"][0]["gained"] == 5000
