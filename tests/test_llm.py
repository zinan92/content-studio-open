import json
import os
from pathlib import Path
import shlex

import pytest

from content_studio import llm

FAKE = r'''#!/bin/sh
# 假 codex：记下参数和提问，按 -o 写回答
printf '%s\n' "$@" > "$ARGS_FILE"
cat > "$PROMPT_FILE"
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out="$a"; fi
  prev="$a"
done
case "$MODE" in
  empty) exit 0 ;;
  logout) echo "ERROR: unexpected status 401 Unauthorized: Missing bearer or basic authentication in header" >&2; exit 1 ;;
esac
printf '%s' "${ANSWER:-好的}" > "$out"
echo '{"type":"thread.started","thread_id":"t-123"}'
'''


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    exe = tmp_path / "codex"
    exe.write_text(FAKE)
    exe.chmod(0o755)
    monkeypatch.setattr(llm, "codex_bin", lambda: str(exe))
    monkeypatch.setenv("ARGS_FILE", str(tmp_path / "args"))
    monkeypatch.setenv("PROMPT_FILE", str(tmp_path / "prompt"))
    monkeypatch.setenv("CONTENT_STUDIO_AI", "codex")
    monkeypatch.setattr(llm, "SKILL_ROOTS", (tmp_path / "skills",))

    def seen():
        return (tmp_path / "args").read_text().splitlines(), (tmp_path / "prompt").read_text()
    return seen


def test_read_only_command_becomes_codex_read_only_without_web(fake_codex):
    argv = shlex.split("claude -p --model sonnet --output-format text --disallowedTools Bash,Edit,Write,Read,WebSearch")
    done = llm.run(argv, input="评一下", timeout=30)
    args, prompt = fake_codex()
    assert done.returncode == 0 and done.stdout == "好的\n"
    assert args[0] == "exec" and args[-1] == "-" and "--ignore-user-config" in args and "--ephemeral" in args
    assert 'sandbox_mode="read-only"' in args and 'web_search="disabled"' in args and "model_reasoning_effort=medium" in args
    assert prompt == "评一下" and "project_doc_max_bytes=0" in args


def test_opus_with_web_tools_gets_high_effort_and_live_search(fake_codex):
    argv = shlex.split('claude -p --model opus --output-format text --allowedTools "WebSearch WebFetch" --disallowedTools "Bash Edit Write"')
    llm.run(argv, input="找证据", timeout=30)
    args, _ = fake_codex()
    assert 'web_search="live"' in args and "model_reasoning_effort=high" in args and 'sandbox_mode="read-only"' in args


def test_json_turn_carries_system_prompt_and_resumes_by_thread(fake_codex, monkeypatch):
    base = shlex.split('claude -p --model sonnet --output-format json --allowedTools "Read Glob Grep"')
    done = llm.run(base + ["--add-dir", "/vault", "--disallowedTools", "Read(//vault/_secrets/**)", "--system-prompt", "你是 Anna"], input="在吗", timeout=30)
    args, prompt = fake_codex()
    assert json.loads(done.stdout) == {"result": "好的", "session_id": "t-123", "is_error": False}
    assert prompt.startswith("<instructions>\n你是 Anna\n</instructions>") and prompt.endswith("在吗")
    assert "--json" in args and "--ephemeral" not in args and "--add-dir" not in args  # 只读不用加目录
    llm.run(base + ["--system-prompt", "你是 Anna", "--resume", "t-123"], input="接着说", timeout=30)
    args, prompt = fake_codex()
    assert args[:2] == ["exec", "resume"] and args[-2:] == ["t-123", "-"] and prompt == "接着说"


def test_empty_answer_and_logout_are_failures(fake_codex, monkeypatch):
    monkeypatch.setenv("MODE", "empty")
    done = llm.run(["claude", "-p"], input="x", timeout=30)
    assert done.returncode == 1 and "没有回话" in done.stderr
    monkeypatch.setenv("MODE", "logout")
    done = llm.run(["claude", "-p"], input="x", timeout=30)
    assert done.returncode == 1 and "authenticat" in done.stderr
    assert "codex login" in llm.login_hint() and llm.label() == "Codex"


def test_skill_named_in_prompt_points_codex_at_its_file(fake_codex, tmp_path):
    skill = tmp_path / "skills" / "gzh-design"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# gzh")
    llm.run(shlex.split('claude -p --allowedTools "Skill Read"'), input="用 gzh-design skill 排版", timeout=30)
    _, prompt = fake_codex()
    assert f"先读 {skill / 'SKILL.md'}" in prompt and prompt.endswith("用 gzh-design skill 排版")


def test_other_commands_and_claude_backend_run_as_is(tmp_path, monkeypatch):
    script = tmp_path / "fake.sh"
    script.write_text("#!/bin/sh\ncat\n")
    script.chmod(0o755)
    monkeypatch.setenv("CONTENT_STUDIO_AI", "codex")
    assert llm.run([str(script)], input="原样", timeout=30).stdout == "原样"
    monkeypatch.setenv("CONTENT_STUDIO_AI", "claude")
    assert llm.backend() == "claude" and not llm.shell_command("claude -p", ["/p"]).startswith(llm.codex_bin())
    assert llm.shell_command("claude -p", ["/p"]) == "claude -p --add-dir /p"


def test_long_task_shell_command_can_write_the_project(monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_AI", "codex")
    monkeypatch.setattr(llm, "codex_bin", lambda: "codex")
    cmd = shlex.split(llm.shell_command('claude -p --model opus --allowedTools "Skill Bash Read Write"', ["/proj"]))
    assert cmd[:2] == ["codex", "exec"] and 'sandbox_mode="workspace-write"' in cmd and cmd[cmd.index("--add-dir") + 1] == "/proj"
    assert "sandbox_workspace_write.network_access=true" in cmd


def test_review_explicitly_disables_tools_across_codex_translation(fake_codex):
    argv = shlex.split('claude -p --output-format json --allowedTools "Read Glob Grep" --tools ""')
    spec = llm.parse_claude(argv)
    assert spec['no_tools'] and not spec['allowed']
    llm.run(argv, input="只写复盘，不要调用工具", timeout=30)
    args, _ = fake_codex()
    assert "tools.disable_defaults=true" in args
    assert "include_apply_patch_tool=false" in args
    for key in ("shell_tool", "view_image", "multi_agent", "apps", "plugins", "computer_use", "browser_use"):
        assert f"features.{key}=false" in args
    assert 'web_search="disabled"' in args
