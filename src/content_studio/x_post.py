"""Post one text tweet to X, using 作者's own developer credentials.

Text only: he said 主要发文字, and video would need the chunked media-upload endpoint and a
paid tier. Free tier allows a few hundred posts a month, which is far more than he needs.

Auth is OAuth 1.0a User Context — the only scheme that lets an app post *as* 作者 with static
credentials (OAuth 2.0 user context needs a refresh dance and a browser). Signing it takes
~30 lines of stdlib, which is cheaper than adding requests_oauthlib to a service that runs
under launchd.

Run as a module so publisher.py can shell out to it like every other channel:
    python3 -m content_studio.x_post --text "..."
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import time
from typing import Any
import urllib.parse
import urllib.request

SECRETS_PATH = Path(os.environ.get("CONTENT_STUDIO_SECRETS", "~/.config/content-studio/secrets.yaml")).expanduser()
ENDPOINT = "https://api.x.com/2/tweets"
MAX_WEIGHTED = 280
MAX_LONG = 25_000  # Premium 账号一条长帖的上限；中文也按两个算，宁严不松（10/7 长帖实验）
NEEDED = ("api_key", "api_secret", "access_token", "access_secret")
# 10/12 15:37 起 X 每次都回 402 credits depleted：API 是按次付费的，余额用完了什么都发不出去，只能他去充值
CREDITS_OUT = "X API 余额用完了（402）"
CREDITS_HELP = f"{CREDITS_OUT}：去 console.x.com 充值，充好回 X 页点「充值好了，接着发」"


class XError(RuntimeError):
    """Posting could not proceed; the message is shown to 作者."""


def load_credentials(path: Path | None = None) -> dict[str, str]:
    target = path or SECRETS_PATH
    try:
        import yaml

        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise XError(f"读不到密钥文件 {target}：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - malformed YAML
        raise XError(f"密钥文件格式不对：{exc}") from exc
    creds = (data.get("x") or data.get("twitter") or {}) if isinstance(data, dict) else {}
    missing = [k for k in NEEDED if not str(creds.get(k) or "").strip()]
    if missing:
        raise XError(f"secrets.yaml 的 x: 段里还缺 {', '.join(missing)}；在 developer.x.com 建应用后填进去")
    return {k: str(creds[k]).strip() for k in NEEDED}


def weighted_length(text: str) -> int:
    """X counts CJK as 2, everything else as 1 — same rule 文案页 already uses."""
    import re

    return sum(2 if re.match(r"[⺀-鿿＀-￯　-〿]", ch) else 1 for ch in text)


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def authorization_header(method: str, url: str, creds: dict[str, str], *, nonce: str | None = None, timestamp: str | None = None,
                         query: dict[str, str] | None = None) -> str:
    """OAuth 1.0a signature. A JSON body is not part of the base string — only the oauth_* params
    and, for a GET, the query parameters (``url`` stays without them)."""
    params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    signed = {**params, **(query or {})}
    normalized = "&".join(f"{_quote(k)}={_quote(signed[k])}" for k in sorted(signed))
    base = "&".join([method.upper(), _quote(url), _quote(normalized)])
    key = f"{_quote(creds['api_secret'])}&{_quote(creds['access_secret'])}".encode()
    params["oauth_signature"] = base64.b64encode(hmac.new(key, base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_quote(k)}="{_quote(params[k])}"' for k in sorted(params))


def post_tweet(text: str, *, long: bool = False, quote_tweet_id: str | None = None, in_reply_to_tweet_id: str | None = None,
               creds: dict[str, str] | None = None, opener: Any = None) -> dict[str, Any]:
    """long=True 是长帖：同一个接口，账号是 Premium 就能发到 MAX_LONG。quote_tweet_id：发成引用帖（10/8 X 热榜「引用它」）。"""
    text = text.strip()
    if not text:
        raise XError("推文是空的")
    limit = MAX_LONG if long else MAX_WEIGHTED
    if weighted_length(text) > limit:
        raise XError(f"这条 {weighted_length(text)} 字（中文算两个），超过 X 的 {limit}")
    creds = creds or load_credentials()
    body = json.dumps({"text": text, **({"quote_tweet_id": quote_tweet_id} if quote_tweet_id else {}),
                       **({"reply": {"in_reply_to_tweet_id": in_reply_to_tweet_id}} if in_reply_to_tweet_id else {})}).encode()
    request = urllib.request.Request(ENDPOINT, data=body, method="POST")
    request.add_header("Authorization", authorization_header("POST", ENDPOINT, creds))
    request.add_header("Content-Type", "application/json")
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:  # noqa: PERF203 - the body carries X's reason
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 401:
            raise XError(f"X 拒绝了这次调用（401）：密钥不对，或者应用权限不是 Read and Write。{detail}") from exc
        if exc.code == 429:
            raise XError("X 说超额了（429）：免费版每月有发帖上限，等额度恢复再发") from exc
        if exc.code == 402:
            raise XError(CREDITS_HELP) from exc
        raise XError(f"X 返回 {exc.code}：{detail}") from exc
    except OSError as exc:
        raise XError(f"连不上 X：{exc}") from exc
    if payload.get("errors") or re.search(r"automated|spam|restricted", json.dumps(payload), re.I):
        raise XError(f"X 拒绝了回复：{json.dumps(payload, ensure_ascii=False)[:300]}")
    tweet_id = ((payload or {}).get("data") or {}).get("id")
    return {"id": tweet_id, "url": f"https://x.com/i/web/status/{tweet_id}" if tweet_id else None}


def main() -> int:
    parser = argparse.ArgumentParser(description="发一条纯文字推文到 X")
    parser.add_argument("--text", required=True)
    parser.add_argument("--check", action="store_true", help="只检查密钥齐不齐，不发")
    args = parser.parse_args()
    try:
        if args.check:
            load_credentials()
            print(json.dumps({"ok": True, "weighted": weighted_length(args.text)}, ensure_ascii=False))
            return 0
        print(json.dumps({"ok": True, **post_tweet(args.text)}, ensure_ascii=False))
    except XError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
