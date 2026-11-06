"""写作规则路由只使用临时 skill，不读取本机安装。"""
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from content_studio import coupon, frames, outline, titles, writing_rules
from content_studio.extras.xline import x_long, x_qa, x_suggest
from content_studio.writer import WriterError
from test_web import client  # noqa: F401


@pytest.fixture
def skill(tmp_path, monkeypatch):
    root = tmp_path / "park-writing"
    refs = root / "references"
    refs.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: park-writing\n---\n技能正文\n")
    for name, text in {"骨架.md": "骨架句子", "开头.md": "开头句子\n\n## 标题\n标题标准",
                       "密度.md": "密度句子", "配图.md": "配图句子", "QA.md": "检查句子", "X短帖.md": "短帖句子"}.items():
        (refs / name).write_text("---\nmeta: hidden\n---\n" + text)
    monkeypatch.setenv(writing_rules.SKILL_ENV, str(root))
    return root


def test_off_preserves_legacy_path(monkeypatch):
    monkeypatch.setenv(writing_rules.SKILL_ENV, "off")
    assert writing_rules.current_path("付息稿.md") == outline.workflows_dir() / "付息稿.md"


def test_incomplete_install_is_not_used(tmp_path, monkeypatch):
    (tmp_path / "SKILL.md").write_text("正文")
    monkeypatch.setenv(writing_rules.SKILL_ENV, str(tmp_path))
    assert writing_rules.skill_dir() is None
    (tmp_path / "references").mkdir()
    assert writing_rules.skill_dir() == tmp_path
    (tmp_path / "SKILL.md").unlink()
    assert writing_rules.skill_dir() is None


def test_discovery_order_and_explicit_override(tmp_path, monkeypatch):
    roots = [tmp_path / str(i) for i in range(3)]
    monkeypatch.setattr(writing_rules, "SKILL_DIRS", tuple(map(str, roots)))
    monkeypatch.delenv(writing_rules.SKILL_ENV)
    for root in roots[1:]:
        installed = root / writing_rules.SKILL
        (installed / "references").mkdir(parents=True)
        (installed / "SKILL.md").write_text("正文")
    assert writing_rules.skill_dir() == roots[1] / writing_rules.SKILL
    monkeypatch.setenv(writing_rules.SKILL_ENV, str(roots[0]))
    assert writing_rules.skill_dir() is None


def test_frameworks_and_explicit_root(skill, tmp_path):
    assert outline.load_framework() == "骨架句子\n\n开头句子"
    assert coupon.load_framework() == "密度句子"
    assert "标题标准" in titles.load_framework()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for module in (outline, coupon, titles):
        (legacy / module.FRAMEWORK_FILE).write_text("---\nmeta: old\n---\n旧规则\n")
        assert module.load_framework(legacy) == "旧规则"
    assert len(frames.layer_one_files(legacy)) == 2
    assert writing_rules.current_path("系列框架/a.md") == outline.workflows_dir() / "系列框架/a.md"


@pytest.mark.parametrize("name", ["骨架.md", "开头.md"])
@pytest.mark.parametrize("text", [None, "", "---\nmeta: only\n---\n"])
def test_outline_missing_or_empty_raises_with_path(skill, name, text):
    path = skill / "references" / name
    if text is None:
        path.unlink()
    else:
        path.write_text(text)
    with pytest.raises(WriterError, match=str(path)):
        outline.load_framework()


def test_qa_routes_to_skill(skill):
    path = skill / "references/QA.md"
    rules = x_qa.load_rules()
    assert rules["path"] == str(path)
    assert x_qa.save_path() == path
    assert rules["bundled"] is False
    assert rules["text"] == "检查句子"


def test_existing_short_style_is_not_generated(skill, tmp_path):
    path = skill / "references/X短帖.md"
    original = path.read_bytes()
    write = Mock(side_effect=AssertionError("不应生成"))
    assert x_suggest.style_path() == path
    assert x_suggest.ensure_style(tmp_path / "absent-vault", write) == (path, original.decode(), False)
    assert path.read_bytes() == original
    write.assert_not_called()


def test_frame_paths_save_and_whitelist(skill, monkeypatch):
    refs = skill / "references"
    run = Mock(return_value=subprocess.CompletedProcess([], 1, stdout=""))
    monkeypatch.setattr(frames.subprocess, "run", run)
    entries = frames.layer_one_files()
    assert [(f["key"], f["label"], f["file"]) for f in entries] == [
        ("opening", "开头", "开头.md"), ("skeleton", "骨架", "骨架.md"), ("coupon", "密度", "密度.md")]
    assert all(Path(f["path"]).parent == refs and f["exists"] for f in entries)
    frames.save(Path("密度.md"), "新内容", root=refs)
    assert (refs / "密度.md").read_text() == "新内容"
    assert run.call_args.args[0][2] == str(refs)
    for name in ("../x.md", "QA.md", "nested/密度.md"):
        with pytest.raises(ValueError):
            frames.save(Path(name), "禁止", root=refs)


def test_skill_body_without_frontmatter(skill):
    assert x_long.skill_text() == "技能正文"


def test_frames_api_writes_skill(client, skill, monkeypatch):
    monkeypatch.setattr(frames.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 1, stdout="")))
    response = client.put("/api/frames/doc", json={"kind": "one", "key": "coupon", "text": "接口新内容"})
    assert response.status_code == 200, response.text
    assert (skill / "references/密度.md").read_text() == "接口新内容"
    data = client.get("/api/frames").json()
    assert len(data["layer_one"]) == 3
    assert all(Path(f["path"]).expanduser().parent == skill / "references" for f in data["layer_one"])
    response = client.get("/api/frames/doc", params={"kind": "one", "key": "coupon"})
    assert response.json()["body"] == "接口新内容"


def test_qa_api_cannot_reset_skill(client, skill):
    response = client.get("/api/xline/qa-rules")
    assert response.status_code == 200, response.text
    assert response.json()["resettable"] is False
    original = (skill / "references/QA.md").read_bytes()
    assert client.delete("/api/xline/qa-rules").status_code == 400
    assert (skill / "references/QA.md").read_bytes() == original


def test_profile_maps_skill_without_overriding_env(client, skill, monkeypatch):
    from content_studio import web

    monkeypatch.delenv(writing_rules.SKILL_ENV)
    web._apply_profile(client.app.state.store, {"anna": {"writing_skill": str(skill)}})
    assert writing_rules.skill_dir() == skill
    monkeypatch.setenv(writing_rules.SKILL_ENV, "off")
    web._apply_profile(client.app.state.store, {"anna": {"writing_skill": str(skill)}})
    assert writing_rules.skill_dir() is None
