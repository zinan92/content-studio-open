from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.extras.team import anna


def test_parse_reply_splits_actions_from_prose() -> None:
    text = "这条素材太薄。\n\n[动作] 存进备注：补一张收益截图\n[动作] 重写提纲\n[动作] 拿来做：\n[动作] 重写提纲\n[动作] 发布"
    parsed = anna.parse_reply(text)
    assert parsed["text"] == "这条素材太薄。\n\n[动作] 发布"
    assert parsed["actions"] == [
        {"kind": "memo", "label": "存进备注", "arg": "补一张收益截图"},
        {"kind": "outline", "label": "重写提纲", "arg": ""},
    ]


def test_soul_reads_role_knowledge_and_skill(tmp_path: Path) -> None:
    role = tmp_path / "content_editor Anna.md"
    role.write_text("---\nx: 1\n---\n# Anna\n第一目标：让对的人看得更久。", encoding="utf-8")
    know = tmp_path / "content_editor Anna" / "knowledge"
    know.mkdir(parents=True)
    (know / "定位.md").write_text("吸引想跟你学的人", encoding="utf-8")
    (know / "课件.pdf").write_bytes(b"%PDF")
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: qa\n---\n三点评分", encoding="utf-8")
    soul = anna.load_soul(role, skill)
    assert soul["text"].startswith("# Anna") and "吸引想跟你学的人" in soul["text"] and "三点评分" in soul["text"]
    assert [Path(p).name for p in soul["sources"]] == ["content_editor Anna.md", "定位.md", "SKILL.md"]
    assert "x: 1" not in soul["text"]
    fallback = anna.load_soul(tmp_path / "missing.md", tmp_path / "missing-skill.md")
    assert "流量 CEO" in fallback["text"] and "让他们看得更久" in fallback["text"] and fallback["sources"] == []


def test_workbench_rules_forbid_laundering_qa_caution_into_a_confident_quote() -> None:
    # Regression: Anna once turned a QA "不要讲过头" caution (an unverified 1840 historical
    # detail) into a ready-to-read direct-quote suggestion, with the warning dropped entirely.
    system = anna.system_prompt("# Anna")
    assert "不要讲过头" in system and "不能把这些细节讲成确定的事实或可以直接念的引语" in system


def test_run_turn_composes_context_and_resumes_session() -> None:
    seen = []

    def fake(system: str, user: str, session_id: str | None) -> dict:
        seen.append((system, user, session_id))
        return {"text": "先补交付。\n[动作] 按三点评分", "session_id": "s-2"}

    reply = anna.run_turn(scope="work:3", scope_label="这条视频", context="## 拍摄提纲\n- 开头", message="能拍吗", session_id="s-1", turn_fn=fake, soul={"text": "# Anna", "sources": []})
    system, user, sid = seen[0]
    assert system.startswith("# Anna") and "[动作] 存进备注" in system and sid == "s-1"
    assert user.startswith('<工作台 页面="这条视频">') and "## 拍摄提纲" in user and user.endswith("作者：能拍吗")
    assert reply["text"] == "先补交付。" and reply["actions"][0]["kind"] == "qa" and reply["session_id"] == "s-2"


def test_context_is_truncated_and_cli_errors_are_explained(tmp_path: Path) -> None:
    long = anna.compose_user_message("x" * (anna.MAX_CONTEXT_CHARS + 10), "hi", scope_label="进项")
    assert "已截断" in long and len(long) < anna.MAX_CONTEXT_CHARS + 200
    with pytest.raises(anna.AnnaError, match="找不到本机的 (Claude|Codex) 命令"):
        anna.cli_turn("s", "u", None, command=str(tmp_path / "no-such-binary"))
    script = tmp_path / "fake.sh"
    script.write_text('#!/bin/sh\necho \'{"result": "好的", "session_id": "abc"}\'\n', encoding="utf-8")
    script.chmod(0o755)
    assert anna.cli_turn("s", "u", None, command=str(script)) == {"text": "好的", "session_id": "abc"}
    login = tmp_path / "login.sh"
    login.write_text('#!/bin/sh\necho "please log in" >&2\nexit 1\n', encoding="utf-8")
    login.chmod(0o755)
    with pytest.raises(anna.AnnaLoginError):
        anna.cli_turn("s", "u", None, command=str(login))


def test_soul_puts_parks_principles_before_the_rubric(tmp_path) -> None:
    from content_studio.extras.team import anna

    role = tmp_path / "Anna.md"
    role.write_text("# Anna\n让对的人看得更久。", encoding="utf-8")
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "SKILL.md").write_text("# 三点评分\n痛点具象度。", encoding="utf-8")
    (skills / "principles.md").write_text("# 原则\n抖音是情绪菜市场。", encoding="utf-8")

    soul = anna.load_soul(role, skills / "SKILL.md")
    assert soul["text"].index("抖音是情绪菜市场") < soul["text"].index("痛点具象度")
    assert "以这里为准" in soul["text"]
    assert [p.split("/")[-1] for p in soul["sources"]] == ["Anna.md", "principles.md", "SKILL.md"]


