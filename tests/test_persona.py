from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from content_studio import illustrate as il
from content_studio.extras.positioning import persona

ARTICLE = "# 怎么让 AI 赚钱\n\n变便宜的是产品，变贵的是信任。\n\n所以一定不要说违心的话。\n"
SPEC = "# 作者 角色固定规范\n\n角色名称为 作者。朱红 T 恤，胸口米白「作者」。\n"


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    base = tmp_path / "persona"
    base.mkdir()
    monkeypatch.setenv("CONTENT_STUDIO_PERSONA", str(base))
    return base


def with_character(base: Path) -> None:
    (base / "spec.md").write_text(SPEC, encoding="utf-8")
    for name in ("reference.png", "avatar.png", "sheet.png", "fullbody.png"):
        (base / name).write_bytes(b"png")


def runner(seen: list[str], files=("01-trust.png", "02-lost.png")):
    def run(text: str, cwd: Path) -> None:
        seen.append(text)
        seen.append(",".join(sorted(p.name for p in (cwd / persona.STAGE).glob("*"))) if (cwd / persona.STAGE).exists() else "")
        folder = cwd / il.FOLDER
        for f in files:
            (folder / f).write_bytes(b"png")
        plan = [{"file": files[0], "after": "变便宜的是产品", "caption": "信任变贵"}]
        if len(files) > 1:
            plan.append({"file": files[1], "after": "文章里没有这一段", "caption": "没插上"})
        (folder / il.PLAN).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return run


def test_no_character_draws_xiaohei_and_keeps_no_gallery(home: Path, tmp_path: Path) -> None:
    """客户装机没有形象：和以前一样画小黑，不建形象库。"""
    (home / "spec.md").write_text(SPEC, encoding="utf-8")  # 只有 spec、没有参考图，也不算有角色
    article = tmp_path / "t1" / "article.md"
    article.parent.mkdir()
    article.write_text(ARTICLE, encoding="utf-8")
    seen: list[str] = []
    il.illustrate(article, runner=runner(seen))
    assert persona.character() is None
    assert "不要小黑" not in seen[0] and seen[1] == ""
    assert persona.gallery() == [] and not (home / persona.GALLERY).exists()


def test_character_replaces_xiaohei_and_every_round_is_kept(home: Path, tmp_path: Path) -> None:
    with_character(home)
    article = tmp_path / "topic-54" / "article.md"
    article.parent.mkdir()
    article.write_text(ARTICLE, encoding="utf-8")
    seen: list[str] = []
    il.illustrate(article, runner=runner(seen))
    text = seen[0]
    assert "ian-xiaohei-illustrations" in text and "不要小黑" in text and "固定角色 作者" in text
    assert "persona-ref/spec.md" in text and "忽略 xiaohei-ip.md" in text
    assert seen[1] == "avatar.png,fullbody.png,reference.png,sheet.png,spec.md"
    assert not (article.parent / persona.STAGE).exists()  # 参考图用完就收走，不留在文章目录
    il.illustrate(article, runner=runner(seen, files=("01-again.png",)))
    # 文章里只剩第二轮的图，形象库两轮都在，画出来没插上的也在
    assert not (article.parent / il.FOLDER / "01-trust.png").exists()
    files = [g["file"] for g in persona.gallery()]
    assert len(files) == 3 and files[0].endswith("/01-again.png")
    assert any(f.endswith("/02-lost.png") for f in files)
    dirs = sorted(p.name for p in (home / persona.GALLERY).iterdir() if p.is_dir())
    assert len(dirs) == 2 and dirs[0].endswith("topic-54") and dirs[1].endswith("topic-54-v2")
    assert persona.gallery()[-1]["title"] == "怎么让 AI 赚钱"


