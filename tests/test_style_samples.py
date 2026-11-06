"""样图脚本仅替换主题，串行调用既有沙盒；此处全部使用假的出图。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image
import pytest


@pytest.fixture
def samples(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/style-samples.py"
    spec = importlib.util.spec_from_file_location("style_samples", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(module.public.CURRENT, "dir", None)
    return module


def row(ident, **changes):
    return {"id": ident, "function": "image", "listed": True, "needs": [],
            "prompt": 'Draw {topic}; retain literal {"color": "red"}.', **changes}


def records(output):
    return [json.loads(line) for line in (output / "log.jsonl").read_text().splitlines()]


def test_filters_skips_logs_replaces_topic_and_uses_last_image(samples, tmp_path, monkeypatch):
    rows = [row("existing"), row("new"), row("hidden", listed=False), row("missing", listed=None),
            row("movie", function="video"), row("motion", function="motion")]
    monkeypatch.setattr(samples.styles, "load_all", lambda: rows)
    existing = tmp_path / "existing.webp"
    Image.new("RGB", (8, 8), "green").save(existing, "WEBP")
    original = existing.read_bytes()
    calls = []

    def paint(prompt, cwd):
        assert samples.public.CURRENT["dir"] == cwd
        assert cwd.is_dir()
        calls.append((prompt, cwd))
        first, last = cwd / "first.png", cwd / "last.png"
        Image.new("RGB", (10, 10), "red").save(first)
        Image.new("RGBA", (2400, 1600), (0, 0, 255, 100)).save(last)
        return [first, last], "好了"

    monkeypatch.setattr(samples.public, "sandboxed_paint", paint)
    result = samples.run(output=tmp_path, topic="演示主题")
    assert (result["success"], result["failed"], result["skipped"]) == (1, 0, 1)
    assert len(calls) == 1
    prompt, job = calls[0]
    assert "演示主题" in prompt and "{topic}" not in prompt
    assert '{"color": "red"}' in prompt
    assert samples.IMAGE_INSTRUCTION in prompt
    assert existing.read_bytes() == original
    with Image.open(tmp_path / "new.webp") as image:
        assert image.format == "WEBP" and image.size == (1200, 800)
        assert image.getpixel((0, 0))[2] > 240  # 最后一张蓝图，不是第一张红图。
        assert image.getpixel((0, 0))[3] == 100
    assert not job.exists() and samples.public.CURRENT["dir"] is None
    log = records(tmp_path)
    assert [(item["id"], item["status"]) for item in log] == [("existing", "skipped"), ("new", "success")]
    assert all(item["seconds"] >= 0 and item["error"] == "" for item in log)
    samples.run(output=tmp_path, topic="演示主题")
    assert len(calls) == 1 and len(records(tmp_path)) == 4  # 续跑追加，不覆盖。


def test_failure_does_not_stop_next_style_and_limit_counts_attempts(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(samples.styles, "load_all", lambda: [row("existing"), row("bad"), row("good"), row("later")])
    (tmp_path / "existing.webp").write_bytes(b"already present")
    calls = []

    def paint(prompt, cwd):
        calls.append(cwd)
        if len(calls) == 1:
            raise RuntimeError("failed\nsecond line")
        shot = cwd / "image.png"
        Image.new("RGB", (20, 10), "blue").save(shot)
        return [shot], "好了"

    monkeypatch.setattr(samples.public, "sandboxed_paint", paint)
    result = samples.run(output=tmp_path, limit=2)
    assert (result["success"], result["failed"], result["skipped"]) == (1, 1, 1)
    assert len(calls) == 2 and all(not cwd.exists() for cwd in calls)
    assert not (tmp_path / "bad.webp").exists() and not (tmp_path / "later.webp").exists()
    assert (tmp_path / "good.webp").exists()
    assert records(tmp_path)[1]["error"] == "failed second line"
    assert samples.public.CURRENT["dir"] is None


def test_only_selects_requested_ids_and_unknown_id_fails_early(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(samples.styles, "load_all", lambda: [row("one"), row("two"), row("hidden", listed=False)])
    calls = []

    def paint(prompt, cwd):
        calls.append(prompt)
        shot = cwd / "image.png"
        Image.new("RGB", (20, 10)).save(shot)
        return [shot], "好了"

    monkeypatch.setattr(samples.public, "sandboxed_paint", paint)
    result = samples.run(output=tmp_path, only={"two"})
    assert result["success"] == 1 and [item["id"] for item in records(tmp_path)] == ["two"]
    with pytest.raises(ValueError, match="不是已上架"):
        samples.run(output=tmp_path, only={"hidden", "typo"})
    assert len(calls) == 1
    assert samples.DEFAULT_TOPIC in calls[0]


@pytest.mark.parametrize("failure", ["empty", "broken", "interrupt"])
def test_bad_output_and_ctrl_c_leave_no_webp_and_reset_current(samples, tmp_path, monkeypatch, failure):
    monkeypatch.setattr(samples.styles, "load_all", lambda: [row("first"), row("second")])
    calls = []

    def paint(prompt, cwd):
        calls.append(cwd)
        if failure == "interrupt":
            raise KeyboardInterrupt
        if failure == "empty":
            return [], "好了"
        shot = cwd / "broken.png"
        shot.write_bytes(b"not an image")
        return [shot], "好了"

    monkeypatch.setattr(samples.public, "sandboxed_paint", paint)
    result = samples.run(output=tmp_path)
    expected = 1 if failure == "interrupt" else 2
    assert result["failed"] == expected and len(calls) == expected
    assert result["interrupted"] == (failure == "interrupt")
    assert len(records(tmp_path)) == expected and not list(tmp_path.glob("*.webp"))
    assert samples.public.CURRENT["dir"] is None
    assert all(not cwd.exists() for cwd in calls)


def test_zero_limit_does_not_generate(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(samples.styles, "load_all", lambda: [row("one")])
    monkeypatch.setattr(samples.public, "sandboxed_paint", lambda *args: pytest.fail("must not generate"))
    result = samples.run(output=tmp_path, limit=0)
    assert result["average_seconds"] == 0 and result["success"] == 0
