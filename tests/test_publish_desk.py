"""发布台：treatment 推导、行状态、候选排序，以及接口整体形状。"""
from __future__ import annotations

from content_studio import copypack, publish_desk
from test_web import client  # noqa: F401 - fixture


SPECS = {
    "x": {"needs_keys": ("x", ("api_key",))},
    "bilibili": {"credential": "/tmp/x", "probe": ["true"]},
    "channels": {"credential": "/tmp/y", "blocked": "限制了"},
    "wechat_mp": {"needs_keys": ("wechat", ("appid", "secret")), "needs_article": True},
}


def test_treatment_by_channel_kind():
    assert publish_desk.treatment("douyin", None) == "manual"
    # 9/29 起抖音半自动：机器填好，最后点发布的是 作者
    assert publish_desk.treatment("x", SPECS["x"]) == "auto"
    assert publish_desk.treatment("bilibili", SPECS["bilibili"]) == "scan"
    assert publish_desk.treatment("channels", SPECS["channels"]) == "scan"
    # 9/24 起公众号一键发（排版 + 封面进草稿箱），不再是「交给流水线」
    assert publish_desk.treatment("wechat_mp", SPECS["wechat_mp"]) == "auto"


def test_shared_entry_prefers_first_written_platform():
    assert publish_desk.shared_entry(None) == {"title": "", "body": "", "tags": []}
    copy = {"platforms": {"douyin": {"title": "", "body": ""}, "youtube": {"title": "T", "body": "B", "tags": ["a"]}}}
    assert publish_desk.shared_entry(copy) == {"title": "T", "body": "B", "tags": ["a"]}


def test_fill_trims_to_platform_caps():
    entry = {"title": "一二三四五六七八九十一二三四五六七八九十多出来", "body": "x" * 5, "tags": ["a", "b", "c", "d", "e", "f"]}
    fill = publish_desk.fill_for(copypack.PLATFORMS["channels"], entry)
    assert len(fill["title"]) == 16 and fill["title_over"] is True and fill["title_trimmed"] is True
    xhs = publish_desk.fill_for(copypack.PLATFORMS["xiaohongshu"], entry)
    assert xhs["title"] == entry["title"] and xhs["title_over"] is True and xhs["title_trimmed"] is False  # 小红书不截，提醒
    assert xhs["tags"] == ["a", "b", "c", "d", "e", "f"]
    # 9/24 实测：小红书两个英文字母算一个字
    title = "我终于理解了dontbesilent为什么开源dbskill！"
    assert copypack.title_units(title, copypack.PLATFORMS["xiaohongshu"]) == 21.5
    assert copypack.title_units(title[:20], copypack.PLATFORMS["xiaohongshu"]) == 14
    x = publish_desk.fill_for(copypack.PLATFORMS["x"], entry)
    assert x["title"] == "" and x["tags"] == ["a", "b", "c"] and x["title_over"] is False


def test_each_platform_fills_from_its_own_copy():
    """9/29：描述（抖音、视频号、小红书）和简介（B 站、YouTube）分开存，发布台每个平台读自己那份。"""
    shared = {"title": "标题", "body": "长描述", "tags": ["t"]}
    copies = {
        "douyin": {"title": "标题", "body": "长描述", "tags": ["t"]},
        "bilibili": {"title": "标题", "body": "短简介", "tags": ["t"]},
        "youtube": {"title": "", "body": "", "tags": []},
    }
    rows = {r["key"]: r for r in publish_desk.rows([_platform("douyin"), _platform("bilibili"), _platform("youtube"), _platform("wechat_mp")],
                                                      specs=copypack.PLATFORMS, publishers={}, readiness={}, records={}, jobs=[],
                                                      entry=shared, copies=copies)}
    assert rows["douyin"]["fill"]["body"] == "长描述"
    assert rows["bilibili"]["fill"]["body"] == "短简介"
    assert rows["youtube"]["fill"]["body"] == "长描述"  # 空的那份不算写过，用共用的
    assert rows["wechat_mp"]["fill"]["title"] == "标题"


def _platform(key, state="manual", **extra):
    return {"key": key, "label": key, "mark": key[0], "hue": "#000", "handle": "", "on": True, "state": state, "note": "", "admin": None, "login_hint": "", **extra}


