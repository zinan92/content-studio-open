"""能力积木和主线之间的口子写明在两边：主线的 web.BLOCK_API，积木的 NEEDS / PROVIDES。"""
from __future__ import annotations

import importlib

import pytest

from content_studio import blocks, extras, web


def _modules():
    """挂的顺序：先主线积木（blocks/），再加购（extras/）。"""
    return [*((name, importlib.import_module(f"content_studio.blocks.{name}")) for name in blocks.MODULES),
            *((name, importlib.import_module(f"content_studio.extras.{name}.routes")) for name in extras.MODULES)]


def test_block_api_names_all_exist(tmp_path, monkeypatch):
    """完整版里 BLOCK_API 的每一样主线都真的给了（试用版剪掉的才允许缺）。"""
    seen = {}

    def capture(app, ctx):
        seen.update(ctx)
        return []

    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(extras, "register_all", capture)
    monkeypatch.setattr(blocks, "register_all", lambda app, ctx: [])
    cookie = tmp_path / "c.json"
    cookie.write_text("{}")
    cookie.chmod(0o600)
    web.create_app(store_path=tmp_path / "s.sqlite3", cookie_path=cookie, creator_db=None, data_dir=tmp_path / "d",
                   downloads_dir=tmp_path / "dl", drafts_dir=tmp_path / "dr", start_worker=False)
    assert set(seen) == set(web.BLOCK_API)


def test_every_need_is_offered_and_every_offer_is_needed():
    offered = set(web.BLOCK_API)
    provided: set[str] = set()
    needed: set[str] = set()
    for name, mod in _modules():
        missing = set(mod.NEEDS) - offered - provided
        assert not missing, f"{name} 要的这些主线没给、前面的积木也没递：{sorted(missing)}"
        needed |= set(mod.NEEDS)
        provided |= set(mod.PROVIDES)
    assert not offered - needed, f"BLOCK_API 里这些没有积木在用，拿掉：{sorted(offered - needed)}"
    assert not provided - needed, f"这些递出去了没人用：{sorted(provided - needed)}"


def test_a_block_cannot_reach_past_its_declaration():
    shared = {"store": object(), "profile": {}}
    ctx = extras.BlockContext("demo", shared, needs=("store",), provides=("helper",))
    assert ctx.store is shared["store"]
    with pytest.raises(AttributeError, match="没写进它的 NEEDS"):
        ctx.profile
    ctx.helper = len
    assert shared["helper"] is len
    with pytest.raises(AttributeError, match="没写进它的 PROVIDES"):
        ctx.other = 1
