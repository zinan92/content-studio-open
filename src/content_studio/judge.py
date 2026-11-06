from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from typing import Callable

from . import llm


JudgeFn = Callable[[str], dict]

# The default judge shells out to the locally authenticated Claude Code CLI with
# every tool disabled, so the model only reads the prompt and returns JSON.
DEFAULT_LLM_COMMAND = (
    "claude -p --model sonnet --output-format text "
    "--disallowedTools Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit"
)
LLM_COMMAND_ENV = "CONTENT_STUDIO_LLM_CMD"


class JudgeError(RuntimeError):
    """The structure judge did not return a usable JSON object."""


class JudgeLoginError(JudgeError):
    """The local LLM CLI is logged out; retrying will not help until someone logs in."""


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in model output, tolerating code fences."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise JudgeError("model output contains no JSON object")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JudgeError(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise JudgeError("model output JSON must be an object")
    return value


def cli_judge(prompt: str, *, command: str | None = None, timeout: float = 600.0) -> dict:
    """Send a prompt to a local LLM CLI on stdin and parse its JSON answer."""
    argv = shlex.split(command or os.environ.get(LLM_COMMAND_ENV) or DEFAULT_LLM_COMMAND)
    try:
        completed = llm.run(argv, input=prompt, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise JudgeError(f"LLM command failed to run: {exc}") from exc
    if completed.returncode != 0:
        detail = f"{completed.stderr}\n{completed.stdout}"
        if re.search(r"authenticat|log ?in|oauth", detail, re.IGNORECASE):
            raise JudgeLoginError(f"本机 {llm.label()} 命令行没登录或登录过期：{llm.login_hint()}，然后回到队列点重试")
        detail = (completed.stderr.strip() or completed.stdout.strip())[-300:] or "没有输出"
        if re.search(r"usage limit|rate limit|limit reached|quota", detail, re.IGNORECASE):
            raise JudgeLoginError(f"本机 {llm.label()} 额度用完或被限流，稍后点重试：{detail[:120]}")
        raise JudgeError(f"LLM command exited with {completed.returncode}: {detail}")
    return parse_json_object(completed.stdout)
