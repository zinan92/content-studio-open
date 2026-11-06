import json
from pathlib import Path
import subprocess

import pytest

from content_studio import platform_stats, screen_stats
from content_studio.platform_stats import NotConnected, StatsError


class FakeMac:
    """osascript / lsappinfo / ioreg / screencapture 的假替身。"""

    def __init__(self, *, url=screen_stats.XHS_URL, front="Google Chrome", active_tab="918762005", locked=False):
        self.url, self.front, self.active_tab, self.locked = url, front, active_tab, locked
        self.closed = False
        self.captured = []

    def __call__(self, argv, **kw):
        out = ""
        if argv[0] == "ioreg":
            out = '"CGSSessionScreenIsLocked" = Yes' if self.locked else ""
        elif argv[0] == "lsappinfo":
            out = "ASN:0x0-0x1:" if argv[1] == "front" else f'"LSDisplayName"="{self.front}"'
        elif argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"png")
            self.captured.append(argv)
        elif argv[0] == "osascript":
            script = argv[2]
            if "make new tab" in script:
                out = "918762005,918760661"
            elif "close t" in script:
                self.closed = True
            elif "loading of t" in script:
                out = "false"
            elif "URL of t" in script:
                out = self.url
            elif "active tab" in script:
                out = f"{self.active_tab},1"
            elif "bounds of w" in script:
                out = "0, 25, 1440, 900"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def test_capture_takes_only_the_chrome_window_and_closes_its_own_tab(tmp_path: Path) -> None:
    mac = FakeMac()
    screen_stats.capture_page(screen_stats.XHS_URL, tmp_path / "x.png", run=mac, sleep=lambda s: None)
    assert mac.captured[0][:4] == ["screencapture", "-x", "-R", "0,25,1440,875"] and mac.closed


@pytest.mark.parametrize("mac, error", [
    (FakeMac(front="WeChat"), StatsError),                                   # 作者 正在用别的程序
    (FakeMac(active_tab="1"), StatsError),                                   # 他切到了别的标签页
    (FakeMac(url="https://creator.xiaohongshu.com/login"), NotConnected),   # Chrome 里没登录
])
def test_nothing_is_captured_when_the_page_is_not_ours(tmp_path: Path, mac: FakeMac, error: type) -> None:
    with pytest.raises(error):
        screen_stats.capture_page(screen_stats.XHS_URL, tmp_path / "x.png", run=mac, sleep=lambda s: None)
    assert mac.captured == [] and mac.closed  # 不截，但我们开的标签页照样关掉


def test_a_locked_screen_opens_nothing(tmp_path: Path) -> None:
    mac = FakeMac(locked=True)
    with pytest.raises(StatsError, match="锁"):
        screen_stats.capture_page(screen_stats.XHS_URL, tmp_path / "x.png", run=mac, sleep=lambda s: None)
    assert not mac.closed and mac.captured == []


def _model(reply: dict):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=json.dumps(reply, ensure_ascii=False), stderr="")


def test_numbers_are_kept_only_from_parks_note_data_page(tmp_path: Path) -> None:
    image = tmp_path / "x.png"
    good = {"page_ok": True, "account": "我的账号", "tab": "笔记数据",
            "notes": [{"title": "我终于理解了dontbesilent为什么开...", "published": "2026-09-24 14:53", "views": 28}]}
    assert screen_stats.read_numbers(image, run=_model(good)) == [{"post_id": "2026-09-24 14:53|我终于理解了dontbe", "title": "我终于理解了dontbesilent为什么开...",
                                                                  "published_at": "2026-09-24T14:53:00+08:00", "views": 28}]
    for bad in ({**good, "account": "别人"}, {**good, "tab": "直播数据"}, {**good, "page_ok": False},
                {**good, "notes": [{"title": "t", "published": "昨天", "views": 1}]}, {**good, "notes": [{"title": "t", "published": "2026-09-24 14:53", "views": "28"}]}):
        with pytest.raises(StatsError):
            screen_stats.read_numbers(image, run=_model(bad))


def test_the_screenshot_does_not_outlive_the_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screen_stats, "TMP_ROOT", tmp_path / "tmp")
    seen = []
    posts = screen_stats.xiaohongshu_posts(capture=lambda url, out: out.write_bytes(b"png"), read=lambda p: seen.append(p) or [])
    assert posts == [] and not seen[0].exists() and list((tmp_path / "tmp").iterdir()) == []


def test_a_failed_capture_is_not_retried_the_same_morning(tmp_path: Path) -> None:
    from content_studio.store import StudioStore

    tries = []

    def fetch():
        tries.append(1)
        raise StatsError("截图那一刻 Chrome 不在最前")

    fetch.retry = False
    out = platform_stats.sync(StudioStore(tmp_path / "s.sqlite3"), {"xiaohongshu": fetch})
    assert out["xiaohongshu"]["ok"] is False and len(tries) == 1


def test_a_permission_prompt_nobody_answers_becomes_a_readable_error() -> None:
    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 30)

    with pytest.raises(StatsError, match="允许"):
        screen_stats._osa("tell application \"Google Chrome\" to activate", hang)
