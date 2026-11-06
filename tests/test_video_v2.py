"""口播动效 v2 项目在工作台里的显示和按钮。pv2.py 用一个假的脚本代替，只记下被怎么调用。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from content_studio import video_project
from content_studio.extras.motion import video_v2

from test_web import client  # noqa: F401  (fixture)

FAKE = '''import json, sys, pathlib
log = pathlib.Path(__file__).with_name("calls.log")
log.open("a").write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
cmd = sys.argv[1]
if cmd == "status":
    print(json.dumps({"step": "方案", "percent": None, "waiting_for": "作者 看样片", "failed": False, "detail": "",
                      "sample": "v2/sample.mp4", "final": None}, ensure_ascii=False))
elif cmd == "init":
    v2 = pathlib.Path(sys.argv[2]) / "v2"
    v2.mkdir(parents=True, exist_ok=True)
    (v2 / "brief.yaml").write_text("# 模板\\n", encoding="utf-8")
    print(str(v2))
elif cmd == "approve":
    print(json.dumps({"by": "作者", "message": sys.argv[sys.argv.index("-m") + 1]}, ensure_ascii=False))
elif cmd in ("sample", "render"):
    print("已在后台启动")
elif cmd == "settings":
    print(json.dumps({"schema": {"sliders": [{"key": "density", "name": "密度", "levels": [{"value": "low", "label": "低"}, {"value": "medium", "label": "中"}]}],
                                 "choices": [], "presets": []},
                      "values": {"density": "medium"}, "source": {"density": "repo"}, "components": []}, ensure_ascii=False))
elif cmd == "set":
    values = json.loads(sys.argv[4])
    if values.get("effort") == "c":
        print(json.dumps({"error": "动效努力「像专业 AE」这一档还没做，先选别的档"}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"written": sys.argv[2], "values": values}, ensure_ascii=False))
elif cmd == "catalog":
    home = pathlib.Path(__file__).parents[1]
    print(json.dumps([{"key": "Cycle", "name": "飞轮循环", "form": "diagram", "effort": "b",
                       "video": str(home / "gallery" / "Cycle.mp4"), "poster": None}], ensure_ascii=False))
elif cmd == "shotcraft":
    home = pathlib.Path(__file__).parents[1]
    print(json.dumps([{"name": "cycle-glass-node-morph", "summary": "循环图", "category_zh": "数据与指标",
                       "poster": str(home / "sc-cycle.jpg"), "video": str(home / "sc-cycle.mp4"), "adapted_as": ["Cycle"]},
                      {"name": "aurora-bloom-bg-flip", "summary": "极光", "category_zh": "开场", "poster": None, "video": None,
                       "adapted_as": []}],
                     ensure_ascii=False))
else:
    sys.exit("unknown")
'''


@pytest.fixture
def pv2_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "pv2"
    (home / "scripts").mkdir(parents=True)
    (home / "scripts" / "pv2.py").write_text(FAKE, encoding="utf-8")
    monkeypatch.setenv(video_v2.HOME_ENV, str(home))
    return home


def calls(home: Path) -> list[list[str]]:
    path = home / "scripts" / "calls.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _v2_project(root: Path, name: str) -> Path:
    base = root / name
    (base / "v2").mkdir(parents=True)
    (base / "v2" / "brief.yaml").write_text("video_type: 横屏口播\n", encoding="utf-8")
    return base


def test_v2_project_shows_four_steps_and_real_status(tmp_path: Path, pv2_home: Path) -> None:
    root = tmp_path / "videos"
    _v2_project(root, "2026-10-03_new")
    info = video_project.inspect(root, "2026-10-03_new")
    assert info["layout"] == "v2"
    assert info["v2"]["waiting_for"] == "作者 看样片" and info["v2"]["sample"] == "v2/sample.mp4"
    assert [s["state"] for s in info["stages"]] == ["done", "current", "todo", "todo"]
    assert info["summary"] == "方案 · 等 作者 看样片" and info["delivered"] is False and info["gate"] is None
    assert "park-video-v2" in info["continue_command"]


def test_old_project_with_a_v2_folder_stays_on_the_old_flow(tmp_path: Path, pv2_home: Path) -> None:
    root = tmp_path / "videos"
    base = _v2_project(root, "2026-10-02_old")
    (base / "project.json").write_text(json.dumps({"workflow": "ask-park-video/v1", "presets": {}}), encoding="utf-8")
    assert video_project.inspect(root, "2026-10-02_old")["layout"] != "v2"


def test_missing_pv2_is_reported_not_crashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(video_v2.HOME_ENV, str(tmp_path / "nowhere"))
    root = tmp_path / "videos"
    _v2_project(root, "p")
    st = video_project.inspect(root, "p")["v2"]
    assert st["failed"] is True and "找不到 park-video-v2" in st["detail"]


def test_buttons_go_through_to_pv2(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    root = tmp_path / "videos"
    base = _v2_project(root, "2026-10-03_new")
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "拍这条", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    assert client.get(f"/api/topics/{topic['id']}/video-project").json()["layout"] == "v2"

    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/approve", json={"gate": "sample", "message": "可以，全部渲染"})
    assert r.status_code == 200 and r.json()["approval"]["message"] == "可以，全部渲染"
    assert ["approve", str(base), "sample", "-m", "可以，全部渲染"] in calls(pv2_home)

    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/approve", json={"gate": "sample", "message": " "}).status_code == 400
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/approve", json={"gate": "H2", "message": "x"}).status_code == 400

    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/start", json={"job": "render"})
    assert r.status_code == 200 and ["render", str(base), "--detach"] in calls(pv2_home)
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/start", json={"job": "rm"}).status_code == 400


def test_v2_buttons_refuse_old_projects(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    root = tmp_path / "videos"
    (root / "2026-01-01_old" / "delivery").mkdir(parents=True)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "旧的", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": "2026-01-01_old"})
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/start", json={"job": "sample"}).status_code == 400



def _linked(client: TestClient, tmp_path: Path) -> tuple[dict, Path]:  # noqa: F811
    root = tmp_path / "videos"
    base = _v2_project(root, "2026-10-03_new")
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "拍这条", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    return topic, base


def test_settings_come_from_pv2_and_saves_go_back_to_it(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    topic, base = _linked(client, tmp_path)
    r = client.get(f"/api/topics/{topic['id']}/video-project/v2/settings")
    assert r.status_code == 200 and r.json()["schema"]["sliders"][0]["key"] == "density"
    assert ["settings", str(base)] in calls(pv2_home)

    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/settings", json={"values": {"density": "low"}})
    assert r.status_code == 200 and r.json()["result"]["values"] == {"density": "low"}
    assert ["set", str(base), "--json", '{"density": "low"}'] in calls(pv2_home)

    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/settings", json={"values": {"card": "dark"}, "scope": "default"})
    assert r.status_code == 200 and ["set", "default", "--json", '{"card": "dark"}'] in calls(pv2_home)


def test_make_motion_turns_a_rough_cut_project_into_v2(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    # 10/5：粗剪放进项目后点「做动效」，设置面板就在页面上，不用先去对话里
    root = tmp_path / "videos"
    base = root / "2026-10-05_粗剪"
    (base / "subtitles").mkdir(parents=True)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "拍这条", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/init")
    assert r.status_code == 400 and "粗剪" in r.json()["error"] and not calls(pv2_home)

    (base / "粗剪-10月5日.mov").write_bytes(b"0" * 32)
    (base / "subtitles" / "source.srt").write_text("1\n", encoding="utf-8")
    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/init")
    assert r.status_code == 200 and r.json()["project"]["layout"] == "v2"
    assert ["init", str(base.resolve()), "--video", "粗剪-10月5日.mov", "--srt", "subtitles/source.srt"] in calls(pv2_home)
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/init").json()["already"] is True


def test_make_motion_refuses_old_fourteen_step_projects(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    root = tmp_path / "videos"
    base = root / "2026-09-22_旧"
    base.mkdir(parents=True)
    (base / "project.json").write_text("{}", encoding="utf-8")
    (base / "粗剪.mp4").write_bytes(b"0" * 32)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "旧的", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/init")
    assert r.status_code == 400 and "旧流程" in r.json()["error"] and not calls(pv2_home)


def test_settings_page_reads_and_writes_only_the_defaults(client: TestClient, pv2_home: Path) -> None:  # noqa: F811
    r = client.get("/api/video-v2/settings")
    assert r.status_code == 200 and r.json()["values"]["density"] == "medium" and ["settings"] in calls(pv2_home)
    r = client.post("/api/video-v2/settings", json={"values": {"density": "low"}, "scope": "default"})
    assert r.status_code == 200 and ["set", "default", "--json", '{"density": "low"}'] in calls(pv2_home)
    assert client.post("/api/video-v2/settings", json={"values": {"density": "low"}}).status_code == 400


def test_unbuilt_level_is_refused_with_pv2s_own_words(client: TestClient, tmp_path: Path, pv2_home: Path) -> None:  # noqa: F811
    topic, _base = _linked(client, tmp_path)
    r = client.post(f"/api/topics/{topic['id']}/video-project/v2/settings", json={"values": {"effort": "c"}})
    assert r.status_code == 400 and "还没做" in r.json()["error"]
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/settings", json={"values": {}}).status_code == 400
    assert client.post(f"/api/topics/{topic['id']}/video-project/v2/settings",
                       json={"values": {"density": "low"}, "scope": "everyone"}).status_code == 400


def test_catalog_gives_urls_not_local_paths_and_serves_the_files(client: TestClient, pv2_home: Path) -> None:  # noqa: F811
    (pv2_home / "gallery").mkdir()
    (pv2_home / "gallery" / "Cycle.mp4").write_bytes(b"\x00\x00mp4")
    (pv2_home / "sc-cycle.jpg").write_bytes(b"\xff\xd8jpg")
    (pv2_home / "sc-cycle.mp4").write_bytes(b"\x00\x00sc-mp4")
    data = client.get("/api/video-v2/catalog").json()
    comp = data["components"][0]
    assert comp["video_url"] == "/api/video-v2/media/gallery/Cycle.mp4" and "video" not in comp
    cards = {c["name"]: c for c in data["shotcraft"]}
    assert cards["cycle-glass-node-morph"]["poster_url"].endswith("/shotcraft/cycle-glass-node-morph.jpg")
    assert cards["cycle-glass-node-morph"]["video_url"].endswith("/shotcraft/cycle-glass-node-morph.mp4")
    assert cards["aurora-bloom-bg-flip"]["poster_url"] is None and cards["aurora-bloom-bg-flip"]["video_url"] is None
    assert str(pv2_home) not in json.dumps(data)
    assert client.get("/api/video-v2/media/gallery/Cycle.mp4").content == b"\x00\x00mp4"
    assert client.get("/api/video-v2/media/shotcraft/cycle-glass-node-morph.jpg").content == b"\xff\xd8jpg"
    assert client.get("/api/video-v2/media/shotcraft/cycle-glass-node-morph.mp4").content == b"\x00\x00sc-mp4"
    assert client.get("/api/video-v2/media/shotcraft/aurora-bloom-bg-flip.mp4").status_code == 400
    assert client.get("/api/video-v2/media/gallery/..%2Fsecret.mp4").status_code in (400, 404)
    assert client.get("/api/video-v2/media/other/Cycle.mp4").status_code == 400


def test_changing_your_mind_goes_back_to_the_motion_choice_without_deleting(
        client: TestClient, tmp_path: Path, pv2_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """10/7 作者 点了「做动效」想退回来，只能取消关联；点「不加动效」又看到「还没按 14 步初始化」。"""
    root = tmp_path / "videos"
    base = _v2_project(root, "2026-10-07_爆款拆解")
    (base / "粗剪-10月7日.mov").write_bytes(b"x" * 100)
    client.put("/api/settings", json={"video_projects_root": str(root)})
    topic = client.post("/api/topics", json={"title": "爆款拆解", "formats": "video"}).json()
    client.put(f"/api/topics/{topic['id']}/video-project", json={"name": base.name})
    url = f"/api/topics/{topic['id']}/video-project"

    monkeypatch.setattr(video_v2, "status", lambda _b: {"step": "渲染", "percent": 40, "waiting_for": None, "failed": False})
    busy = client.post(f"{url}/back")
    assert busy.status_code == 400 and "正在渲染" in busy.json()["error"]
    monkeypatch.undo()
    monkeypatch.setenv(video_v2.HOME_ENV, str(pv2_home))

    r = client.post(f"{url}/back")
    assert r.status_code == 200, r.text
    assert not (base / "v2").exists()
    kept = [p for p in base.iterdir() if p.name.startswith(".v2-撤回-")]
    assert len(kept) == 1 and (kept[0] / "brief.yaml").is_file()
    info = client.get(url).json()
    assert info["layout"] == "legacy" and not info["delivered"]  # 回到「粗剪放好了：加不加动效？」

    assert client.post(f"{url}/external", json={"what": "all"}).status_code == 200
    assert client.get(url).json()["delivered"] is True
    r = client.post(f"{url}/back")
    assert r.status_code == 200, r.text
    assert (base / "粗剪-10月7日.mov").is_file() and not (base / "final").exists()
    assert any(p.name.startswith(".final-撤回-") for p in base.iterdir())
    info = client.get(url).json()
    assert info["layout"] == "legacy" and not info["delivered"]

    again = client.post(f"{url}/back")
    assert again.status_code == 400 and "还没选" in again.json()["error"]
