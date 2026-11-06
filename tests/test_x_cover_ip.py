"""X 长文封面（10/10 作者）：像抖音封面，人换成他的 作者 形象，红色更多，标题为点击率写；出不来不挡发文。"""
from __future__ import annotations

from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from content_studio.extras.xline import x_cover_ip, x_daily
from test_x_line import client_factory  # noqa: F401 - fixture

ARTICLE = "# 自媒体仅仅是我的获客渠道\n\n10 万粉丝每个月可以变现 50 万。流量应该只占你 10%~20% 的精力。\n"


def model(prompt: str) -> str:
    assert "不要用「我觉得」" in prompt and "暴论" in prompt
    return ("1. 10万粉能月入50万｜算账｜依据：「10 万粉丝每个月可以变现 50 万」\n"
            "2. 我觉得流量不重要｜绝对否定｜依据：「…」\n"                    # 「我觉得」开头：扔
            "3. 100万粉才能赚钱｜算账｜依据：「…」\n"                        # 数字原文没有：扔
            "4. 流量最多只值20%精力｜攻击流行说法｜依据：「流量应该只占你 10%~20% 的精力」\n"
            "5. 想赚钱就别把流量当全部｜攻击流行说法｜依据：「…」\n"
            "6. 做自媒体只是为了获客｜绝对否定｜依据：「…」\n"
            "7. 这是一个特别特别特别特别长的封面标题根本放不下｜悖论｜依据：「…」")


def test_headlines_follow_the_title_rules_and_drop_what_the_article_cannot_back() -> None:
    hs = x_cover_ip.headlines("自媒体仅仅是我的获客渠道", ARTICLE, write_fn=model, framework="暴论")
    assert [h["title"] for h in hs] == ["10万粉能月入50万", "流量最多只值20%精力", "想赚钱就别把流量当全部", "做自媒体只是为了获客"]
    assert hs[0]["pattern"] == "算账"
    with pytest.raises(x_cover_ip.CoverError, match="没写出来"):
        x_cover_ip.headlines("t", ARTICLE, write_fn=lambda p: "随便说点什么", framework="暴论")


def fake_draw(tmp_path: Path):
    from PIL import Image

    def runner(prompt: str, cwd: Path) -> None:
        assert "SOLE CHARACTER SOURCE" in prompt and "#E2461F" in prompt and "5:2" in prompt
        assert (cwd / "persona-ref" / "fullbody.png").is_file() and (cwd / "style-ref.png").is_file()
        Image.new("RGB", (1536, 1024), (226, 70, 31)).save(cwd / "out" / "cover.png")
        (cwd / "out" / "receipt.json").write_text('{"checks": {"text": "ok"}}', encoding="utf-8")
    return runner


