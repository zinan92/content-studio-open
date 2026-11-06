"""后台 AI 走哪个命令行：Codex（默认）还是 Claude Code。

10/6：作者 这台的 Claude 订阅访问被组织关了（`claude -p` 退出码 0、回一句「已禁用」），作者 定「换成 codex」。
各模块的命令仍写成 claude 的样子（工具白名单、--model opus/sonnet、--add-dir），这里统一翻成 `codex exec`：

- 能不能动手：白名单里有 Write / Edit / Bash → workspace-write（项目目录可写、可联网），否则 read-only（只读，整盘可读）
- 能不能上网：白名单里有 WebSearch / WebFetch → 开 live 网页搜索，否则关
- opus → 推理强度 high，sonnet → medium；模型统一用 codex.model
- --system-prompt 拼到提问前面；--resume 换成 `codex exec resume <thread_id>`；--output-format json 包成 claude 的 {"result","session_id"}
- 提问里写了「xx skill」、本机有这个 skill 的，补一句 SKILL.md 在哪（Codex 没有 Skill 工具，自己去读）
- --ignore-user-config：不加载本机 ~/.codex/config.toml（作者 的 hooks、通知、插件），登录照常；也不读 AGENTS.md
- 回答从 -o 文件取；退出码 0 但没回话按失败算

只翻真正的 `claude` 命令：测试里的假命令、显式配置的别的命令原样跑。
已知差别：Codex 只读沙盒能读整个硬盘，Anna 的 vault 拒读目录（_secrets、_contact）在 Codex 下不再被强制。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

from . import conf

WRITE_TOOLS = {"Write", "Edit", "Bash", "NotebookEdit"}
WEB_TOOLS = {"WebSearch", "WebFetch"}
SKILL_ROOTS = (Path("~/.agents/skills"), Path("~/.claude/skills"), Path("~/.codex/skills"))
SKILL_MENTION = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]{2,})\s*skill", re.IGNORECASE)


def backend() -> str:
    return "claude" if conf.value("ai.backend").strip().lower() == "claude" else "codex"


def label() -> str:
    return "Claude" if backend() == "claude" else "Codex"


def login_hint() -> str:
    return "在终端运行 claude 并按提示重新登录" if backend() == "claude" else "在终端运行 codex login 重新登录"


def error_detail(stderr: str, stdout: str = "", limit: int = 300) -> str:
    """命令失败时给 作者 看的那句原因。Codex 的 stderr 开头是固定抬头（版本、模型、沙盒、session），接着是整段提问，
    真正的原因在最后——10/13 写作只留前 200 字，正好全是抬头，原因被截掉了。先找 ERROR 那几行，没有就取结尾。"""
    text = (stderr or "").strip() or (stdout or "").strip()
    text = re.sub(r"\AOpenAI Codex v.*?\n-{4,}\n.*?\n-{4,}\n(?:user\n)?", "", text, flags=re.DOTALL).strip()  # 抬头去掉
    errors = [line.strip() for line in text.splitlines() if re.match(r"\s*(ERROR|Error|error)\b", line)]
    if errors:
        return "；".join(errors[-2:])[-limit:]
    return text[-limit:] or "没有输出"


def is_claude(argv: list[str]) -> bool:
    return bool(argv) and Path(argv[0]).name == "claude"


def codex_bin() -> str:
    return shutil.which("codex") or next((p for p in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex") if Path(p).is_file()), "codex")


def _tools(value: str) -> set[str]:
    """--allowedTools "Read Glob" / Bash,Edit：只取工具名，Read(/x/**) 这种带规则的不算放行。"""
    return {t for t in re.split(r"[\s,]+", value) if t and "(" not in t}


def parse_claude(argv: list[str]) -> dict[str, Any]:
    spec: dict[str, Any] = {"model": "sonnet", "json": False, "allowed": set(), "dirs": [], "system": "", "resume": None, "no_tools": False}
    i = 1
    while i < len(argv):
        arg, nxt = argv[i], argv[i + 1] if i + 1 < len(argv) else ""
        if arg in ("--model", "--output-format", "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools",
                   "--add-dir", "--system-prompt", "--append-system-prompt", "--resume", "--permission-mode", "--max-turns", "--tools"):
            if arg == "--tools":
                spec["no_tools"] = not nxt.strip()
            elif arg == "--model":
                spec["model"] = nxt
            elif arg == "--output-format":
                spec["json"] = nxt == "json"
            elif arg in ("--allowedTools", "--allowed-tools"):
                spec["allowed"] |= _tools(nxt)
            elif arg == "--add-dir":
                spec["dirs"].append(nxt)
            elif arg in ("--system-prompt", "--append-system-prompt"):
                spec["system"] = (spec["system"] + "\n\n" + nxt).strip()
            elif arg == "--resume":
                spec["resume"] = nxt or None
            i += 2
            continue
        i += 1
    if spec["no_tools"]:
        spec["allowed"].clear()
    return spec


def skill_note(prompt: str, roots: tuple[Path, ...] | None = None) -> str:
    """提问里点名的 skill，本机找得到 SKILL.md 的，告诉 Codex 去哪读。"""
    lines, seen = [], set()
    for name in SKILL_MENTION.findall(prompt):
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        for root in roots or SKILL_ROOTS:
            path = root.expanduser() / name / "SKILL.md"
            if path.is_file():
                lines.append(f"- {name} skill：先读 {path} 并照它做；它引用的 references/、scripts/ 在同一个目录里。")
                break
    return ("本机 skill 位置：\n" + "\n".join(lines) + "\n\n") if lines else ""


def codex_argv(spec: dict[str, Any], out_file: str) -> list[str]:
    writes = bool(spec["allowed"] & WRITE_TOOLS)
    web = bool(spec["allowed"] & WEB_TOOLS)
    effort = "high" if "opus" in spec["model"] else "medium"
    # project_doc_max_bytes=0：不读本机全局 / 目录里的 AGENTS.md——提问自带全部材料，别让它顺着指针去翻别的文件
    opts = ["--ignore-user-config", "--skip-git-repo-check", "-c", "project_doc_max_bytes=0", "-m", conf.value("codex.model"),
            "-c", f"model_reasoning_effort={effort}",
            "-c", f'sandbox_mode="{"workspace-write" if writes else "read-only"}"',
            "-c", f'web_search="{"live" if web else "disabled"}"',
            "-o", out_file]
    if spec.get("no_tools"):
        # cli_turn 的 --tools "" 也必须穿过 Codex 翻译层，不能退化成整盘只读。
        opts += ["-c", "include_apply_patch_tool=false", "-c", "tools.disable_defaults=true"]
        for feature in ("shell_tool", "shell_snapshot", "view_image", "view_image_tool", "multi_agent", "multi_agent_v2",
                        "apps", "plugins", "computer_use", "browser_use", "image_generation", "tool_suggest"):
            opts += ["-c", f"features.{feature}=false"]
    if writes:
        opts += ["-c", "sandbox_workspace_write.network_access=true"]
    if spec["json"]:
        opts.append("--json")
    if spec["resume"]:
        return [codex_bin(), "exec", "resume", *opts, spec["resume"], "-"]
    if not spec["json"]:
        opts.append("--ephemeral")  # 不用续的对话不留会话文件
    for d in spec["dirs"] if writes else ():
        opts += ["--add-dir", d]
    return [codex_bin(), "exec", *opts, "-"]


def codex_prompt(spec: dict[str, Any], prompt: str) -> str:
    head = "" if spec.get("no_tools") else skill_note(prompt)
    if spec["system"] and not spec["resume"]:
        head = f"<instructions>\n{spec['system']}\n</instructions>\n\n" + head
    return head + prompt


def _thread_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            return event.get("thread_id")
    return None


def run(argv: list[str], *, input: str = "", timeout: float = 600, cwd: str | None = None) -> subprocess.CompletedProcess:
    """跑一次 AI 命令。claude 命令且后台选了 Codex 时翻译；返回值和 subprocess.run(text=True) 一样，stdout 是回答。"""
    if not (is_claude(argv) and backend() == "codex"):
        return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd)
    spec = parse_claude(argv)
    with tempfile.TemporaryDirectory(prefix="cs-codex-") as tmp:
        out_file = str(Path(tmp) / "answer.txt")
        cmd = codex_argv(spec, out_file)
        done = subprocess.run(cmd, input=codex_prompt(spec, input), capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd)
        try:
            answer = Path(out_file).read_text(encoding="utf-8").strip()
        except OSError:
            answer = ""
    stderr = done.stderr or ""
    if done.returncode == 0 and not answer:
        return subprocess.CompletedProcess(cmd, 1, done.stdout, (stderr + "\nCodex 没有回话").strip())
    if done.returncode != 0:
        if re.search(r"401 Unauthorized|not logged in|Please log ?in", stderr, re.IGNORECASE):
            stderr += "\nCodex authentication failed: run codex login"
        return subprocess.CompletedProcess(cmd, done.returncode, done.stdout, stderr)
    if spec["json"]:
        stdout = json.dumps({"result": answer, "session_id": _thread_id(done.stdout) or spec["resume"], "is_error": False}, ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, 0, stdout + "\n", stderr)
    return subprocess.CompletedProcess(cmd, 0, answer + "\n", stderr)


def prepare_prompt(base: str, prompt: str) -> str:
    """写进文件、给 shell 任务的提问：要翻成 codex 时补上 skill 位置。"""
    argv = shlex.split(base)
    return codex_prompt(parse_claude(argv), prompt) if is_claude(argv) and backend() == "codex" else prompt


def shell_command(base: str, add_dirs: list[str]) -> str:
    """后台跑的长任务（workflow_runner）拼 shell 用：claude 命令翻成 codex，回答和过程都进日志。"""
    argv = shlex.split(base)
    if not (is_claude(argv) and backend() == "codex"):
        return base + "".join(f" --add-dir {shlex.quote(d)}" for d in add_dirs)
    spec = parse_claude(argv)
    spec["dirs"] += add_dirs
    spec["allowed"] |= {"Write"}  # 长任务要写项目文件
    cmd = codex_argv(spec, "/dev/null")
    return shlex.join(cmd)
