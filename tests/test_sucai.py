"""素材页（10/18）：读临时 vault 和素材卡，好网站清单用假的，不联网。"""
from __future__ import annotations

import json
from pathlib import Path

from content_studio.extras.materials import sucai
from tests.test_web import client  # noqa: F401

VIDEO = """---
title: 影响客单价的三个核心要素 #自媒体 #创业
source: https://www.douyin.com/video/1
author: 一勾工作号
published: 2026-10-11T12:05:11
likes: 1801
multiple_of_median: 3.4
---
# 影响客单价的三个核心要素

## 主线
想提高客单价，要同时提升前端质感、选题和后端销售。

## 为什么爆
- 开头用「交付一样，售价却不同」制造矛盾。
- 归纳成三个可自查的环节。

## 全文
……
"""
MANIFEST = [{"id": "gp-001", "title": "NewsLiquid", "source_url": "https://newsliquid.example", "note": "新闻和交易同一屏\n", "image": "images/a.png", "collected_at": "2026-10-10"},
            {"id": "bad", "title": ""}]
DECK = {"source": {"id": "gh-a-b", "url": "https://github.com/a/b", "author": "a", "learned_at": "2026-10-17T13:00:00"},
        "cards": [{"name": "lighttable", "title": "档案灯台", "what": "老照片铺在桌上", "when": "讲老物件", "category": "实证影像", "status": "kept",
                   "poster": "lighttable.jpg", "sample": "lighttable.mp4", "source_url": "https://github.com/a/b/tree/x", "pushed_at": "2026-10-17T14:47:20"},
                  {"name": "dropped", "title": "不要的", "status": "dropped"}]}


def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    (v / sucai.VIDEO_FOLDER).mkdir(parents=True)
    (v / sucai.VIDEO_FOLDER / "a.md").write_text(VIDEO, encoding="utf-8")
    (v / sucai.VIDEO_FOLDER / "no-link.md").write_text("---\ntitle: 没链接\n---\n", encoding="utf-8")
    return v


def test_videos_cards_and_sites_are_read_as_they_are(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sucai, "_sites", {"at": 0.0, "items": [], "why": ""})
    out = sucai.listing("all", decks=[DECK], vault=vault(tmp_path), site_fetch=lambda url: MANIFEST)
    kinds = {k["key"]: k["count"] for k in out["kinds"]}
    assert kinds == {"card": 1, "video": 1, "site": 1}
    by = {x["kind"]: x for x in out["items"]}
    assert by["video"]["title"] == "影响客单价的三个核心要素" and by["video"]["note"].startswith("开头用") and by["video"]["stats"] == {"likes": 1801, "multiple": 3.4}
    assert by["card"]["image"] == "/materials/media/gh-a-b/lighttable.jpg" and by["card"]["video"] == "/materials/media/gh-a-b/lighttable.mp4"
    assert by["site"]["image"] == sucai.SITES_BASE + "images/a.png" and by["site"]["excerpt"] == "新闻和交易同一屏"
    assert [x["kind"] for x in out["items"]] == ["card", "video", "site"]  # 新的在前


def test_sites_failure_keeps_page_working_and_is_cached(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sucai, "_sites", {"at": 0.0, "items": [], "why": ""})
    calls = []

    def boom(url):
        calls.append(url)
        raise OSError("断网")
    out = sucai.listing("site", decks=[], vault=None, site_fetch=boom)
    assert out["items"] == [] and "没取到" in out["why"]
    sucai.listing("site", decks=[], vault=None, site_fetch=boom)
    assert len(calls) == 1  # 一小时内不再问


def test_api(client, tmp_path: Path, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(sucai, "_sites", {"at": 0.0, "items": [], "why": ""})
    client.app.state.sucai_fetch = lambda url: MANIFEST
    assert "素材" in client.get("/sucai").text
    assert client.get("/sucai/sucai.js").status_code == 200 and client.get("/sucai/other.txt").status_code == 404
    assert client.get("/api/sucai?kind=nope").status_code == 400
    d = client.get("/api/sucai?kind=site").json()
    assert d["items"][0]["title"] == "NewsLiquid"
