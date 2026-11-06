"""X 运营 Agent（10/9 作者）：常驻 X 页，不是 作者、也不是 Anna；看得到队列、数、持续在涨，只给建议。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import x_daily, xops
from test_x_line import client_factory  # noqa: F401 - fixture


def fx(views: dict[str, int]):
    def fetch(url: str):
        if "api.fxtwitter.com/status/" in url:
            tid = url.rsplit("/", 1)[1]
            return {"tweet": {"views": views.get(tid, 0), "likes": 1, "bookmarks": views.get(tid, 0) // 100, "replies": 0, "retweets": 0}}
        return {"items": [], "updatedAt": 1791445167547}
    return fetch


DAYS = {"2026-10-08": {"posts": [{"state": "sent", "long": True, "format": "post", "text": "简单规则\n\n…", "url": "https://x.com/i/web/status/1"},
                                 {"state": "sent", "long": True, "text": "# 世界未来\n\n…", "url": "https://x.com/i/web/status/2"},
                                 {"state": "sent", "text": "短帖", "url": "https://x.com/i/web/status/3"},
                                 {"state": "pending", "long": True, "text": "没发"}]},
        "2026-09-01": {"posts": [{"state": "sent", "text": "太早了", "url": "https://x.com/i/web/status/9"}]}}


def test_perf_compares_long_posts_articles_and_short_posts_over_seven_days() -> None:
    calls = []
    fetch = fx({"1": 2000, "2": 600, "3": 50})
    perf = xops.Perf(lambda u: calls.append(u) or fetch(u))
    s = perf.summary(DAYS, date(2026, 10, 9))
    assert s["by_kind"]["长帖"]["avg_views"] == 2000 and s["by_kind"]["长文"]["avg_views"] == 600 and s["by_kind"]["短帖"]["n"] == 1
    assert s["best"][0]["kind"] == "长帖" and s["count"] == 3  # 7 天以前的、没发的不算
    perf.summary(DAYS, date(2026, 10, 9))
    assert len(calls) == 3  # 半小时内不重读


def test_reply_buttons_only_for_quote_links_and_count_changes() -> None:
    r = xops.parse_reply("先引用这条。\n[引用] https://x.com/a/status/123\n[改数量] long=12 post_share=0.5 hot=50 bogus=1\n[引用] https://evil.com/a/status/1\n就这样")
    assert r["text"] == "先引用这条。\n[引用] https://evil.com/a/status/1\n就这样"  # 不是 X 的链接不变按钮
    assert r["actions"] == [{"kind": "quote", "url": "https://x.com/a/status/123"}, {"kind": "counts", "change": {"long": 12, "post_share": 0.5, "hot": 50}}]


def test_context_carries_queue_counts_numbers_rising_and_beliefs() -> None:
    perf = xops.Perf(fx({"1": 2000, "2": 600, "3": 50})).summary(DAYS, date(2026, 10, 9))
    text = xops.context(queue={"today": {"day": "2026-10-09", "posts": [{"state": "pending", "long": True, "format": "post"}, {"state": "sent", "text": "x"}]},
                               "tomorrow": {"day": "2026-10-10", "posts": []}},
                        counts={"long": 10, "post_share": 0.5, "hot": 30, "own_short": 0}, perf=perf,
                        rising=[{"title": "Claude 封号", "author": "甲", "gained": 23456, "url": "https://x.com/a/status/5", "category": "AI"}],
                        beliefs="慢就是快")
    assert "长帖 排着等勾 1" in text and "短帖 发了 1" in text and "明天 2026-10-10：还没排" in text
    assert "长帖：1 条，平均浏览 2000" in text and "Claude 封号" in text and "+23456" in text and "慢就是快" in text


def test_page_chat_runs_in_its_own_thread_not_annas(client_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    seen = []

    def turn(system: str, user: str, sid):
        seen.append((system, user))
        return {"text": "先引用这条，再把长帖加到 6 条。\n[引用] https://x.com/a/status/5\n[改数量] long=12 post_share=0.5", "session_id": "s1"}

    client: TestClient = client_factory(anna_fn=turn, x_fetch_fn=fx({}))
    assert client.get("/api/xops").json()["messages"] == []
    assert client.post("/api/xops", json={"message": "今天先做什么？"}).json()["started"] is True
    for _ in range(100):
        d = client.get("/api/xops").json()
        if not d["busy"]:
            break
        time.sleep(0.05)
    assert d["error"] is None and [m["role"] for m in d["messages"]] == ["park", "xops"]
    assert d["messages"][1]["actions"][0] == {"kind": "quote", "url": "https://x.com/a/status/5"}
    system, user = seen[0]
    assert "X 运营" in system and "不是主人本人，也不是流量 CEO Anna" in system and "不自动发热点" in system
    assert "## 每天发多少" in user and "主人：今天先做什么？" in user
    assert client.get("/api/anna", params={"scope": "board"}).json()["messages"] == []  # 和 Anna 的对话不混
    assert client.post("/api/xops", json={"message": "  "}).status_code == 400
    assert client.delete("/api/xops").json() == {"ok": True} and client.get("/api/xops").json()["messages"] == []


def test_he_is_called_michael_unless_the_brand_says_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    """10/9 晚 作者：「X 那个 agent 名字叫做 Michael 吧」。名字跟着品牌走，每一轮都告诉他。"""
    from content_studio import conf

    monkeypatch.setattr(conf, "brand", lambda data=None: {**conf.BRAND_DEFAULT})
    s = xops.soul()
    assert xops.name() == "Michael" and s["name"] == "Michael" and s["text"].startswith("你叫 Michael，是主人的X 运营。")
    monkeypatch.setattr(conf, "brand", lambda data=None: {**conf.BRAND_DEFAULT, "xops": "Leo"})
    assert xops.name() == "Leo" and xops.soul()["text"].startswith("你叫 Leo")


def test_the_x_queue_is_signed_by_michael_not_wendy() -> None:
    """10/9 晚 作者：X 页归 Michael。排队列的是后台那一圈，页面和提示上署他的名字，不再写 Wendy。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src/content_studio"
    js = (root / "static/xline.js").read_text(encoding="utf-8")
    routes = (root / "extras/xline/routes.py").read_text(encoding="utf-8")
    for old in ("Wendy 在排", "Wendy 还没排", "Wendy 从这里挑"):
        assert old not in js, old
    assert "xlWho()" in js and "Wendy 排好了" not in routes and "Wendy 正在排" not in routes


def test_michael_is_off_the_rail_while_paused() -> None:
    """10/12 作者：「Michael 暂时没有什么用，先拿掉。」左栏不再有他（Obsidian 里的角色文件标了 paused）。"""
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "src/content_studio/static/index.html").read_text(encoding="utf-8")
    assert 'id="railMichael"' not in html and 'id="railAnna"' in html and 'id="railWendy"' in html
