from __future__ import annotations

from pathlib import Path

import pytest

from content_studio import writer
from content_studio.judge import JudgeLoginError
from content_studio.store import StudioStore

BODY = "# 标题\n\n" + "正文内容。" * 60


def _topic(**kw):
    base = {"id": 7, "title": "选题", "memo": None, "note_paths": []}
    base.update(kw)
    return base


def test_extract_article_requires_block_title_and_no_foreign_signature() -> None:
    assert writer.extract_article(f"前言\n<<<ARTICLE>>>\n{BODY}\n<<<END>>>").startswith("# 标题")
    with pytest.raises(writer.WriterError, match="格式"):
        writer.extract_article(BODY)
    with pytest.raises(writer.WriterError, match="太短"):
        writer.extract_article("<<<ARTICLE>>>\n# 短\n<<<END>>>")
    with pytest.raises(writer.WriterError, match="署名"):
        writer.extract_article(f"<<<ARTICLE>>>\n{BODY}\n> / 作者：卡兹克\n<<<END>>>")


def test_retry_passes_the_error_back_then_saves_draft(tmp_path: Path) -> None:
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return "没按格式" if len(prompts) == 1 else f"<<<ARTICLE>>>\n{BODY}\n<<<END>>>"

    result = writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path / "d", write_fn=fake)
    assert "上一次输出有问题" in prompts[1]
    assert Path(result["article_path"]).read_text(encoding="utf-8").startswith("# 标题")
    assert writer.read_draft({"article_path": result["article_path"]})["skill"] == writer.ORIGINAL_WORDS


def test_gives_up_after_attempts_and_login_errors_are_not_retried(tmp_path: Path) -> None:
    with pytest.raises(writer.WriterError, match="连续 2 次"):
        writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=lambda p: "x")
    calls = []

    def logged_out(prompt):
        calls.append(1)
        raise JudgeLoginError("登录已过期")

    with pytest.raises(JudgeLoginError):
        writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path, write_fn=logged_out)
    assert len(calls) == 1


def test_prompt_uses_sources_and_keeps_park_as_author(tmp_path: Path) -> None:
    (tmp_path / "002_clippings").mkdir()
    (tmp_path / "002_clippings" / "a.md").write_text("---\ntitle: 剪藏\nsource: https://x.com/1\n---\n别人的观点", encoding="utf-8")
    sources = writer.gather_sources(str(tmp_path), ["002_clippings/a.md", "_secrets/x.md"])
    prompt = writer.build_prompt(_topic(memo="写给小白"), sources)
    assert "不要用任何写作 skill" in prompt and "不改词" in prompt and "别人的观点" in prompt and "写给小白" in prompt
    assert "khazix-writer" not in prompt
    assert len(sources) == 1


def test_a_chosen_writing_skill_fills_the_slot(tmp_path: Path) -> None:
    """10/4 作者：他自己不用写作 skill，但客户想用可以在设置里选，作者仍是 作者。"""
    prompt = writer.build_prompt(_topic(), [], skill="khazix-writer")
    assert "请使用 khazix-writer skill" in prompt and "作者是你" in prompt and "不改词" not in prompt
    result = writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path / "d", skill="khazix-writer",
                                  write_fn=lambda p: f"<<<ARTICLE>>>\n{BODY}\n<<<END>>>", transcript="完全不相干的原话。" * 30)
    assert result["skill"] == "khazix-writer"  # 选了 skill 就不按原话核对


def test_original_words_mode_rejects_a_rewrite(tmp_path: Path) -> None:
    """只整理原话：删口语、调顺序可以；换了词、改写成别的话就退回重写。"""
    said = "工具一直在变。如果你认同这个判断，那么所有人都会失业。就是说，然后，所有人都会去做自媒体。"
    kept = "# 标题\n\n如果你认同这个判断，那么所有人都会失业。工具一直在变。所有人都会去做自媒体。"
    assert writer.fidelity(kept, said) > 0.8
    rewritten = "# 标题\n\n时代浪潮不可逆转，倘若接受这一前提，白领岗位终将消失，人们纷纷转向内容创作。"
    assert writer.fidelity(rewritten, said) < writer.MIN_FIDELITY
    outputs = iter([f"<<<ARTICLE>>>\n{rewritten * 10}\n<<<END>>>", f"<<<ARTICLE>>>\n{kept * 6}\n<<<END>>>"])
    prompts = []
    result = writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path / "d", transcript=said,
                                  write_fn=lambda p: (prompts.append(p), next(outputs))[1])
    assert "改动太多" in prompts[1] and result["skill"] == writer.ORIGINAL_WORDS


