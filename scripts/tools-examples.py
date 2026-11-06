#!/usr/bin/env python3
"""把「单点功能」真跑出来的几次收进仓库，当页面上的样例（10/10 作者：先给用户看结果）。

用法：python3 scripts/tools-examples.py review=20261010-000027-1 style=20261010-000027-10,20261010-000027-11 …
每个功能给一次或几次运行编号（生图风格给 6 次，一种风格一次）。运行在 ~/.config/content-studio/tools/<编号>/。
图转成 1400 宽以内的 webp，写进 src/content_studio/extras/tools/examples/，manifest.json 记输入和结果。
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/content_studio/extras/tools/examples"
sys.path.insert(0, str(ROOT / "src"))

from content_studio.extras.tools import tools  # noqa: E402

MAX_W = 1400
EXCERPT = {"teardown": 480}  # 别人的作品只放一段节选


def webp(src: Path, name: str) -> str:
    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        im.save(OUT / name, "WEBP", quality=82, method=6)
        return name


def collect(key: str, run_id: str, n: int) -> dict:
    folder = tools.root() / run_id
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    if run["tool"] != key or run["state"] != "done":
        raise SystemExit(f"{run_id} 不是一次做完的「{key}」：{run['tool']} {run['state']}")
    result = dict(run["result"])
    images = []
    for i, rel in enumerate(result.get("images") or [], 1):
        name = webp(folder / rel, f"{key}-{n}-{i:02d}.webp")
        images.append(name)
        if result.get("markdown"):
            result["markdown"] = result["markdown"].replace(f"]({rel})", f"]({name})")
    result["images"] = images
    if key == "clean" and "diff" not in result:  # 早于逐字对比的那次运行：照样补上
        result["diff"] = tools.diff(run["input"]["text"], result["copy"])
    inp = dict(run["input"])
    chars = {k: len("".join(v.split())) for k, v in inp.items() if isinstance(v, str)}
    if key in EXCERPT:  # 别人的视频：只留开头一段，页面上照样显示全文多少字
        inp["text"] = inp["text"][:EXCERPT[key]] + "……"
    return {"input": inp, "chars": chars, "result": result, "seconds": _seconds(run)}


def _seconds(run: dict) -> int | None:
    from datetime import datetime

    try:
        return round((datetime.fromisoformat(run["finished"]) - datetime.fromisoformat(run["started"])).total_seconds())
    except (KeyError, ValueError):
        return None


def main(args: list[str]) -> None:
    pairs = dict(a.split("=", 1) for a in args)
    unknown = set(pairs) - set(tools.BY_KEY)
    if unknown:
        raise SystemExit(f"没有这些功能：{unknown}")
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    manifest = {}
    for key, ids in pairs.items():
        samples = [collect(key, rid, n) for n, rid in enumerate(ids.split(","), 1)]
        manifest[key] = samples
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"{len(manifest)} 个功能，{len(list(OUT.glob('*.webp')))} 张图，共 {size / 1e6:.1f} MB → {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
