"""两层内容框架：只用临时 workflows、素材库和草稿，不碰真实 vault。"""
from pathlib import Path
import subprocess
import time
from unittest.mock import Mock

import pytest

from content_studio import coupon, frames, outline, titles
from content_studio.writer import WriterError
from test_outline import GOOD
from test_coupon import _good
from test_web import client  # noqa: F401

SERIES = "系列1 一人自媒体究竟怎么做"
FRAME = "# 系列规则\n\n先展示结果，再讲操作。\n"
MATERIAL = "我把三条选题排进周一到周三，每次只拍一条。"
WITH_MATERIAL = FRAME + f"\n## 每集材料\n说明\n\n### 选题排期\n{MATERIAL}\n\n### 下一集\n其他事实。\n\n## 补充\n不是本集材料。\n"
TOPIC = {"id": 3, "title": "选题排期", "note_paths": [], "series": SERIES}


@pytest.fixture
def workflows(tmp_path, monkeypatch):
    root = tmp_path / "frame-workflows"
    root.mkdir()
    for filename in (outline.FRAMEWORK_FILE, coupon.FRAMEWORK_FILE, titles.FRAMEWORK_FILE):
        (root / filename).write_text("# 通用规则\n照材料写。\n", encoding="utf-8")
    monkeypatch.setenv(outline.WORKFLOWS_ENV, str(root))
    return root


def test_series_without_facts_does_not_call_model(tmp_path, workflows):
    write = Mock()
    with pytest.raises(WriterError, match="还没有材料"):
        outline.write_outline(TOPIC, vault_raw=str(tmp_path), drafts_dir=tmp_path / "drafts",
                              series_frame=FRAME, write_fn=write)
    write.assert_not_called()


def test_episode_facts_and_both_layers_without_review_adjustments(tmp_path, workflows):
    write = Mock(return_value=f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>")
    result = outline.write_outline(TOPIC, vault_raw=str(tmp_path), drafts_dir=tmp_path / "drafts",
                                   series_frame=WITH_MATERIAL, episode_material=frames.episode_material(WITH_MATERIAL, "选题排期"),
                                   adjustments=["每条封面不超过12个字"], write_fn=write)
    prompt = write.call_args.args[0]
    assert "通用规则" in prompt and WITH_MATERIAL in prompt and MATERIAL in prompt
    assert f"## 这一集的材料（真实事实，只能用这里和素材里的事实）\n{MATERIAL}" in prompt
    assert "封面" not in prompt and "12个字" not in prompt and "每周复盘" not in prompt
    assert result["frames"] == ["骨架", SERIES]
    assert outline.read_outline(result)["frames"] == result["frames"]


def test_non_series_still_writes_from_sources(tmp_path, workflows, monkeypatch):
    source = {"path": "note.md", "url": "", "title": "原话", "body": "我是这样安排选题的。"}
    monkeypatch.setattr(outline, "topic_sources", lambda *args: [source])
    write = Mock(return_value=f"<<<ARTICLE>>>\n{GOOD}\n<<<END>>>")
    result = outline.write_outline({"id": 4, "title": "选题"}, vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=write)
    assert source["body"] in write.call_args.args[0]
    assert "这个系列的框架" not in write.call_args.args[0]
    assert result["frames"] == ["骨架"]


def test_load_and_exact_episode_section(workflows):
    assert frames.load_series_frame(None) == frames.load_series_frame(SERIES) == ""
    path = frames.series_frame_path(SERIES)
    path.parent.mkdir()
    path.write_text("---\nprivate: metadata\n---\n" + WITH_MATERIAL, encoding="utf-8")
    assert frames.load_series_frame(SERIES) == WITH_MATERIAL.strip()
    assert frames.episode_material(WITH_MATERIAL, "选题排期") == MATERIAL
    assert frames.episode_material(WITH_MATERIAL, "选题") == ""
    assert frames.episode_material("### 选题排期\n不在每集材料中", "选题排期") == ""
    assert frames.episode_material("## 每集材料\n### 选题排期\n\n### 下一集\n其他", "选题排期") == ""
    path.write_text("---\na: b\n---\n", encoding="utf-8")
    assert frames.load_series_frame(SERIES) == ""


@pytest.mark.parametrize("name", ["../outside.md", "/tmp/outside.md", "其他.md", "系列框架/../../一勾式骨架.md", "系列框架/nested/a.md", "系列框架/a.txt"])
def test_save_rejects_unapproved_paths(name, workflows):
    with pytest.raises(ValueError):
        frames.save(Path(name), "内容")


def test_save_creates_folder_and_records_only_changed_file(workflows, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="true\n"))
    monkeypatch.setattr(frames.subprocess, "run", run)
    relative = Path(frames.FOLDER) / f"{SERIES}.md"
    frames.save(relative, WITH_MATERIAL)
    assert frames.series_frame_path(SERIES).read_text() == WITH_MATERIAL
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[1] == ["git", "-C", str(workflows), "add", "--", str(relative)]
    assert commands[2] == ["git", "-C", str(workflows), "commit", "--only", "-m", f"docs: 设置里改了{SERIES}.md", "--", str(relative)]
    run.side_effect = subprocess.CalledProcessError(1, "git")
    frames.save(relative, "写盘成功，git失败")
    assert frames.series_frame_path(SERIES).read_text() == "写盘成功，git失败"