def test_cli_write_reports_missing_command() -> None:
    with pytest.raises(writer.WriterError, match="找不到"):
        writer.cli_write("x", command="definitely-not-a-command-xyz")


def test_interrupted_writes_are_recovered(tmp_path: Path) -> None:
    store = StudioStore(tmp_path / "s.sqlite3")
    topic = store.create_topic("t")
    store.update_topic(topic["id"], write_state="running")
    assert store.recover_interrupted_writes() == 1
    assert store.topic(topic["id"])["write_state"] == "failed"
    store.close()


def test_video_transcript_leads_the_material(tmp_path: Path) -> None:
    """视频拍完的选题：原话排第一，提示词说以原话为准。"""
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return f"<<<ARTICLE>>>\n{BODY}\n<<<END>>>"

    result = writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path / "d", write_fn=fake,
                                  transcript="我今天才想明白他为什么开源这个skill。正文内容。正文内容。")
    assert "### 素材 1：视频原话（转写）" in prompts[0] and "以「视频原话」为准" in prompts[0]
    assert result["sources"][0]["title"] == writer.TRANSCRIPT_TITLE
    writer.write_article(_topic(), vault_raw=str(tmp_path), drafts_dir=tmp_path / "d", write_fn=fake)
    assert "视频原话" not in prompts[1]


def test_prompt_forbids_crosspost_intro_and_hides_backfill_memo() -> None:
    """作者 9/27：文字版第一句「这是我之前抖音的视频，整理成文字」对其他平台有引流嫌疑。"""
    topic = {**_topic(), "memo": "补发：抖音发过的旧视频\n重点讲加息的逻辑"}
    prompt = writer.build_prompt(topic, [])
    assert "补发：抖音发过的旧视频" not in prompt and "重点讲加息的逻辑" in prompt
    assert "不要写「之前在抖音发过」" in prompt


def test_rewrite_carries_the_instruction_and_the_previous_version(tmp_path: Path) -> None:
    """9/29 作者：「重写就完全不一样了，我要知道它怎么会不一样。」重写带上他这次的要求和上一版，只改他说的；上一版另存。"""
    folder = tmp_path / "topic-7"
    folder.mkdir()
    (folder / "article.md").write_text("# 上一版\n\n旧的正文。", encoding="utf-8")
    seen = {}

    def fake(prompt: str) -> str:
        seen["prompt"] = prompt
        return "<<<ARTICLE>>>\n# 新一版\n\n" + "新的正文。" * 80 + "\n<<<END>>>"

    result = writer.write_article({"id": 7, "title": "t", "note_paths": [], "memo": ""}, vault_raw=str(tmp_path),
                                  drafts_dir=tmp_path, write_fn=fake, instruction="开头直接给结论")
    assert "开头直接给结论" in seen["prompt"] and "旧的正文。" in seen["prompt"] and "只按这句话改" in seen["prompt"]
    assert (folder / "article.prev.md").read_text(encoding="utf-8").startswith("# 上一版")
    assert result["instruction"] == "开头直接给结论"
    assert "这次是重写" not in writer.build_prompt({"id": 1, "title": "t", "memo": ""}, [])


CODEX_HEADER = ("OpenAI Codex v0.159.3\n--------\nworkdir: /Users/me/work/content-studio\nmodel: gpt-6.1-sol\nprovider: openai\n"
                "approval: never\nsandbox: read-only\nreasoning effort: high\nreasoning summaries: none\nsession id: 01a1\n--------\nuser\n")


def test_cli_write_failure_shows_the_real_reason_not_the_codex_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """10/13 作者：「没做成：写作命令失败（退出码 1）：OpenAI Codex v0.159.3 …session」——只留前 200 字，全是抬头。"""
    import subprocess

    from content_studio import llm

    stderr = CODEX_HEADER + "整段提问" * 200 + "\nERROR: stream disconnected before completion: error sending request\n"
    monkeypatch.setattr(llm, "run", lambda argv, input="", timeout=0: subprocess.CompletedProcess(argv, 1, "", stderr))
    with pytest.raises(writer.WriterError) as exc:
        writer.cli_write("x", command="claude -p")
    assert "stream disconnected" in str(exc.value) and "OpenAI Codex v0.159.3" not in str(exc.value)

    # 没有 ERROR 那一行：取结尾，不取抬头
    assert llm.error_detail(CODEX_HEADER + "提问\nNo space left on device (os error 28)\n") == "提问\nNo space left on device (os error 28)"
    assert llm.error_detail(CODEX_HEADER + "提问" * 300).endswith("提问") and "OpenAI Codex" not in llm.error_detail(CODEX_HEADER + "提问" * 300)
    assert llm.error_detail("", "") == "没有输出"
