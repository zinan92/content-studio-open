"""风格数据合同、只读查询，以及坏数据不会被静默放过。"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from content_studio.extras.tools import styles


def test_catalog_is_valid_and_covers_six_sources() -> None:
    assert styles.validate() == []
    assert len(styles.SOURCE_FILES) == 6
    for filename in styles.SOURCE_FILES:
        data = json.loads((styles.DATA_DIR / filename).read_text(encoding="utf-8"))
        minimum = 30 if filename == "huashu-art-motion.json" else 15 if filename == "mg-styles.json" else 10
        assert len(data["styles"]) >= minimum, filename
        if filename == "huashu-art-motion.json":
            assert len(data["grammars"]) == 9


def test_ids_and_queries_include_grammars_without_combining_them() -> None:
    all_styles = styles.load_all()
    syntax = styles.grammars()
    rows = all_styles + syntax
    assert len({row["id"] for row in rows}) == len(rows)
    assert len(syntax) == 9
    assert all(row["function"] == "grammar" for row in syntax)
    assert all(row["function"] != "grammar" for row in all_styles)
    for row in rows:
        assert styles.get(row["id"]) == row
    assert styles.get("does-not-exist") is None
    assert styles.by_function("grammar") == []
    assert styles.by_function("unknown") == []
    for fn in ("image", "video", "motion"):
        selected = styles.by_function(fn)
        assert selected
        assert selected == [row for row in all_styles if row["function"] == fn]


def test_names_summaries_and_handraw_credit() -> None:
    import re

    for row in styles.load_all() + styles.grammars():
        assert re.search(r"[\u4e00-\u9fff]", row["name"]), row["id"]
        assert len(row["summary"]) <= 40, row["id"]
        assert re.search(r"[\u4e00-\u9fff]", row["summary"]) or "summary" in row["needs"], row["id"]
    data = json.loads((styles.DATA_DIR / "handraw.json").read_text(encoding="utf-8"))
    credit = "handraw-style by yang0 (https://github.com/yang0/handraw-style)"
    assert data["source"]["attribution"] == credit
    assert all(row["attribution"] == credit for row in data["styles"])


def test_index_matches_data() -> None:
    index = json.loads((styles.DATA_DIR / "index.json").read_text(encoding="utf-8"))
    rows = styles.load_all()
    syntax = styles.grammars()
    assert index["totals"]["styles"] == len(rows)
    assert index["totals"]["grammars"] == len(syntax)
    assert index["totals"]["needs"] == sum(bool(row["needs"]) for row in rows)
    assert index["totals"]["grammar_needs"] == sum(bool(row["needs"]) for row in syntax)
    assert index["totals"]["listed"] == sum(row["listed"] for row in rows)
    assert index["totals"]["unlisted"] == sum(not row["listed"] for row in rows)
    assert index["totals"]["grammar_listed"] == sum(row["listed"] for row in syntax)
    assert index["totals"]["grammar_unlisted"] == sum(not row["listed"] for row in syntax)
    assert index["totals"]["candidates"] == len(rows) + index["totals"]["skipped"]
    assert set(index["sources"]) == set(styles.SOURCE_FILES)
    for filename, count in index["sources"].items():
        data = json.loads((styles.DATA_DIR / filename).read_text(encoding="utf-8"))
        assert count["styles"] == len(data["styles"])
        assert count["grammars"] == len(data.get("grammars", []))
        assert count["needs"] == sum(bool(row["needs"]) for row in data["styles"])
        assert count["listed"] == sum(row["listed"] for row in data["styles"])
        assert count["unlisted"] == sum(not row["listed"] for row in data["styles"])
        assert count["grammar_listed"] == sum(row["listed"] for row in data.get("grammars", []))
        assert count["grammar_unlisted"] == sum(not row["listed"] for row in data.get("grammars", []))
        assert count["unlisted_reasons"] == dict(Counter(
            reason for row in data["styles"] if not row["listed"] for reason in row["needs"]))
        assert count["skipped"] >= 0
        assert count["candidates"] == count["styles"] + count["skipped"]
        assert count["categories"] == dict(Counter(row["category"] for row in data["styles"]))
    assert index["totals"]["skipped"] == sum(row["skipped"] for row in index["sources"].values())
    assert index["functions"] == dict(Counter(row["function"] for row in rows))
    assert index["listed_by_function"] == dict(Counter(row["function"] for row in rows if row["listed"]))
    assert index["unlisted_by_function"] == dict(Counter(row["function"] for row in rows if not row["listed"]))
    for fn in ("image", "video", "motion"):
        assert index["categories"][fn] == dict(Counter(row["category"] for row in rows if row["function"] == fn))
        assert index["skipped_by_function"][fn] == sum(source["skipped"] for source in index["sources"].values() if source["function"] == fn)
        assert sum(index["skipped_by_category"][fn].values()) == index["skipped_by_function"][fn]
    skipped = index["skipped_items"]
    assert len(skipped) == index["totals"]["skipped"]
    assert len({(row["case"], row["variant"]) for row in skipped}) == len(skipped)
    assert all(row["reason"].strip() and row["source_excerpt"].strip() for row in skipped)
    assert index["skipped_by_category"]["image"] == dict(Counter(row["category"] for row in skipped))


@pytest.fixture
def catalog_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """最小的六来源目录，专门验证损坏输入，不依赖生产数据的某个具体条目。"""
    row = {
        "id": "sample", "function": "motion", "category": "线条", "name": "线条变化",
        "name_en": "Line motion", "summary": "线条按内容依次出现。", "prompt": "Animate {script}.",
        "inputs": ["script"], "aspect": None, "path": "README.md", "preview": None,
        "attribution": None, "status": "draft", "needs": [], "listed": True,
    }
    for number, filename in enumerate(styles.SOURCE_FILES):
        entry = deepcopy(row)
        entry["id"] = f"sample-{number}"
        data = {
            "source": {"repo": f"example/source-{number}", "license": "MIT", "url": "https://github.com/example/source", "attribution": None},
            "function": "motion", "styles": [entry],
        }
        if filename == "huashu-art-motion.json":
            grammar = deepcopy(row)
            grammar.update(id="grammar-one", function="grammar")
            data["grammars"] = [grammar]
        if filename == "handraw.json":
            data["source"].update(repo="yang0/handraw-style", attribution=styles._HANDRAW_ATTRIBUTION)
            entry["attribution"] = styles._HANDRAW_ATTRIBUTION
        (tmp_path / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(styles, "DATA_DIR", tmp_path)
    styles._catalog.cache_clear()
    yield tmp_path
    styles._catalog.cache_clear()


def test_cache_and_return_values_cannot_be_mutated_by_callers(catalog_copy: Path) -> None:
    original = styles.load_all()
    changed = styles.load_all()
    changed[0]["needs"].append("prompt")
    styles.get(original[0]["id"])["inputs"].clear()
    styles.by_function("motion")[0]["name"] = "改名"
    styles.grammars()[0]["needs"].append("summary")
    assert styles.load_all() == original
    assert styles.grammars()[0]["needs"] == []
    (catalog_copy / "opus-videos.json").write_text("broken", encoding="utf-8")
    assert styles.load_all() == original  # 查询使用首次读取的缓存。
    assert any("opus-videos.json: 无法读取 JSON" in problem for problem in styles.validate())


def test_validation_collects_contract_errors_together(catalog_copy: Path) -> None:
    path = catalog_copy / "huashu-art-motion.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["styles"][0]
    del entry["summary"]
    del data["source"]["license"]
    entry.update(id="Bad_ID", function="wrong", aspect="2:1", prompt="No placeholder")
    data["grammars"][0]["id"] = "Bad_ID"
    path.write_text(json.dumps(data), encoding="utf-8")
    path = catalog_copy / "handraw.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source"]["attribution"] = None
    data["styles"][0]["attribution"] = None
    path.write_text(json.dumps(data), encoding="utf-8")
    errors = "\n".join(styles.validate())
    for expected in ("缺少字段 summary", "source.license", "id 格式", "id 重复", "function 与", "prompt 没有", "aspect 不在", "handraw source.attribution", "handraw attribution"):
        assert expected in errors


@pytest.mark.parametrize("bad", [None, [], {"source": [], "styles": None}, {"styles": [None, {"id": [], "function": [], "needs": [1], "aspect": []}]}])
def test_malformed_shapes_return_errors_instead_of_crashing(catalog_copy: Path, bad: object) -> None:
    (catalog_copy / "opus-videos.json").write_text(json.dumps(bad), encoding="utf-8")
    assert styles.validate()


def test_missing_prompt_is_explicit_and_does_not_hide_other_errors(catalog_copy: Path) -> None:
    path = catalog_copy / "opus-videos.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["styles"][0].update(prompt="", needs=["prompt"], listed=False)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert styles.validate() == []
    data["styles"][0]["aspect"] = "unknown"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("aspect" in error for error in styles.validate())


def test_image_requires_topic_not_script(catalog_copy: Path) -> None:
    path = catalog_copy / "gpt-image.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["function"] = "image"
    data["styles"][0].update(function="image", inputs=["topic"])
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("prompt 没有 {topic}" in error for error in styles.validate())


def test_missing_source_file_is_reported(catalog_copy: Path) -> None:
    (catalog_copy / "mg-styles.json").unlink()
    assert any("mg-styles.json: 无法读取 JSON" in error for error in styles.validate())


@pytest.mark.parametrize("listed", [None, 0, 1, "true", [], {}])
def test_listed_must_be_boolean(catalog_copy: Path, listed: object) -> None:
    path = catalog_copy / "opus-videos.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["styles"][0]["listed"] = listed
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("listed 必须是布尔值" in error for error in styles.validate())


def test_listed_cannot_hide_missing_prompt_behind_needs(catalog_copy: Path) -> None:
    path = catalog_copy / "huashu-art-motion.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["styles"][0]["listed"]
    data["grammars"][0].update(prompt="", needs=["prompt"])
    path.write_text(json.dumps(data), encoding="utf-8")
    errors = "\n".join(styles.validate())
    assert "缺少字段 listed" in errors
    assert "listed 为 true 时 needs 必须为空" in errors
    assert "listed 为 true 时 prompt 必须包含 {script}" in errors