def test_anna_can_look_things_up_in_the_vault_but_not_the_secrets(tmp_path: Path) -> None:
    """10/1 作者：老师对标、日报、原始输出、clippings、咨询都能当她的上下文，但不是每轮全塞——提到了她自己去找。"""
    vault = tmp_path / "vault"
    for d in ("002_对标内容", "010_咨询", "_secrets", ".obsidian"):
        (vault / d).mkdir(parents=True)
    (vault / "010_咨询" / "诊断流程.md").write_text("x", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    args = anna.reach_args(vault, {"拆解报告": reports, "没有的": tmp_path / "nope"})
    assert args[:4] == ["--add-dir", str(vault), "--add-dir", str(reports)] and str(tmp_path / "nope") not in args
    assert f"Read(/{(vault / '_secrets').resolve()}/**)" in args  # Read 规则同时管 Grep / Glob
    note = anna.reach_note(vault, {"拆解报告": reports})
    assert "010_咨询 （1 项）" in note and "_secrets （" not in note and ".obsidian" not in note.split("\n\n")[-1] and "拆解报告" in note
    assert "Read / Glob / Grep" in note and "不要整个文件夹地读" in note
    assert anna.reach_note(None) == "" and anna.reach_args(None) == []
    # 命令本身：只读工具开着，能改东西的都关着
    assert '--allowedTools "Read Glob Grep"' in anna.DEFAULT_ANNA_COMMAND and "Edit,Write" in anna.DEFAULT_ANNA_COMMAND and "Bash" in anna.DEFAULT_ANNA_COMMAND


def test_raw_output_draft_becomes_a_button_and_is_saved_without_overwriting(tmp_path: Path) -> None:
    text = "按你的诊断流程整理了一版。\n\n<原始输出>\n# 我给客户的服务流程\n\n## Section 1：原始输出\n我先跟你聊一个小时。\n\n## Section 2：处理过的输出\n三步走。\n</原始输出>\n\n[动作] 写进原始输出：自媒体/我给客户的服务流程\n[动作] 写进原始输出："
    parsed = anna.parse_reply(text)
    assert "<原始输出>" not in parsed["text"] and "## Section 1：原始输出" in parsed["text"]
    assert [(a["kind"], a["arg"]) for a in parsed["actions"]] == [("raw", "自媒体/我给客户的服务流程")]
    assert parsed["actions"][0]["body"].startswith("# 我给客户的服务流程") and "三步走" in parsed["actions"][0]["body"]
    assert anna.parse_reply("[动作] 写进原始输出：自媒体/空的")["actions"] == []  # 没给整篇：不给按钮

    vault = tmp_path / "vault"
    (vault / anna.RAW_FOLDER / "自媒体").mkdir(parents=True)
    first = anna.save_raw(vault, "自媒体/我给客户的服务流程", "# 正文")
    assert first == vault / anna.RAW_FOLDER / "自媒体" / "我给客户的服务流程.md" and first.read_text(encoding="utf-8") == "# 正文\n"
    assert anna.save_raw(vault, "自媒体/我给客户的服务流程", "# 第二版").name == "我给客户的服务流程-2.md"  # 不覆盖
    assert anna.save_raw(vault, "没有这个目录/一篇", "x").parent == vault / anna.RAW_FOLDER  # 不存在的子目录：放根下
    assert anna.save_raw(vault, "../../etc/passwd", "x").parent == vault / anna.RAW_FOLDER  # 跳不出去
    with pytest.raises(anna.AnnaError):
        anna.save_raw(vault, "自媒体/空", "  ")


def test_she_sees_what_is_on_his_screen_when_he_writes() -> None:
    """10/5：后台给她的资料是一条条写死的，页面加了东西她看不到。他发消息时屏幕上那一页的字一起给她。"""
    seen = []
    anna.run_turn(scope="board", scope_label="加工中", context="## 看板\n- a", message="上面那个数是什么意思", session_id=None,
                  turn_fn=lambda s, u, sid: seen.append(u) or {"text": "ok", "session_id": None}, soul={"text": "# Anna", "sources": []},
                  screen="全网粉丝 7,586\n\n\n\n预期月底 8,221")
    user = seen[0]
    assert "<他屏幕上这一页>\n全网粉丝 7,586\n\n预期月底 8,221\n</他屏幕上这一页>" in user
    assert user.index("</工作台>") < user.index("<他屏幕上这一页>") < user.index("作者：")
    assert "<他屏幕上这一页>" not in anna.compose_user_message("x", "hi", scope_label="进项")
    assert len(anna.screen_block("字" * 20000)) < anna.SCREEN_MAX + 100
    assert "<他屏幕上这一页>" in anna.WORKBENCH_RULES
