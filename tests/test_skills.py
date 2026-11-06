from __future__ import annotations

import json
from pathlib import Path

from content_studio.skills import REGISTRY_PATH, load_skills

REPO = Path(__file__).resolve().parents[1]


def test_registry_is_complete_and_honest() -> None:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    names = [s["name"] for s in data["skills"]]
    assert len(names) == len(set(names))
    for skill in data["skills"]:
        assert skill["title"] and skill["use"] and skill["invoke"]
        if skill["repo"]:
            assert skill["repo"].startswith("https://github.com/")
        if skill["own"]:
            assert skill["author"] == "作者" and "zinan92" in skill["repo"]
    assert {"khazix-writer", "park-video-v2", "dbs-content", "video-shotcraft"} <= set(names)


def test_local_detection_reads_folded_description(tmp_path: Path) -> None:
    skill = tmp_path / "khazix-writer"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: khazix-writer\ndescription: |\n  公众号长文写作\n  第二行\n---\n正文", encoding="utf-8")
    other = tmp_path / "dbs-content"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: dbs-content\ndescription: 诊断内容\n---\n", encoding="utf-8")
    result = load_skills(roots=(tmp_path,))
    by_name = {s["name"]: s for s in result["skills"]}
    assert by_name["khazix-writer"]["installed"] and by_name["khazix-writer"]["description"] == "公众号长文写作 第二行"
    assert by_name["dbs-content"]["description"] == "诊断内容"
    assert by_name["video-shotcraft"]["installed"] is False
    assert by_name["daily-news-caster"]["source_known"] is False


def test_no_third_party_skill_files_are_vendored() -> None:
    ignored = {".git", ".venv", "node_modules"}
    found = [p for p in REPO.rglob("SKILL.md") if not ignored & set(p.parts)]
    assert found == []


def test_edits_go_to_the_user_file_and_the_seed_stays_untouched(tmp_path: Path) -> None:
    import pytest
    from content_studio import skills

    user = tmp_path / "skills.json"
    seed_before = REGISTRY_PATH.read_text(encoding="utf-8")
    assert skills.load_skills(user=user, roots=(tmp_path,))["editable"] is True
    skills.upsert({"name": "my-frame", "title": "我的框架", "stage": "plan", "use": "写提纲用"}, user=user)
    assert REGISTRY_PATH.read_text(encoding="utf-8") == seed_before
    names = [s["name"] for s in skills.load_skills(user=user, roots=(tmp_path,))["skills"]]
    assert "my-frame" in names and "khazix-writer" in names  # the seed was copied, then added to
    skills.upsert({"name": "my-frame2", "title": "改名", "stage": "write", "use": "x"}, user=user, previous="my-frame")
    names = [s["name"] for s in skills.load_skills(user=user, roots=(tmp_path,))["skills"]]
    assert "my-frame" not in names and "my-frame2" in names
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "bad name!", "stage": "plan", "use": "x"}, user=user)
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "x", "stage": "nope", "use": "x"}, user=user)
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "x", "stage": "plan", "use": "x", "repo": "javascript:alert(1)"}, user=user)
    with pytest.raises(skills.SkillsError):
        skills.upsert({"name": "khazix-writer", "stage": "plan", "use": "x"}, user=user, previous="my-frame2")
    assert skills.remove("my-frame2", user=user) and not skills.remove("my-frame2", user=user)


def test_doc_reads_only_listed_markdown_in_skill_folders_or_annas_folder(tmp_path: Path, monkeypatch) -> None:
    import pytest
    from content_studio import skills

    monkeypatch.setenv("HOME", str(tmp_path))
    role_dir = tmp_path / "vault" / "001_role" / "content_editor Anna"
    (role_dir / "workflows").mkdir(parents=True)
    (role_dir / "workflows" / "frame.md").write_text("---\nname: f\n---\n# 框架\n正文", encoding="utf-8")
    monkeypatch.setenv(skills.ANNA_ROLE_ENV, str(role_dir.with_suffix(".md")))
    (tmp_path / "vault" / "_secrets").mkdir()
    (tmp_path / "vault" / "_secrets" / "k.md").write_text("不该读到", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "n.md").write_text("家目录别处也不读", encoding="utf-8")
    user = tmp_path / "skills.json"
    skills.upsert({"name": "frame", "stage": "plan", "use": "x", "path": "~/vault/001_role/content_editor Anna/workflows/frame.md"}, user=user)
    skills.upsert({"name": "secret", "stage": "plan", "use": "x", "path": "~/vault/_secrets/k.md"}, user=user)
    skills.upsert({"name": "elsewhere", "stage": "plan", "use": "x", "path": "~/notes/n.md"}, user=user)
    assert "正文" in skills.read_doc("frame", user=user, roots=(tmp_path / "skills",))["body"]
    for name in ("secret", "elsewhere", "not-listed"):
        with pytest.raises(skills.SkillsError):
            skills.read_doc(name, user=user, roots=(tmp_path / "skills",))