def test_rows_state_shipped_and_can_auto():
    platform_rows = [_platform("douyin"), _platform("x", "linked"), _platform("bilibili", "stale"), _platform("wechat_mp", "ready")]
    readiness = {"x": {"modes": {"post": "发"}, "no_video": True}, "bilibili": {"modes": {"upload": "投"}}}
    jobs = [
        {"id": 3, "platform": "x", "state": "cancelled", "payload": {"mode_label": "发"}},
        {"id": 2, "platform": "x", "state": "done", "payload": {"mode_label": "发"}, "message": None, "created_at": "t"},
    ]
    entry = {"title": "标题", "body": "正文", "tags": ["t"]}
    rows = {r["key"]: r for r in publish_desk.rows(platform_rows, specs=copypack.PLATFORMS, publishers={"x": SPECS["x"], "bilibili": SPECS["bilibili"]},
                                                      readiness=readiness, records={"x": {"url": "https://x.com/1", "published_at": "2026-09-21"}}, jobs=jobs,
                                                      entry=entry, douyin_linked=True, handoff_done=True)}
    assert rows["douyin"]["shipped"] is True and rows["douyin"]["record"] is None and rows["douyin"]["treatment"] == "manual"
    assert rows["x"]["shipped"] is True and rows["x"]["record"]["url"] == "https://x.com/1"
    assert rows["x"]["job"]["id"] == 2  # cancelled one skipped
    assert rows["x"]["can_auto"] is True and rows["x"]["no_video"] is True and rows["x"]["modes"] == {"post": "发"}
    assert rows["bilibili"]["can_auto"] is False and rows["bilibili"]["treatment"] == "scan"
    assert rows["wechat_mp"]["treatment"] == "manual" and rows["wechat_mp"]["handoff_done"] is None  # 这里没给它通道
    assert rows["douyin"]["handoff_done"] is None
    assert rows["douyin"]["fill"]["title"] == "标题"


def test_order_candidates_ready_first_then_shipped():
    cards = [
        {"id": 1, "stage": "outline", "focus": True},
        {"id": 2, "stage": "ready", "focus": False},
        {"id": 3, "stage": "edit", "focus": False},
        {"id": 4, "stage": "outline", "focus": False},
    ]
    shipped = [{"id": 5, "updated_at": "2026-09-01"}, {"id": 6, "updated_at": "2026-09-20"}]
    assert [c["id"] for c in publish_desk.order_candidates(cards, shipped)] == [2, 3, 1, 4, 6, 5]


def test_only_a_finished_video_shows_up_on_the_publish_page(client):
    """作者：「通常我只会有一条视频在这个环节中，而不是六个」。

    还在写提纲、还在录的不该出现在发布页——列一排选不了的东西，等于让人每次
    重新判断哪条才是真的能发。发不了的时候，页面要说清最近的那条卡在哪。
    """
    topic = client.post("/api/topics", json={"title": "还在录的"}).json()
    d = client.get("/api/publish/desk").json()
    assert d["candidates"] == [] and d["topic"] is None
    assert d["waiting"]["id"] == topic["id"] and d["waiting"]["stage"] == "outline"
    assert [c["id"] for c in d["others"]] == [topic["id"]]
    # 真有成片但工作台不知道时，仍然能直接指名打开——不能把人锁在外面。
    assert client.get(f"/api/publish/desk?topic_id={topic['id']}").json()["topic"]["id"] == topic["id"]


def test_desk_endpoint_shape(client):
    topic = client.post("/api/topics", json={"title": "发布台测试"}).json()
    client.put(f"/api/topics/{topic['id']}/copy", json={"platforms": {"douyin": {"title": "标题", "body": "简介", "tags": ["AI"]}}})
    client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "bilibili", "published": True, "url": "https://b23.tv/1"})
    d = client.get(f"/api/publish/desk?topic_id={topic['id']}").json()
    assert d["topic"]["id"] == topic["id"]
    assert d["has_copy"] is True and d["entry"]["title"] == "标题"
    rows = {r["key"]: r for r in d["platforms"]}
    assert set(rows) == {"douyin", "channels", "xiaohongshu", "wechat_mp", "miniprogram", "x", "bilibili", "youtube", "xiaoyuzhou"}
    assert rows["bilibili"]["shipped"] is True and rows["bilibili"]["record"]["url"] == "https://b23.tv/1"
    assert rows["douyin"]["shipped"] is False and rows["douyin"]["fill"]["title"] == "标题"
    assert rows["wechat_mp"]["treatment"] == "auto" and rows["wechat_mp"]["needs_article"] is True
    # 指定不在候选里的 id 也能打开
    other = client.post("/api/topics", json={"title": "第二条"}).json()
    client.patch(f"/api/topics/{other['id']}", json={"archived": True})
    assert client.get(f"/api/publish/desk?topic_id={other['id']}").json()["topic"]["id"] == other["id"]


def test_desk_endpoint_empty(client):
    d = client.get("/api/publish/desk").json()
    assert d["topic"] is None and d["candidates"] == [] and len(d["platforms"]) == 9
    assert d["waiting"] is None and d["others"] == []


