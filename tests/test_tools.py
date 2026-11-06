"""单点功能（10/9 作者：「先做 10 个试试」）：一样东西进、一样东西出。Codex 一律换成假的，不真调。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from content_studio import edition
from content_studio.extras.tools import tools
from tests.test_web import client  # noqa: F401

HEAD = {"x-content-studio": "1"}


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, list]:
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    calls: dict[str, list] = {"text": [], "image": []}

    def no_text(prompt: str) -> str:
        raise AssertionError("这个测试没准备文字回答")

    def no_image(prompt: str, cwd: Path) -> None:
        raise AssertionError("这个测试没准备出图")

    monkeypatch.setitem(tools.TEXT, "fn", no_text)
    monkeypatch.setitem(tools.IMAGE, "fn", no_image)
    monkeypatch.setattr(tools.Queue, "start", lambda self: None)  # 测试里不起后台线程，自己 drain
    return calls


def png(path: Path, w: int, h: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), "white").save(path)


def run(key: str, raw: dict, base: Path) -> dict:
    q = tools.Queue(base)
    got = q.submit(key, raw)
    assert got["state"] == "waiting"
    q.drain()
    return q.read(got["id"])


def test_ten_tools_each_with_a_runner_and_fields() -> None:
    keys = [t["key"] for t in tools.catalog()]
    assert len(keys) == 10 == len(set(keys))
    assert set(keys) == set(tools.RUNS)
    assert {t["kind"] for t in tools.catalog()} == {"text", "image"}
    for t in tools.catalog():
        assert t["fields"] and t["give"] and t["get"]


def test_usecases_references_and_choices() -> None:
    data = json.loads((Path(tools.__file__).parent / "usecases.json").read_text(encoding="utf-8"))
    groups = {g["id"] for scene in data["scenes"] for g in scene["groups"]}
    scenes = {scene["id"] for scene in data["scenes"]}
    for card in data["cards"]:
        assert card["group"] in groups, card["id"]
        assert set(card["alsoGroups"]) <= groups, card["id"]
        assert card["group"] not in card["alsoGroups"], card["id"]
        assert set(card["alsoScenes"]) <= scenes, card["id"]
        assert card["status"] in {"有", "要做", "想法"}, card["id"]
        assert set(card["media"]) <= {"文字", "图片", "视频", "声音", "数据", "抓取"}, card["id"]
        if "tool" in card:
            assert card["tool"] in tools.RUNS, card["id"]
    assert Counter(c["tool"] for c in data["cards"] if "tool" in c) == Counter({key: 1 for key in tools.RUNS})


def test_usecases_asset_is_whitelisted(client) -> None:  # noqa: F811
    response = client.get("/tools/usecases.json")
    assert response.status_code == 200
    assert response.json() == json.loads((Path(tools.__file__).parent / "usecases.json").read_text(encoding="utf-8"))
    assert client.get("/tools/whatever.json").status_code == 404


def test_inputs_are_checked_before_anything_runs(tmp_path: Path) -> None:
    q = tools.Queue(tmp_path)
    with pytest.raises(tools.ToolError, match="还没填"):
        q.submit("review", {"text": "  "})
    with pytest.raises(tools.ToolError, match="下拉"):
        q.submit("style", {"topic": "猫", "style": "随便"})
    with pytest.raises(tools.ToolError, match="数字"):
        q.submit("teardown", {"text": "稿子", "likes": "很多"})
    with pytest.raises(tools.ToolError, match="没有这个功能"):
        q.submit("nope", {})
    assert q.runs() == []


def test_text_tool_runs_through_the_queue_and_keeps_its_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asked = []
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: asked.append(p) or "## 主线\n说清楚了")
    done = run("review", {"text": "第一段。\n\n第二段。"}, tmp_path)
    assert done["state"] == "done" and done["result"]["markdown"].startswith("## 主线")
    assert "第二段" in asked[0] and "5 类生态位" in asked[0]  # 原文进了提示词；不许拿生态位当判定规则
    assert (tmp_path / done["id"] / "run.json").is_file()



def test_titles_from_one_line_with_the_park_writing_frame(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 10/20 只填「这条讲什么」：模型照 park-writing 的格式写了「## 标题候选」，以前解析读到 0 条
    skill = tmp_path / "park-writing"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# park-writing", encoding="utf-8")
    (skill / "references" / "开头.md").write_text("## 输出\n## 开头候选\n## 标题\n## 标题候选\n1. 标题｜句式｜依据：「……」",
                                                   encoding="utf-8")
    monkeypatch.setenv("CONTENT_STUDIO_WRITING_SKILL", str(skill))
    one_line = "新手博主用 AI 从选题到发布一天做完一条视频"
    rows = ["新手博主用AI一天做完一条视频", "一天一条视频新手从选题做到发布", "用AI做一条视频一天走完选题到发布",
            "新手用AI做视频一天连发布一起完成", "一条视频从选题到发布用AI一天做完", "一天做完一条视频新手博主的AI流程"]
    reply = ("<<<ARTICLE>>>\n## 点名的人\n无\n\n## 标题候选\n"
             + "\n".join(f"{i}. {r}｜直接说｜依据：「{one_line}」" for i, r in enumerate(rows, 1))
             + "\n\n## 话题\n新手博主，AI做视频，短视频选题\n<<<END>>>")
    asked = []
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: asked.append(p) or reply)
    done = run("titles", {"topic": one_line, "text": ""}, tmp_path)
    assert done["state"] == "done", done.get("error")
    assert done["result"]["copy"].splitlines() == rows
    assert len(asked) == 1 and one_line in asked[0]

def test_teardown_only_calls_it_a_boom_against_the_accounts_usual_likes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asked = []
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: asked.append(p) or "ok")
    run("teardown", {"text": "稿子", "likes": "3万", "median": "5000"}, tmp_path)
    run("teardown", {"text": "稿子", "likes": "30000"}, tmp_path)
    assert "6.0 倍" in asked[0]
    assert "判断不了" in asked[1] and "不要说它「爆了」" in asked[1]


def test_spoken_cleanup_only_drops_filler_words(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: '{"drop": [[0, "嗯"], [0, "改写"]]}')
    done = run("clean", {"text": "嗯，我今天想说三件事。"}, tmp_path)
    assert done["result"]["copy"] == "我今天想说三件事。"


def test_failures_are_kept_on_the_run_not_raised(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(p: str) -> str:
        raise tools.ToolError("Codex 没回话：codex login")

    monkeypatch.setitem(tools.TEXT, "fn", boom)
    done = run("humanize", {"text": "首先，其次，最后。"}, tmp_path)
    assert done["state"] == "failed" and "codex login" in done["error"]


def test_style_image_must_come_back_3_by_4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prompts = []
    monkeypatch.setitem(tools.IMAGE, "fn", lambda p, cwd: (prompts.append(p), png(cwd / "out/image.png", 900, 1200)))
    done = run("style", {"topic": "一个人做自媒体", "style": "纽约客极简"}, tmp_path)
    assert done["state"] == "done" and done["result"]["images"] == ["out/image.png"]
    assert "纽约客" in prompts[0] and "水印" in prompts[0]
    monkeypatch.setitem(tools.IMAGE, "fn", lambda p, cwd: png(cwd / "out/image.png", 1200, 900))
    bad = run("style", {"topic": "猫", "style": "手绘草图"}, tmp_path)
    assert bad["state"] == "failed" and "3:4" in bad["error"]


def test_cover_needs_a_drawn_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(tools.IMAGE, "fn", lambda p, cwd: None)
    done = run("cover", {"title": "一个人也能做自媒体"}, tmp_path)
    assert done["state"] == "failed" and "没有画出封面" in done["error"]


def test_illustrations_are_inserted_after_their_paragraph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake(prompt: str, cwd: Path) -> None:
        assert "最多 4 张" in prompt
        png(cwd / "illustrations/01-a.png", 1600, 900)
        (cwd / "illustrations/plan.json").write_text(json.dumps([{"file": "01-a.png", "after": "第二段讲的是复利", "caption": "复利"}]), encoding="utf-8")

    monkeypatch.setitem(tools.IMAGE, "fn", fake)
    done = run("illustrate", {"text": "第一段讲的是开头。\n\n第二段讲的是复利怎么滚起来。"}, tmp_path)
    assert done["state"] == "done"
    assert "第二段讲的是复利怎么滚起来。\n\n![复利](illustrations/01-a.png)" in done["result"]["markdown"]
    q = tools.Queue(tmp_path)
    assert q.file(done["id"], "illustrations/01-a.png").is_file()
    for rel in ("../../etc/passwd", "run.json", "article.md"):
        with pytest.raises(tools.ToolError):
            q.file(done["id"], rel)


def test_image_runs_use_the_pinned_model_at_medium_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio import illustrate

    monkeypatch.setattr(illustrate, "codex_bin", lambda: "/usr/local/bin/codex")  # CI 上没装 codex
    argv = tools.image_argv("画一张")
    assert argv[-1] == "画一张"
    assert argv[argv.index("-m") + 1] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="medium"' in argv
    assert "--model sonnet" in tools.TEXT_COMMAND  # llm.run 把 sonnet 翻成 Codex 的 medium


def test_a_restart_marks_the_interrupted_run_failed(tmp_path: Path) -> None:
    q = tools.Queue(tmp_path)
    got = q.submit("humanize", {"text": "原文"})
    q._write({**got, "state": "running"})
    q.recover()
    assert q.read(got["id"])["state"] == "failed"


def test_page_and_api(client) -> None:  # noqa: F811
    assert "单点功能" in client.get("/tools").text
    # 10/20：工作台里这一页只放文字功能，四个出图的去素材页；公开站（CS_STATIC）照旧十个
    js = client.get("/tools/page.js").text
    assert "const LOCAL = !STATIC;" in js and "new Set(['cover', 'illustrate', 'style', 'xhs'])" in js
    assert client.get("/tools/page.js").status_code == 200
    assert client.get("/tools/run.json").status_code == 404
    assert len(client.get("/api/tools").json()["tools"]) == 10
    bad = client.post("/api/tools/humanize/run", json={"text": ""}, headers=HEAD)
    assert bad.status_code == 400 and "还没填" in bad.json()["detail"]
    ok = client.post("/api/tools/humanize/run", json={"text": "原文"}, headers=HEAD).json()
    assert client.get(f"/api/tools/runs/{ok['id']}").json()["state"] == "waiting"
    assert client.get("/api/tools/runs/x").status_code == 400


def test_trial_edition_has_no_tools() -> None:
    assert "tools" in edition.EDITIONS["trial"]
    assert edition.blocked("/api/tools", {"edition": "trial"}) == "tools"
    assert edition.blocked("/api/tools", {}) is None


def test_spoken_cleanup_returns_a_char_diff_of_what_was_dropped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(tools.TEXT, "fn", lambda p: '{"drop": [[0, "嗯"]]}')
    done = run("clean", {"text": "嗯，我今天想说三件事。"}, tmp_path)
    d = done["result"]["diff"]
    assert "".join(t for op, t in d if op == "keep") == done["result"]["copy"]
    assert "".join(t for op, t in d) == "嗯，我今天想说三件事。"  # 原话一个字不少地拼得回来
    assert ["drop", "嗯，"] in d


def test_runs_past_nine_in_one_second_keep_their_order(tmp_path: Path) -> None:
    q = tools.Queue(tmp_path)
    for i in range(11):
        q._write({"id": f"20261010-000027-{i + 1}", "tool": "humanize", "name": "去掉 AI 味", "kind": "text", "input": {"text": "x"},
                  "state": "waiting", "created": "", "result": None, "error": None})
    assert q.next_waiting()["id"] == "20261010-000027-1"
    assert [r["id"] for r in q.runs()][:2] == ["20261010-000027-11", "20261010-000027-10"]


def test_bundled_examples_cover_every_tool_and_their_images_exist() -> None:
    folder = Path(tools.__file__).parent / "examples"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) <= set(tools.RUNS)
    for key, samples in manifest.items():
        assert samples, key
        for s in samples:
            tools.clean_input(key, s["input"])  # 样例的输入就是一次合法的输入
            for name in s["result"].get("images") or []:
                assert (folder / name).is_file(), name
    assert {s["input"]["style"] for s in manifest.get("style", [])} <= set(tools.STYLES)


def test_examples_route_serves_only_example_files(client) -> None:  # noqa: F811
    assert client.get("/tools/examples/manifest.json").status_code == 200
    assert client.get("/tools/examples/..%2Ftools.py").status_code == 404
    assert client.get("/tools/examples/tools.py").status_code == 404
    assert set(client.get("/api/tools").json()["styles"]) == set(tools.STYLES)


def test_xhs_drops_pasted_image_links_it_cannot_carry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from content_studio import xhs_cards

    seen = {}

    def fake_cards(article: Path) -> dict:
        seen["md"] = article.read_text(encoding="utf-8")
        png(article.parent / "xhs/01.png", 1080, 1440)
        return {"images": 1, "over_limit": False}

    monkeypatch.setattr(xhs_cards, "make_cards", fake_cards)
    done = run("xhs", {"title": "标题", "text": "第一段。\n\n![图](./assets/01.png)\n\n第二段。"}, tmp_path)
    assert done["state"] == "done" and "assets" not in seen["md"] and "第二段。" in seen["md"]


def test_static_export_for_the_public_site_needs_no_backend(tmp_path: Path) -> None:
    """10/10：example.com/tools/ 是纯静态页——不指向 /api/、/static/，目录布局和工作台里的网址一致。"""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("export_tools_site", root / "scripts/export-tools-site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "tools"
    mod.main(out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "window.CS_STATIC = true" in html and "/api/" not in html and "/static/" not in html
    catalog = json.loads((out / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["tools"]) == 10 and set(catalog["styles"]) == set(tools.STYLES)
    for rel in ("styles.css", "page.css", "page.js", "usecases.json", "vendor/marked.min.js", "vendor/purify.min.js", "examples/manifest.json"):
        assert (out / rel).is_file(), rel
    assert (out / "usecases.json").read_bytes() == (mod.PKG / "usecases.json").read_bytes()
    assert "STATIC" in (out / "page.js").read_text(encoding="utf-8")


def test_style_gallery_lists_styles_serves_samples_and_records_reviews(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from content_studio.extras.tools import gallery, styles

    samples = tmp_path / "samples"
    samples.mkdir()
    sid = next(s["id"] for s in styles.load_all() if s["function"] == "image" and s.get("listed"))
    png(samples / "x.png", 30, 40)
    Image.open(samples / "x.png").save(samples / f"{sid}.webp", "WEBP")
    monkeypatch.setenv("CONTENT_STUDIO_STYLE_SAMPLES", str(samples))
    assert "风格画廊" in client.get("/tools/styles").text
    assert client.get("/tools/gallery.js").status_code == 200
    data = client.get("/tools/styles.json").json()
    row = next(s for s in data["styles"] if s["id"] == sid)
    assert row["sample"] is True and row["src"]["repo"] and row["review"] is None
    assert all(s["fn"] in ("image", "video", "motion") for s in data["styles"])
    assert client.get(f"/tools/styles/sample/{sid}.webp").status_code == 200
    assert client.get("/tools/styles/sample/..%2Fetc.webp").status_code == 404
    r = client.post(f"/api/tools/styles/{sid}/review", json={"verdict": "redo", "note": "字太小"}, headers=HEAD)
    assert r.json()["review"]["verdict"] == "redo" and gallery.reviews()[sid]["note"] == "字太小"
    assert client.post(f"/api/tools/styles/{sid}/review", json={"verdict": "maybe"}, headers=HEAD).status_code == 400
    assert client.post("/api/tools/styles/nope/review", json={"verdict": "approve"}, headers=HEAD).status_code == 404
    client.post(f"/api/tools/styles/{sid}/review", json={"verdict": "approve"}, headers=HEAD)
    assert [s["id"] for s in gallery.catalog(approved_only=True)["styles"]] == [sid]
    client.post(f"/api/tools/styles/{sid}/review", json={"verdict": ""}, headers=HEAD)
    assert sid not in gallery.reviews()


def test_style_accepts_gallery_styles_he_approved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """10/11：画廊里通过的风格，填一句主题就能画；没通过的不认。比例跟着风格走，不卡 3:4。"""
    from content_studio.extras.tools import gallery, styles

    sid = next(s["id"] for s in styles.load_all() if s["function"] == "image" and s.get("listed"))
    with pytest.raises(tools.ToolError, match="下拉"):
        tools.clean_input("style", {"topic": "猫", "style": sid})
    gallery.review(sid, "approve")
    assert tools.clean_input("style", {"topic": "猫", "style": sid})["style"] == sid
    with pytest.raises(tools.ToolError):
        tools.clean_input("style", {"topic": "猫", "style": "../etc"})
    prompts = []
    monkeypatch.setitem(tools.IMAGE, "fn", lambda p, cwd: (prompts.append(p), png(cwd / "out/image.png", 1200, 900)))
    done = run("style", {"topic": "一只会写稿的猫", "style": sid}, tmp_path)
    assert done["state"] == "done" and done["result"]["images"] == ["out/image.png"]
    assert "一只会写稿的猫" in prompts[0] and "{topic}" not in prompts[0]


def test_static_export_puts_only_approved_styles_in_the_gallery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import importlib.util
    from content_studio.extras.tools import gallery, styles

    ids = [s["id"] for s in styles.load_all() if s["function"] == "image" and s.get("listed")][:2]
    samples = tmp_path / "samples"
    samples.mkdir()
    for sid in ids:
        png(samples / "x.png", 1440, 1920)
        Image.open(samples / "x.png").save(samples / f"{sid}.webp", "WEBP")
    monkeypatch.setenv("CONTENT_STUDIO_STYLE_SAMPLES", str(samples))
    gallery.review(ids[0], "approve")
    gallery.review(ids[1], "redo")
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("export_tools_site", root / "scripts/export-tools-site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "tools"
    mod.main(out)
    data = json.loads((out / "styles.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in data["styles"]] == [ids[0]] and data["styles"][0]["prompt"] == ""
    assert Image.open(out / "styles" / f"{ids[0]}.webp").width == 720
    assert not (out / "styles" / f"{ids[1]}.webp").exists()
    page = (out / "styles" / "index.html").read_text(encoding="utf-8")
    assert "window.CS_STATIC = true" in page and "/static/" not in page and "/api/" not in page
    assert (out / "gallery.js").is_file() and (out / "gallery.css").is_file()


def _export_module():
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("export_tools_site", root / "scripts/export-tools-site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_video_samples_are_served_only_from_the_manifest(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """10/16：视频样片的成片放本机 tool-videos/，清单里有的才给，别的文件和越级路径一律 404。"""
    from content_studio.extras.tools import videos

    folder = tmp_path / "vids"
    folder.mkdir()
    monkeypatch.setenv("CONTENT_STUDIO_TOOL_VIDEOS", str(folder))
    first = videos.manifest()["groups"][0]["items"][0]["id"]
    (folder / f"{first}.mp4").write_bytes(b"mp4")
    (folder / "other.mp4").write_bytes(b"x")
    assert client.get("/tools/videos.json").json()["groups"]
    assert client.get(f"/tools/videos/{first}.mp4").content == b"mp4"
    assert client.get(f"/tools/videos/{first}.webp").status_code == 404
    assert client.get("/tools/videos/other.mp4").status_code == 404
    assert client.get("/tools/videos/..%2Fvideos.py").status_code == 404


def test_video_manifest_names_three_groups_with_real_fields() -> None:
    from content_studio.extras.tools import videos

    groups = videos.manifest()["groups"]
    assert [g["key"] for g in groups] == ["brand", "huashu", "opus"]
    ids = [v["id"] for g in groups for v in g["items"]]
    assert len(ids) == len(set(ids)) and all(3 <= len(g["items"]) <= 4 for g in groups)
    for g in groups:
        assert g["url"].startswith("https://github.com/") and g["url"].endswith(g["repo"])
        for v in g["items"]:
            assert v["title"] and v["give"] and v["secs"] > 0 and isinstance(v["sound"], bool)
            assert ("credit" in v) == (g["key"] == "opus")


def test_static_export_copies_video_samples_or_leaves_the_section_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from content_studio.extras.tools import videos

    mod = _export_module()
    folder = tmp_path / "vids"
    folder.mkdir()
    monkeypatch.setenv("CONTENT_STUDIO_TOOL_VIDEOS", str(folder))
    out = tmp_path / "tools"
    out.mkdir()
    assert mod.export_videos(out) == 0 and json.loads((out / "videos.json").read_text()) == {"groups": []}
    names = videos.files()
    (folder / names[0]).write_bytes(b"one")
    with pytest.raises(SystemExit):
        mod.export_videos(out)
    for name in names:
        (folder / name).write_bytes(name.encode())
    assert mod.export_videos(out) == len(names) // 2
    assert (out / "videos" / names[-1]).read_bytes() == names[-1].encode()
    assert json.loads((out / "videos.json").read_text()) == videos.manifest()