@pytest.fixture
def persona(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from PIL import Image

    root = tmp_path / "persona"
    root.mkdir()
    for n in ("fullbody.png", "avatar.png"):
        Image.new("RGB", (10, 10)).save(root / n)
    (root / "spec.md").write_text("作者", encoding="utf-8")
    koubo = tmp_path / "koubo" / "assets" / "covers"
    koubo.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(koubo / "park-bold-orange-v1-4x3.png")
    monkeypatch.setenv("CONTENT_STUDIO_PERSONA", str(root))
    monkeypatch.setenv("CONTENT_STUDIO_KOUBO_SKILL", str(tmp_path / "koubo"))
    return root


def test_draw_uses_his_figure_and_style_ref_then_crops_to_five_by_two(tmp_path: Path, persona: Path) -> None:
    from PIL import Image

    folder = tmp_path / "post"
    folder.mkdir()
    out = x_cover_ip.draw(folder, "10万粉能月入50万", runner=fake_draw(tmp_path))
    assert out == folder / "x-cover.png" and Image.open(out).size == (1500, 600)
    assert not (folder / x_cover_ip.WORK).exists() and (folder / "x-cover.receipt.json").is_file()
    x_cover_ip.draw(folder, "流量最多只值20%精力", runner=fake_draw(tmp_path))
    assert (folder / "x-cover.old.png").is_file()  # 上一张留着


def test_cover_is_made_for_ready_articles_redone_on_his_pick_and_used_when_publishing(client_factory, tmp_path: Path,  # noqa: F811
                                                                                     persona: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio.extras.xline import x_article, x_long

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("content_studio.titles.load_framework", lambda root=None: "暴论")
    client: TestClient = client_factory(write_fn=model, x_cover_fn=fake_draw(tmp_path), x_fetch_fn=lambda url: [] if "manifest" in url else {})
    key = x_daily.day_key(x_daily.now_bj())
    art = x_long.folder(f"{key}-L0") / "article.md"
    art.parent.mkdir(parents=True)
    art.write_text(ARTICLE, encoding="utf-8")
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [
        {"id": f"{key}-L0", "long": True, "prep": "ready", "state": "pending", "text": ARTICLE, "article": str(art), "source_id": "s"},
        {"id": f"{key}-P0", "long": True, "format": "post", "prep": "ready", "state": "pending", "text": "长帖不出封面"}],
        "planned_at": "x", "long_planned_at": "x", "long_target": [5, 5], "halted": None}}})
    job = x_daily.cover_next(x_daily.path())
    assert job[1]["id"] == f"{key}-L0"
    client.app.state.x_long_cover(*job)
    post = client.get("/api/xline/daily").json()["today"]["posts"][0]
    assert post["cover"] == "ready" and post["cover_title"] == "10万粉能月入50万" and len(post["cover_titles"]) == 4
    assert client.get(f"/api/xline/daily/{key}/{key}-L0/file/x-cover.png").status_code == 200
    assert x_daily.cover_next(x_daily.path()) is None  # 长帖不出封面

    assert client.post(f"/api/xline/daily/{key}/{key}-L0/cover", json={"title": "流量最多只值20%精力"}).json()["started"] is True
    for _ in range(100):
        post = client.get("/api/xline/daily").json()["today"]["posts"][0]
        if post["cover"] != "running":
            break
        time.sleep(0.05)
    assert post["cover"] == "ready" and post["cover_title"] == "流量最多只值20%精力" and len(post["cover_titles"]) == 4  # 候选留着
    assert client.post(f"/api/xline/daily/{key}/{key}-P0/cover", json={}).status_code == 400

    used = []
    monkeypatch.setattr(x_article, "publish_article", lambda article, publish, cover=None: used.append(cover) or {"published": True, "url": "u"})
    client.app.state.x_send(ARTICLE, long=True, post=post)
    assert used == [art.parent / "x-cover.png"]  # 发的时候用这张封面


def test_carried_article_shows_cover_and_illustrations_and_redoes_in_its_own_folder(client_factory, tmp_path: Path,  # noqa: F811
                                                                                   persona: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10/13 作者：「封面为什么显示不出来」——昨天没存草稿的长文挪到今天换了 id，文件还在昨天那个文件夹。"""
    from content_studio.extras.xline import x_long

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    client: TestClient = client_factory(write_fn=model, x_cover_fn=fake_draw(tmp_path), x_fetch_fn=lambda url: [] if "manifest" in url else {})
    key = x_daily.day_key(x_daily.now_bj())
    art = x_long.folder("2026-10-12-A2") / "article.md"
    (art.parent / "illustrations").mkdir(parents=True)
    art.write_text(ARTICLE, encoding="utf-8")
    (art.parent / "x-cover.png").write_bytes(b"cover")
    (art.parent / "illustrations" / "01.png").write_bytes(b"img")
    pid = f"{key}-c2026-10-12-A2"
    x_daily.save(x_daily.path(), {"days": {key: {"posts": [
        {"id": pid, "long": True, "prep": "ready", "state": "pending", "text": ARTICLE, "article": str(art), "source_id": "s",
         "cover": "ready", "cover_title": "旧标题", "carried_from": "2026-10-12", "manual_publish": True}],
        "planned_at": "x", "long_planned_at": "x", "halted": None}}})
    assert client.get(f"/api/xline/daily/{key}/{pid}/file/x-cover.png").content == b"cover"
    assert client.get(f"/api/xline/daily/{key}/{pid}/file/illustrations/01.png").content == b"img"
    assert client.get(f"/api/xline/daily/{key}/{pid}/file/%2E%2E/%2E%2E/x_daily.json").status_code == 404

    assert client.post(f"/api/xline/daily/{key}/{pid}/cover", json={"title": "流量最多只值20%精力"}).json()["started"] is True
    for _ in range(100):
        post = client.get("/api/xline/daily").json()["today"]["posts"][0]
        if post["cover"] != "running":
            break
        time.sleep(0.05)
    assert post["cover"] == "ready" and (art.parent / "x-cover.old.png").read_bytes() == b"cover"  # 重出也在原来的文件夹，存草稿用的就是它
    assert not x_long.folder(pid).exists()
