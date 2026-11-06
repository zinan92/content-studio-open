"""YouTube 封面：视频传上去以后，用同一份授权把打包里定稿的 16:9 封面设上去。

9/29 以前上传 YouTube 不带封面，YouTube 从视频里随便截一帧。上传脚本在 content-ops 里，那边的仓库
有 Codex 正在做的活，这里不去改它：上传拿到 video_id 以后，工作台自己调 thumbnails.set。
授权 `youtube.upload` 就够（thumbnails.set 认这个权限）；频道要做过手机验证才能用自定义封面。
YouTube 封面最大 2 MB：PNG 大于 2 MB 先转成 JPEG。

用 content-ops 的 venv 跑（它装了 google-api-python-client），所以这个文件不 import content_studio：
    <content-ops>/.venv/bin/python youtube_thumb.py --video-id ID --image cover.png --token token.json
最后一行打一行 JSON：{"ok": true} 或 {"ok": false, "message": "..."}。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

MAX_BYTES = 2 * 1024 * 1024


def fit_size(image: Path, workdir: Path) -> Path:
    """大于 2 MB 就用 sips 转成 JPEG（质量从 90 往下试），尺寸不动。"""
    if image.stat().st_size <= MAX_BYTES:
        return image
    for quality in (90, 82, 74):
        out = workdir / f"thumb-{quality}.jpg"
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality), str(image), "--out", str(out)],
                       capture_output=True, check=False)
        if out.is_file() and out.stat().st_size <= MAX_BYTES:
            return out
    raise RuntimeError("封面图太大，转成 JPEG 也超过 2 MB")


def explain(status: int, text: str) -> str:
    if status == 403:
        return "YouTube 不让这个频道用自定义封面（要先在 YouTube 做手机验证），视频已经传上去了，封面去 YouTube Studio 手动换"
    if status == 404:
        return "YouTube 还找不到这条视频（刚传完偶尔会这样），去 YouTube Studio 手动换封面"
    return f"YouTube 拒绝了封面（{status}）：{text[:160]}"


def set_thumbnail(video_id: str, image: Path, token: Path) -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    # 按 token 自己记着的权限加载，不传 scopes（传了会把刷新出来的 token 缩成那几项）
    creds = Credentials.from_authorized_user_info(json.loads(token.read_text(encoding="utf-8")))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    with tempfile.TemporaryDirectory() as tmp:
        upload = fit_size(image, Path(tmp))
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(upload))).execute()
        except HttpError as exc:
            return {"ok": False, "message": explain(int(getattr(exc.resp, "status", 0) or 0), str(exc))}
    return {"ok": True, "message": "封面设好了"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    try:
        result = set_thumbnail(args.video_id, Path(args.image), Path(args.token))
    except Exception as exc:  # noqa: BLE001 - 一句话交回发布台
        result = {"ok": False, "message": f"封面没设上：{exc}"[:240]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
