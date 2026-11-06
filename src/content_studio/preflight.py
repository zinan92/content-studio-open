"""装机前检查：这台 Mac 够不够格装内容工作台。

作者 9/28：第一版只支持 Mac，门槛就是筛人。要求（在 作者 的 M4 / 16GB 上实测定的）：
M 芯片、macOS 14 以上、内存 16GB、硬盘可用 30GB。

这个文件不 import 工作台的任何东西，也不用新语法——装机时 Mac 上可能只有系统自带的
Python 3.9，脚本要能直接跑：python3 src/content_studio/preflight.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MIN_MACOS = 14
MIN_RAM_GB = 16
MIN_FREE_GB = 30
GB = 1024 ** 3


def gather() -> dict:
    """读这台电脑的实际情况。"""
    try:
        ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False).stdout.strip() or 0)
    except (OSError, ValueError):
        ram = 0
    apps = Path("/Applications")
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "macos": platform.mac_ver()[0],
        "ram": ram,
        "free": shutil.disk_usage(str(Path.home())).free,
        "tools": {name: bool(shutil.which(name)) for name in ("brew", "git", "node", "ffmpeg")},
        "chrome": (apps / "Google Chrome.app").exists(),
        "obsidian": (apps / "Obsidian.app").exists(),
    }


def check(facts: dict) -> list:
    """每项一行：(名字, 过没过, 是不是硬门槛, 说明)。"""
    rows = []
    mac = facts.get("system") == "Darwin"
    arm = facts.get("machine") == "arm64"
    rows.append(("芯片", mac and arm, True, "Apple M 芯片" if arm else "不是 M 芯片（Intel 或不是 Mac），本地转写跑不了"))
    try:
        major = int(str(facts.get("macos") or "0").split(".")[0])
    except ValueError:
        major = 0
    rows.append(("系统", major >= MIN_MACOS, True, f"macOS {facts.get('macos') or '?'}" + ("" if major >= MIN_MACOS else f"，要 {MIN_MACOS} 或更新")))
    ram_gb = round((facts.get("ram") or 0) / GB)
    rows.append(("内存", ram_gb >= MIN_RAM_GB, True, f"{ram_gb}GB" + ("" if ram_gb >= MIN_RAM_GB else f"，要 {MIN_RAM_GB}GB，转写时会卡死")))
    free_gb = int((facts.get("free") or 0) / GB)
    rows.append(("硬盘可用", free_gb >= MIN_FREE_GB, True, f"{free_gb}GB" + ("" if free_gb >= MIN_FREE_GB else f"，要 {MIN_FREE_GB}GB，先清理")))
    tools = facts.get("tools") or {}
    rows.append(("Homebrew", bool(tools.get("brew")), False, "有" if tools.get("brew") else "没有：先装 https://brew.sh ，装机脚本用它装 Python、Node、ffmpeg"))
    rows.append(("Chrome", bool(facts.get("chrome")), False, "有" if facts.get("chrome") else "没有：发布到各平台要用它登录"))
    rows.append(("Obsidian", bool(facts.get("obsidian")), False, "有" if facts.get("obsidian") else "没有：笔记库要用它看"))
    return rows


def render(rows: list) -> str:
    lines = []
    for name, ok, hard, note in rows:
        mark = "✅" if ok else ("❌" if hard else "○ ")
        lines.append(f"  {mark} {name:<8} {note}")
    bad = [r for r in rows if r[2] and not r[1]]
    lines.append("")
    lines.append("✅ 硬件和系统都够，可以装。" if not bad else f"❌ 有 {len(bad)} 项不够，这台电脑装不了第一版。")
    return "\n".join(lines)


def main() -> int:
    rows = check(gather())
    print("内容工作台 · 装机前检查\n")
    print(render(rows))
    return 0 if all(ok for _, ok, hard, _ in rows if hard) else 1


if __name__ == "__main__":
    sys.exit(main())
