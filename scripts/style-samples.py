#!/usr/bin/env python3
"""串行生成已上架生图风格的同主题样图，已有 WebP 自动跳过。

python3 scripts/style-samples.py --function image --limit 2
--limit 限制实际尝试数（含失败，不含跳过）；--only 接受逗号分隔的风格 ID。
输出到 ~/.config/content-studio/style-samples/<id>.webp 和追加式 log.jsonl；Ctrl-C 记下中断后退出，重跑可续接。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_studio.extras.tools import public, styles  # noqa: E402

DEFAULT_TOPIC = "一个人用 AI 做自媒体，像同时指挥一支小乐队"
IMAGE_INSTRUCTION = "只用 image_gen 生成一张，不要运行命令、不要保存或移动文件；生成后只回复『好了』"
from content_studio.extras.tools import gallery  # noqa: E402
OUT = gallery.samples_dir()  # 本机 ~/.config/content-studio/style-samples，不进仓库


def save_webp(source: Path, target: Path) -> None:
    """保留比例及透明度，不放大小图；成功编码后才出现最终文件。"""
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original)
        image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        if image.width > 1200:
            image = image.resize((1200, max(1, round(image.height * 1200 / image.width))), Image.Resampling.LANCZOS)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            image.save(temporary, "WEBP", quality=82, method=6)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def run(*, topic: str = DEFAULT_TOPIC, limit: int | None = None,
        only: set[str] | None = None, output: Path = OUT) -> dict:
    """每次仅调用一次 sandboxed_paint，失败不中断后续条目。"""
    if limit is not None and limit < 0:
        raise ValueError("limit 不能为负数")
    rows = [row for row in styles.load_all()
            if row.get("function") == "image" and row.get("listed") is True
            and (only is None or row["id"] in only)]
    if only is not None:
        missing = only - {row["id"] for row in rows}
        if missing:
            raise ValueError("以下 ID 不存在或不是已上架生图风格：" + ", ".join(sorted(missing)))
    output.mkdir(parents=True, exist_ok=True)
    counts = {"success": 0, "failed": 0, "skipped": 0, "interrupted": False}
    elapsed = 0.0
    try:
        for row in rows:
            if limit is not None and counts["success"] + counts["failed"] >= limit:
                break
            ident = row["id"]
            target = output / f"{ident}.webp"
            start = time.monotonic()
            status, error = "skipped", ""
            try:
                if not target.is_file():
                    print(f"生成 {ident} …", flush=True)
                    prompt = row["prompt"]
                    if row.get("needs") != [] or "{topic}" not in prompt:
                        raise ValueError("已上架生图风格仍有缺项或缺少 {topic}")
                    prompt = prompt.replace("{topic}", topic) + "\n\n" + IMAGE_INSTRUCTION
                    with tempfile.TemporaryDirectory(prefix=f".{ident}-", dir=output) as directory:
                        job = Path(directory).resolve()
                        public.CURRENT["dir"] = job
                        try:
                            shots, _ = public.sandboxed_paint(prompt, job)
                            if not shots:
                                raise ValueError("sandboxed_paint 没有返回图片")
                            save_webp(Path(shots[-1]), target)
                        finally:
                            public.CURRENT["dir"] = None
                    status = "success"
            except KeyboardInterrupt:
                status, error = "failed", "用户中断（Ctrl-C）"
                counts["interrupted"] = True
            except Exception as exc:
                status = "failed"
                error = " ".join(str(exc).split())[:300] or type(exc).__name__
            seconds = time.monotonic() - start
            counts[status] += 1
            if status != "skipped":
                elapsed += seconds
            record = {"id": ident, "status": status, "seconds": round(seconds, 3), "error": error}
            with (output / "log.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"{ident}: {status} ({seconds:.1f}s)" + (f" — {error}" if error else ""), flush=True)
            if counts["interrupted"]:
                break
    except KeyboardInterrupt:
        counts["interrupted"] = True
    finally:
        attempts = counts["success"] + counts["failed"]
        counts["average_seconds"] = elapsed / attempts if attempts else 0.0
        print(f"成功 {counts['success']} 条，失败 {counts['failed']} 条，跳过 {counts['skipped']} 条，"
              f"平均每条 {counts['average_seconds']:.1f} 秒（不含跳过）", flush=True)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--function", required=True, choices=["image"])
    parser.add_argument("--limit", type=int, help="最多尝试几条，不含已有样图")
    parser.add_argument("--only", help="仅生成这些 ID，用逗号分隔")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    args = parser.parse_args(argv)
    only = {ident.strip() for ident in args.only.split(",") if ident.strip()} if args.only is not None else None
    if only == set():
        parser.error("--only 不能为空")
    try:
        result = run(topic=args.topic, limit=args.limit, only=only)
    except ValueError as exc:
        parser.error(str(exc))
    return 130 if result["interrupted"] else 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
