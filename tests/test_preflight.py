"""装机前检查：M 芯片、macOS 14+、16GB、30GB 可用是硬门槛；Homebrew、Chrome、Obsidian 只提示。"""
from content_studio import preflight

GB = 1024 ** 3
MAC_M4 = {"system": "Darwin", "machine": "arm64", "macos": "26.2", "ram": 16 * GB, "free": 120 * GB,
           "tools": {"brew": True, "git": True}, "chrome": True, "obsidian": True}


def hard_failures(facts: dict) -> list[str]:
    return [name for name, ok, hard, _ in preflight.check(facts) if hard and not ok]


def test_a_mac_like_parks_passes() -> None:
    assert hard_failures(MAC_M4) == []
    assert "可以装" in preflight.render(preflight.check(MAC_M4))


def test_each_hard_requirement_blocks() -> None:
    assert hard_failures({**MAC_M4, "machine": "x86_64"}) == ["芯片"]
    assert hard_failures({**MAC_M4, "system": "Windows"}) == ["芯片"]
    assert hard_failures({**MAC_M4, "macos": "13.6"}) == ["系统"]
    assert hard_failures({**MAC_M4, "ram": 8 * GB}) == ["内存"]
    assert hard_failures({**MAC_M4, "free": 11 * GB}) == ["硬盘可用"]


def test_missing_apps_only_warn() -> None:
    facts = {**MAC_M4, "tools": {}, "chrome": False, "obsidian": False}
    assert hard_failures(facts) == []
    assert "brew.sh" in preflight.render(preflight.check(facts))