def test_symlinks_cannot_escape_workflows(tmp_path, workflows):
    (workflows / frames.FOLDER).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        frames.save(Path(frames.FOLDER) / "outside.md", "不能写")
    with pytest.raises(ValueError):
        frames.load_series_frame("outside")
    other = workflows / "其他.md"
    other.write_text("不能覆盖", encoding="utf-8")
    (workflows / outline.FRAMEWORK_FILE).unlink()
    (workflows / outline.FRAMEWORK_FILE).symlink_to(other)
    with pytest.raises(ValueError):
        frames.save(Path(outline.FRAMEWORK_FILE), "不能写")
    assert other.read_text() == "不能覆盖"
    for folder in ("../outside", "/absolute", "a/b", "a\\b", "..", ""):
        with pytest.raises(ValueError):
            frames.series_frame_path(folder)


def test_coupon_receives_both_layers(tmp_path, workflows):
    write = Mock(return_value=_good())
    coupon.write_coupon(TOPIC, skeleton=GOOD, vault_raw=str(tmp_path), drafts_dir=tmp_path,
                        series_frame=FRAME, episode_material=MATERIAL, write_fn=write)
    prompt = write.call_args.args[0]
    assert FRAME in prompt and MATERIAL in prompt and "第二层，和上面冲突时以这里为准" in prompt


def test_titles_receive_weekly_adjustments():
    prompt = titles.build_prompt(TOPIC, framework="标题规则", transcript="原话", skeleton="骨架",
                                 adjustments=["每条封面不超过12个字", "标题先说结果"])
    assert "最近一次每周复盘定下的调整（只管标题和封面）" in prompt
    assert "每条封面不超过12个字" in prompt and "标题先说结果" in prompt


def _make_series(client):
    root = Path(client.app.state.store.settings()["obsidian_vault"]) / "003_原始输出"
    root.mkdir(parents=True, exist_ok=True)
    response = client.post("/api/series", json={"name": "一人自媒体究竟怎么做", "titles": "1. 选题排期\n2. 下一集"})
    assert response.status_code == 200, response.text
    return response.json()["series"]


def test_frames_api_lists_edits_and_preserves_raw_markdown(client):
    _make_series(client)
    data = client.get("/api/frames").json()
    assert len(data["layer_one"]) == 2
    assert data["series"][0]["folder"] == SERIES
    assert data["series"][0]["episodes"] == 2 and not data["series"][0]["has_frame"]
    query = {"kind": "series", "folder": SERIES}
    doc = client.get("/api/frames/doc", params=query).json()
    assert not doc["exists"] and f"# 系列框架：{SERIES}（第二层）" in doc["body"]
    assert not frames.series_frame_path(SERIES).exists()
    for target in (query, {"kind": "one", "key": "skeleton"}, {"kind": "one", "key": "coupon"}):
        text = "---\nfoo: bar\n---\n\n" + WITH_MATERIAL
        assert client.put("/api/frames/doc", json={**target, "text": text}).status_code == 200
        assert client.get("/api/frames/doc", params=target).json()["body"] == text
        empty = client.put("/api/frames/doc", json={**target, "text": " \n"})
        assert empty.status_code == 400 and "内容是空的" in empty.text
    assert client.get("/api/frames").json()["series"][0]["has_frame"]
    for target in ({"kind": "series", "folder": "../bad"}, {"kind": "series", "folder": "不存在"}, {"kind": "one", "key": "../bad"}):
        assert client.put("/api/frames/doc", json={**target, "text": "x"}).status_code == 400
        assert client.get("/api/frames/doc", params=target).status_code == 400


def _wait_topic(client, tid):
    for _ in range(200):
        topic = client.app.state.store.topic(tid)
        if topic["outline_state"] != "running":
            return topic
        time.sleep(0.05)
    pytest.fail("骨架线程没有结束")


def test_web_uses_speak_series_and_passes_material_to_coupon(client, monkeypatch):
    _make_series(client)
    board = client.get("/api/board").json()
    tid = board["series"][0]["episodes"][0]["topic_id"]
    query = {"kind": "series", "folder": SERIES}
    client.put("/api/frames/doc", json={**query, "text": FRAME})
    client.post(f"/api/topics/{tid}/outline")
    assert "还没有材料" in _wait_topic(client, tid)["outline_error"]
    client.put("/api/frames/doc", json={**query, "text": WITH_MATERIAL})
    (outline.workflows_dir() / coupon.FRAMEWORK_FILE).write_text("# 通用付息稿", encoding="utf-8")
    called = Mock(return_value={})
    monkeypatch.setattr(coupon, "write_coupon", called)
    client.post(f"/api/topics/{tid}/outline")
    topic = _wait_topic(client, tid)
    assert topic["outline_state"] is None, topic["outline_error"]
    for _ in range(200):  # 付息稿在骨架写完后另起线程：等它真的被调到，不看 running（线程可能还没开始）
        if called.called:
            break
        time.sleep(0.05)
    assert called.call_args.kwargs["series_frame"] == WITH_MATERIAL.strip()
    assert called.call_args.kwargs["episode_material"] == MATERIAL
    assert outline.read_outline(topic)["frames"] == ["骨架", SERIES]