def _flow_registry(tmp_path: Path) -> tuple[list[dict], list[dict]]:
    from content_studio import skills

    user = tmp_path / "skills.json"
    skills.upsert({"name": "my-skeleton", "stage": "plan", "use": "x", "path": "~/frames/一勾式骨架.md"}, user=user)
    data = skills.load_skills(user=user, roots=(tmp_path / "none",))
    return data["skills"], data["stages"]


def test_flow_wiring_comes_from_each_modules_own_constants() -> None:
    from content_studio import coupon, gzh_layout, illustrate, koubo, outline, skills, titles
    from content_studio.extras.motion import video_v2

    wired = skills.wiring()
    assert wired["outline"][0]["file"] == outline.FRAMEWORK_FILE
    assert wired["coupon"][0]["file"] == coupon.FRAMEWORK_FILE
    assert wired["titles"][0]["file"] == titles.FRAMEWORK_FILE
    assert wired["figs"][0]["dir"] == illustrate.SKILL
    assert wired["wx"][0]["dir"] == gzh_layout.SKILL_DIR.name
    assert wired["project"][0]["dir"] == wired["cover"][0]["dir"] == koubo.skill_dir().name
    assert [s["dir"] for s in wired["motion"]] == [video_v2.home().name, video_v2.SHOTCRAFT]
    steps = {s["key"] for st in skills.STAGE_FLOW for s in st["steps"]}
    assert set(wired) <= steps and "article" not in wired  # 写文章默认不用 skill
    assert skills.wiring("khazix-writer")["article"][0]["dir"] == "khazix-writer"


def test_flow_view_marks_listed_skills_in_or_out_and_adds_unlisted_wired_ones(tmp_path: Path) -> None:
    from content_studio import skills

    listed, stages = _flow_registry(tmp_path)
    view = skills.flow_view(listed, stages, drafts=tmp_path / "drafts", video_root=None)
    cards = {c["name"]: c for c in view["cards"]}
    # matched by the framework file's name, not by the name in the list
    assert cards["my-skeleton"]["in_flow"] and cards["my-skeleton"]["steps"] == ["写骨架"]
    assert cards["park-video-v2"]["steps"] == ["建项目 → 录 → 剪映", "动效", "封面"]  # 10/21：剪、动效、封面参考都在同一个 skill
    assert cards["khazix-writer"]["in_flow"] is False and cards["khazix-writer"]["was"] == "写文"
    assert cards["dbs-content"]["in_flow"] is False
    assert cards["coupon-frame"]["listed"] is False and cards["coupon-frame"]["in_flow"]
    assert not [c for c in view["cards"] if not c["listed"] and not c["in_flow"]]
    motion = next(s for st in view["flow"] for s in st["steps"] if s["key"] == "motion")
    assert motion["used"]["missing"]
    with_writer = skills.flow_view(listed, stages, writer_skill="khazix-writer", video_root=None)
    assert {c["name"]: c for c in with_writer["cards"]}["khazix-writer"]["in_flow"]


def test_usage_counts_the_last_two_weeks_and_skips_what_it_cannot_read(tmp_path: Path) -> None:
    import os
    import time

    from content_studio import skills

    now = time.time()
    drafts = tmp_path / "drafts"
    (drafts / "topic-1" / "illustrations").mkdir(parents=True)
    (drafts / "topic-1" / "illustrations" / "skeleton.md").write_text("inside a counted folder", encoding="utf-8")
    (drafts / "topic-1" / "skeleton.md").write_text("x", encoding="utf-8")
    (drafts / "topic-2").mkdir()
    old = drafts / "topic-2" / "skeleton.md"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))
    videos = tmp_path / "videos"
    (videos / "a" / "v2").mkdir(parents=True)
    (videos / "b").mkdir()
    used = skills.usage(drafts, videos, now=now)
    assert used["outline"]["count"] == 1 and used["figs"]["count"] == 1 and used["qa"]["count"] == 0
    assert used["motion"]["count"] == 1
    gone = skills.usage(tmp_path / "nope", tmp_path / "no-disk", now=now)
    assert gone["outline"]["count"] == 0 and gone["motion"]["missing"]