def test_archive_never_overwrites(home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "a" / il.FOLDER
    folder.mkdir(parents=True)
    (folder / "01-x.png").write_bytes(b"one")
    article = folder.parent / "article.md"
    article.write_text(ARTICLE, encoding="utf-8")
    day = datetime(2026, 10, 7, 9, 0)
    first = persona.archive(article, folder, [{"file": "01-x.png"}], now=day)
    (folder / "01-x.png").write_bytes(b"two")
    second = persona.archive(article, folder, [{"file": "01-x.png"}], now=day)
    assert first and second and first != second
    assert (first / "01-x.png").read_bytes() == b"one" and (second / "01-x.png").read_bytes() == b"two"
    assert persona.archive(article, folder, [{"file": "missing.png"}], now=day) is None


def test_state_and_safe_file_lookup(home: Path, tmp_path: Path) -> None:
    with_character(home)
    (home / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "secret.png").write_bytes(b"x")
    st = persona.state()
    assert st["ready"] and st["name"] == "作者"
    assert [b["file"] for b in st["base"]] == ["avatar.png", "fullbody.png", "sheet.png", "reference.png"]
    assert persona.file("avatar.png") == (home / "avatar.png").resolve()
    assert persona.file("../secret.png") is None
    assert persona.file("notes.txt") is None
    assert persona.file("nope.png") is None


def test_own_ip_skill_is_called_directly_without_the_xiaohei_swap(tmp_path: Path, monkeypatch) -> None:
    """ip-studio 生成的 bundle：persona/ 在 <slug>-ip-illustrations/ 下面，配图直接调那个 skill。"""
    bundle = tmp_path / "park-ip-illustrations"
    base = bundle / "persona"
    base.mkdir(parents=True)
    monkeypatch.setenv("CONTENT_STUDIO_PERSONA", str(base))
    with_character(base)
    assert persona.skill() is None  # 没有 SKILL.md 还是走小黑换角
    (bundle / "SKILL.md").write_text("---\nname: park-ip-illustrations\ndescription: x\n---\n", encoding="utf-8")
    assert persona.skill() == "park-ip-illustrations" and persona.state()["skill"] == "park-ip-illustrations"
    article = tmp_path / "topic-1" / "article.md"
    article.parent.mkdir()
    article.write_text(ARTICLE, encoding="utf-8")
    seen: list[str] = []
    il.illustrate(article, runner=runner(seen, files=("01-trust.png",)))
    assert seen[0].startswith("用 $park-ip-illustrations 给这篇") and "不要小黑" not in seen[0]
    assert "persona-ref/" in seen[0] and "ian-xiaohei" not in seen[0]
    assert len(persona.gallery()) == 1
    from content_studio import skills
    assert skills._figs_skill()["title"] == "作者 IP 配图"


def test_thumbs_are_small_cached_and_change_with_the_picture(home: Path, tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cfg"))
    with_character(home)
    Image.new("RGBA", (1920, 1080), (226, 70, 31, 128)).save(home / "sheet.png")
    first = persona.thumb("sheet.png")
    assert first is not None and first.is_relative_to(tmp_path / "cfg")  # 不往形象文件夹里写
    with Image.open(first) as im:
        assert im.size == (640, 360) and im.mode == "RGBA"
    assert persona.thumb("sheet.png") == first
    v = persona.state()["base"][2]["v"]
    Image.new("RGB", (800, 800), "white").save(home / "sheet.png")
    second = persona.thumb("sheet.png")
    assert second != first and persona.state()["base"][2]["v"] != v
    assert persona.thumb("../secret.png") is None and persona.thumb("nope.png") is None
    assert persona.thumb("avatar.png") == (home / "avatar.png").resolve()  # 不是真图：退回原图，不报错


def test_staging_copies_banners_in_their_subfolder(home: Path, tmp_path: Path) -> None:
    """10/7：形象里有了 banner/x-1500x500.png，配图把参考图拷进文章目录时没建 banner/，插图一直报 Errno 2。"""
    with_character(home)
    (home / "banner").mkdir()
    (home / "banner" / "x-1500x500.png").write_bytes(b"png")
    dest = persona.stage(tmp_path / "文章")
    assert (dest / "banner" / "x-1500x500.png").read_bytes() == b"png"
    assert (dest / "spec.md").is_file()