def test_platforms_come_in_publishing_order_and_next_skips_done_and_skipped() -> None:
    """作者 10/4：X 先发 → 抖音 · 小红书 · 视频号 → B 站 · YouTube · 公众号，一次只亮下一步。"""
    from content_studio import publish_desk as pd

    rows = pd.in_sequence([{"key": k, "on": True} for k in ("youtube", "channels", "douyin", "x", "bilibili")])
    assert [r["key"] for r in rows] == ["x", "douyin", "channels", "bilibili", "youtube"]
    rows[0]["shipped"] = True
    assert pd.next_step(rows) == "douyin"
    rows[1]["skipped"] = True
    rows[2]["on"] = False
    assert pd.next_step(rows) == "bilibili"
    for r in rows:
        r["shipped"] = True
    assert pd.next_step(rows) is None


def test_a_video_out_on_douyin_stays_in_pack_and_publish_until_the_rest_are_sent(client):
    """10/3 作者：「昨天这条抖音发了，其他地方都没发，但打包中的页面就没了。」

    抖音发出（挂上作品）只是第一个平台。还有开着的平台没发、也没点「发布完毕」，
    打包和发布默认就还是这条；每个开着的平台都发了或跳过了，或者点了发布完毕，才收起来。
    """
    store = client.app.state.store
    client.put("/api/settings", json={"platform_accounts": {k: {"on": True, "handle": ""} for k in ("channels", "xiaohongshu", "x")}})
    topic = client.post("/api/topics", json={"title": "抖音刚发"}).json()
    store.update_topic(topic["id"], published_video_id="7692084992523930880")
    client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": "douyin", "published": True, "url": "https://www.douyin.com/video/1"})
    d = client.get("/api/publish/desk").json()
    assert d["topic"] is not None and d["topic"]["id"] == topic["id"]

    on = [p["key"] for p in d["platforms"] if p["on"] and p["key"] != "douyin"]
    assert len(on) >= 2
    for key in on[:-1]:
        client.put(f"/api/topics/{topic['id']}/platforms", json={"platform": key, "published": True, "url": f"https://example.com/{key}"})
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    store.set_publish_skip(topic["id"], on[-1], skip=True)
    assert client.get("/api/publish/desk").json()["topic"] is None

    store.set_publish_skip(topic["id"], on[-1], skip=False)
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    client.post(f"/api/topics/{topic['id']}/close")
    assert client.get("/api/publish/desk").json()["topic"] is None


def test_cells_sent_from_the_backfill_desk_count_as_sent(client):
    """10/3：发其他平台改在补发工作台里发。视频号、小红书在那边点「发了」记在抖音作品上，
    整条「不补发」也在那边——打包、发布页得认这两样，不然这条永远收不起来。"""
    store = client.app.state.store
    client.put("/api/settings", json={"platform_accounts": {k: {"on": True, "handle": ""} for k in ("channels", "xiaohongshu")}})
    topic = client.post("/api/topics", json={"title": "抖音刚发"}).json()
    store.update_topic(topic["id"], published_video_id="v1")
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    store.set_backfill_mark("v1", "channels", True)
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    store.set_backfill_mark("v1", "xiaohongshu", True)
    assert client.get("/api/publish/desk").json()["topic"] is None

    store.set_backfill_mark("v1", "xiaohongshu", False)
    assert client.get("/api/publish/desk").json()["topic"]["id"] == topic["id"]
    store.update_settings({"tracker_cancel": ["v1"]})
    assert client.get("/api/publish/desk").json()["topic"] is None


def test_own_entry_uses_this_platforms_traffic_tags_at_send_time():
    """10/8 作者 在设置里填了小红书、X 的常用话题：已经打包好的那条，发的时候也要带上；共用那份带的抖音话题不能跟过去。"""
    traffic = {"douyin": ["青年创作者成长计划"], "xiaohongshu": ["AI新手村", "Redskill"], "x": ["AI工具"]}
    copies = {"douyin": {"title": "T", "body": "B", "tags": ["青年创作者成长计划", "自媒体", "咨询"]},
              "xiaohongshu": {"title": "T", "body": "B", "tags": ["自媒体", "咨询"]}}
    shared = publish_desk.shared_entry({"platforms": copies})
    assert publish_desk.own_entry(copies, "xiaohongshu", shared, traffic)["tags"] == ["AI新手村", "Redskill", "自媒体", "咨询"]
    assert publish_desk.own_entry(copies, "douyin", shared, traffic)["tags"] == ["青年创作者成长计划", "自媒体", "咨询"]
    # X 没有自己那份，用共用的：抖音的流量话题换成 X 的，按 X 的上限 3 个截
    assert publish_desk.own_entry(copies, "x", shared, traffic)["tags"] == ["AI工具", "自媒体", "咨询"]
    # 不给 traffic 就照原样
    assert publish_desk.own_entry(copies, "x", shared)["tags"] == ["青年创作者成长计划", "自媒体", "咨询"]


def test_with_traffic_dedupes_and_caps_at_the_platform_limit():
    traffic = {"x": ["a", "b"]}
    assert copypack.with_traffic("x", ["b", "c", "d", "e"], traffic) == ["a", "b", "c"]
    assert copypack.with_traffic("douyin", ["b", "c"], traffic) == ["c"]
