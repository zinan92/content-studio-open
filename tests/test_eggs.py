"""送出去的鸡蛋（10/14 作者）：话术放在 Obsidian，汇总那张表每条视频一列，点开在 Obsidian 里看。"""
from pathlib import Path

from content_studio import eggs
from tests.test_web import SEC, _wait_sync, client  # noqa: F401 - fixture


def _note(vault: Path, name: str, text: str) -> None:
    folder = vault / eggs.FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_each_note_is_read_with_its_title_day_and_videos_and_never_changed(tmp_path: Path) -> None:
    assert eggs.load(tmp_path) == []  # 还没有这个文件夹
    _note(tmp_path, "2026-10-11 爆款拆解.md", "---\ntitle: 爆款拆解\nsent: 2026-10-11\nsource: https://www.douyin.com/video/111\n---\n你好，拆解的东西都在这了\n")
    _note(tmp_path, "2026-10-06 AI 日报.md", "---\ntitle: AI 日报\nsent: 2026-10-06\n---\nAI 日报来了\n")
    _note(tmp_path, "2026-10-14 没写属性.md", "只有正文，没有属性\n")
    got = {e["title"]: e for e in eggs.load(tmp_path)}
    assert got["爆款拆解"]["videos"] == ["111"] and got["AI 日报"]["videos"] == []
    assert got["没写属性"]["sent"] == "2026-10-14"  # 没写名字 / 日子：从文件名里读
    assert got["爆款拆解"]["open_url"].startswith("obsidian://open?path=") and "%E9%B8%A1%E8%9B%8B" in got["爆款拆解"]["open_url"]
    assert set(eggs.by_video(tmp_path)) == {"111"}
    assert "你好，拆解的东西都在这了" in (tmp_path / eggs.FOLDER / "2026-10-11 爆款拆解.md").read_text(encoding="utf-8")


def test_the_summary_sheet_rows_carry_the_egg_given_after_that_video(client, tmp_path: Path) -> None:
    client.post("/api/accounts", json={"url": f"https://www.douyin.com/user/{SEC}", "is_self": True})
    _wait_sync(client)
    vault = tmp_path / "vault-egg"
    vault.mkdir()
    client.put("/api/settings", json={"obsidian_vault": str(vault)})
    vid = client.get("/api/backfill").json()["videos"][0]["video_id"]
    assert client.get("/api/backfill").json()["videos"][0]["egg"] is None
    _note(vault, "2026-10-11 爆款拆解.md", f"---\ntitle: 爆款拆解\nsent: 2026-10-11\nsource: https://www.douyin.com/video/{vid}\n---\n话术\n")
    rows = {r["video_id"]: r for r in client.get("/api/backfill").json()["videos"]}
    assert rows[vid]["egg"]["title"] == "爆款拆解" and rows[vid]["egg"]["open_url"].startswith("obsidian://")
    assert all(r["egg"] is None for k, r in rows.items() if k != vid)


def test_the_x_style_summary_does_not_read_egg_scripts_as_his_posts(tmp_path: Path) -> None:
    from content_studio.extras.xline import x_suggest

    published = tmp_path / x_suggest.PUBLISHED_FOLDER
    published.mkdir(parents=True)
    (published / "2026-10-08 一条视频.md").write_text("---\ntitle: 一条视频\n---\n我自己讲的话\n", encoding="utf-8")
    _note(tmp_path, "2026-10-11 爆款拆解.md", "---\ntitle: 爆款拆解\n---\n你好，拆解的东西都在这了\n")
    text = x_suggest.corpus(tmp_path)
    assert "我自己讲的话" in text and "拆解的东西都在这了" not in text
