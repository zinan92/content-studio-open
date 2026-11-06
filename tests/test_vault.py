from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path

import pytest

from content_studio import vault


def _write(path: Path, text: str, when: datetime | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if when:
        ts = when.timestamp()
        os.utime(path, (ts, ts))
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    old = datetime(2026, 8, 1)
    _write(tmp_path / "006_ai daily newsletter" / "26-09-14.md", "# AI Daily\n")
    _write(tmp_path / "007_finance newsletter" / "2026-09-13-finance-daily-newsletter.md", "x")
    _write(tmp_path / "007_finance newsletter" / "2026-09-14-finance-weekly-newsletter.md", "weekly")
    _write(tmp_path / "009_morning brief" / "2026-09-14.html", "<h1>brief</h1>")
    _write(
        tmp_path / "002_clippings" / "new.md",
        '---\ntitle: "起号逻辑"\nsource: "https://x.com/a/status/1"\ncreated: 2026-09-14\n---\n![Image](https://x/y.jpg)\n**正文**第一段 [链接](https://z)',
        datetime(2026, 9, 14, 9),
    )
    _write(tmp_path / "002_clippings" / "old.md", "---\ncreated: 2026-08-01\n---\nold", old)
    _write(tmp_path / "003_原始输出" / "ai与人" / "灵感.md", "# 不是我用AI\n今天想到", datetime(2026, 9, 13, 22))
    _write(tmp_path / "_secrets" / "token.md", "secret")
    return tmp_path


def test_dailies_match_both_date_formats(root: Path) -> None:
    items = {item["key"]: item for item in vault.dailies(str(root), date(2026, 9, 14))}
    assert items["ai_daily"]["path"] == "006_ai daily newsletter/26-09-14.md"
    assert [k for k in items] == ["ai_daily", "finance_daily", "kline_daily"]
    assert items["finance_daily"]["path"] is None  # 9/13 file, not today's; the 9/14 weekly shares the folder but is not the daily
    # 晨报 is a digest of the three dailies and stays out of the workbench
    with pytest.raises(vault.VaultError):
        vault.read_note(str(root), "009_morning brief/2026-09-14.html")


def test_inbox_lists_recent_notes_with_titles_and_summaries(root: Path) -> None:
    items = vault.inbox(str(root), since=datetime(2026, 9, 13))
    assert [i["title"] for i in items] == ["起号逻辑", "不是我用AI"]
    clip = items[0]
    assert clip["source_label"] == "Clippings" and clip["url"] == "https://x.com/a/status/1"
    assert clip["summary"] == "正文第一段 链接"
    assert vault.inbox(str(root), since=datetime(2026, 9, 13), sources=("raw",))[0]["source"] == "raw"


@pytest.mark.parametrize("relative", ["_secrets/token.md", "../etc/passwd", "002_clippings/../_secrets/token.md", "/etc/hosts", "002_clippings"])
def test_paths_outside_allowed_folders_are_refused(root: Path, relative: str) -> None:
    with pytest.raises(vault.VaultError):
        vault.read_note(str(root), relative)


def test_symlink_escape_is_refused(root: Path) -> None:
    (root / "002_clippings" / "link.md").symlink_to(root / "_secrets" / "token.md")
    with pytest.raises(vault.VaultError):
        vault.read_note(str(root), "002_clippings/link.md")


def test_read_note_and_missing_vault(root: Path) -> None:
    note = vault.read_note(str(root), "002_clippings/new.md")
    assert note["title"] == "起号逻辑" and "正文" in note["body"] and note["meta"]["source"].startswith("https://")
    with pytest.raises(vault.VaultError, match="找不到"):
        vault.inbox(str(root / "nope"), since=datetime(2026, 9, 1))


def test_window_start_one_day_is_24_hours_and_longer_windows_start_at_midnight() -> None:
    # 「1 天」 is the last 24 hours on the clock; 3/7/30 start at midnight so the list is stable all day.
    assert vault.window_start(1, datetime(2026, 9, 14, 15)) == datetime(2026, 9, 13, 15)
    assert vault.window_start(0, datetime(2026, 9, 14, 15)) == datetime(2026, 9, 13, 15)
    assert vault.window_start(3, datetime(2026, 9, 14, 15)) == datetime(2026, 9, 11)
    assert vault.window_start(7, datetime(2026, 9, 14, 15)) == datetime(2026, 9, 7)


def test_inbox_carries_the_author_so_进项_can_show_the_blogger(tmp_path) -> None:
    from datetime import datetime, timedelta

    from content_studio import vault

    root = tmp_path / "v"
    (root / "002_对标内容").mkdir(parents=True)
    (root / "002_对标内容" / "a.md").write_text(
        f"---\ntitle: 一条内容\nauthor: 柱子哥TzFilm\npublished: {(datetime.now() - timedelta(hours=2)).isoformat(timespec='seconds')}\nsource: https://www.douyin.com/video/1\n---\n\n正文", encoding="utf-8"
    )
    items = vault.inbox(str(root), since=datetime.now() - timedelta(days=1))
    assert [(i["source"], i["author"]) for i in items] == [("benchmark", "柱子哥TzFilm")]


def test_daily_history_lists_only_dated_issues_and_labels_a_second_one(tmp_path) -> None:
    """作者: 这个 README 不用放在这啊。The folder also holds tooling scratch dirs."""
    from content_studio import vault

    root = tmp_path / "v"
    folder = root / "006_ai daily newsletter"
    folder.mkdir(parents=True)
    for name in ("26-09-20.md", "26-09-19.md", "26-09-19-晚.md", "README.md", "notes.md"):
        (folder / name).write_text("x", encoding="utf-8")
    (folder / "tmp-scratch").mkdir()

    items = vault.daily_history(str(root), "ai_daily")
    assert [i["title"] for i in items] == [
        "AI 日报 · 2026-09-20", "AI 日报 · 2026-09-19 晚", "AI 日报 · 2026-09-19",
    ]


def test_passive_sources_are_windowed_on_publish_date_and_active_ones_on_when_park_added_them(tmp_path) -> None:
    """作者: 我收藏的 / 我写的 / Clippings 是我主动加的，看我什么时候加；对标是被动收的，
    一个新账号第一次同步会写进几十篇，按写入时间它们全是今天的——所以看作者什么时候发。"""
    from datetime import datetime, timedelta

    from content_studio import vault

    root = tmp_path / "v"
    (root / "002_对标内容").mkdir(parents=True)
    (root / "002_clippings").mkdir()
    old_pub = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%dT10:00:00")
    new_pub = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT10:00:00")
    # both benchmark notes were written just now; only the recently published one counts
    (root / "002_对标内容" / "old.md").write_text(f"---\ntitle: 老\nauthor: A\npublished: {old_pub}\n---\n正文", encoding="utf-8")
    (root / "002_对标内容" / "new.md").write_text(f"---\ntitle: 新\nauthor: A\npublished: {new_pub}\n---\n正文", encoding="utf-8")
    # a clipping 作者 saved today, of an article written months ago: it is new to him
    (root / "002_clippings" / "c.md").write_text("---\ntitle: 剪藏\npublished: 2025-01-01\nsource: https://x\n---\n正文", encoding="utf-8")

    since = datetime.now() - timedelta(days=7)
    got = {(i["source"], i["title"]) for i in vault.inbox(str(root), since=since)}
    assert got == {("benchmark", "新"), ("clipping", "剪藏")}
    # 3-day window: the 2-day-old benchmark post still shows; a 1-day window drops it
    assert {i["title"] for i in vault.inbox(str(root), since=datetime.now() - timedelta(days=3))} == {"新", "剪藏"}
    assert {i["title"] for i in vault.inbox(str(root), since=datetime.now() - timedelta(days=1))} == {"剪藏"}


def test_parks_own_writing_ignores_the_time_window(tmp_path) -> None:
    """作者: 我写的东西没有时效性，一个月前写的、只要还没拍，今天照样能拍。
    时间窗会把它挡在外面，而它本来就该一直等在那儿。"""
    from datetime import datetime, timedelta

    from content_studio import vault

    root = tmp_path / "v"
    (root / "003_原始输出" / "商业模式").mkdir(parents=True)
    (root / "002_clippings").mkdir()

    old = root / "003_原始输出" / "商业模式" / "新平台.md"
    old.write_text("# 新平台\n两个月前写的想法", encoding="utf-8")
    long_ago = (datetime.now() - timedelta(days=64)).timestamp()
    os.utime(old, (long_ago, long_ago))

    stale_clip = root / "002_clippings" / "旧剪藏.md"
    stale_clip.write_text("# 旧剪藏\n正文", encoding="utf-8")
    os.utime(stale_clip, (long_ago, long_ago))

    got = vault.inbox(str(root), since=datetime.now() - timedelta(days=7))
    by_source = {i["source"]: i["title"] for i in got}
    assert by_source.get("raw") == "新平台"      # 64 天前写的，照样在
    assert "clipping" not in by_source            # 剪藏按加入时间，确实过期了


def test_explicit_empty_dailies_does_not_inherit_owner_newsletters() -> None:
    old_sources, old_dailies = vault.INBOX_SOURCES, vault.DAILY_SOURCES
    try:
        vault.configure({"folders": {"my_writing": "mine"}, "dailies": []})
        assert vault.DAILY_SOURCES == ()
        vault.configure(None)
        assert vault.DAILY_SOURCES == vault._DEFAULT_DAILY_SOURCES
    finally:
        vault.INBOX_SOURCES, vault.DAILY_SOURCES = old_sources, old_dailies
