from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
import urllib.error
import urllib.parse

import pytest

from content_studio import x_post


CREDS = {"api_key": "key", "api_secret": "ksec", "access_token": "tok", "access_secret": "tsec"}


def test_signature_matches_a_hand_computed_hmac() -> None:
    """The whole channel rests on this: a wrong base string means every post 401s."""
    header = x_post.authorization_header("POST", x_post.ENDPOINT, CREDS, nonce="abc", timestamp="1700000000")
    got = dict(part.split("=", 1) for part in header[len("OAuth "):].split(", "))
    signature = urllib.parse.unquote(got["oauth_signature"].strip('"'))

    params = {
        "oauth_consumer_key": "key", "oauth_nonce": "abc", "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1700000000", "oauth_token": "tok", "oauth_version": "1.0",
    }
    normalized = "&".join(f"{k}={params[k]}" for k in sorted(params))
    base = "&".join(["POST", urllib.parse.quote(x_post.ENDPOINT, safe="~"), urllib.parse.quote(normalized, safe="~")])
    expected = base64.b64encode(hmac.new(b"ksec&tsec", base.encode(), hashlib.sha1).digest()).decode()
    assert signature == expected
    # the JSON body must NOT be signed; only oauth_* params are in the base string
    assert "text" not in base


def test_cjk_counts_double_so_a_chinese_post_is_not_silently_truncated() -> None:
    assert x_post.weighted_length("你好hello") == 9
    with pytest.raises(x_post.XError, match="超过 X 的 280"):
        x_post.post_tweet("中" * 141, creds=CREDS)
    with pytest.raises(x_post.XError, match="空的"):
        x_post.post_tweet("   ", creds=CREDS)


def test_missing_credentials_name_exactly_what_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text("x:\n  api_key: k\n  api_secret: s\n", encoding="utf-8")
    with pytest.raises(x_post.XError, match="access_token, access_secret"):
        x_post.load_credentials(path)
    path.write_text("x:\n  api_key: k\n  api_secret: s\n  access_token: t\n  access_secret: ts\n", encoding="utf-8")
    assert x_post.load_credentials(path)["access_token"] == "t"
    with pytest.raises(x_post.XError, match="读不到密钥文件"):
        x_post.load_credentials(tmp_path / "nope.yaml")


def test_x_errors_are_translated_into_something_park_can_act_on() -> None:
    class Fail:
        def __init__(self, code): self.code = code
        def __call__(self, *a, **k):
            raise urllib.error.HTTPError(x_post.ENDPOINT, self.code, "no", {}, None)

    with pytest.raises(x_post.XError, match="Read and Write"):
        x_post.post_tweet("hi", creds=CREDS, opener=Fail(401))
    with pytest.raises(x_post.XError, match="每月有发帖上限"):
        x_post.post_tweet("hi", creds=CREDS, opener=Fail(429))
    with pytest.raises(x_post.XError, match="余额用完了.*console.x.com"):  # 10/12 X 回 402 credits depleted
        x_post.post_tweet("hi", creds=CREDS, opener=Fail(402))


def test_a_successful_post_returns_a_link_park_can_open() -> None:
    class OK:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"data": {"id": "1899", "text": "hi"}}).encode()

    got = x_post.post_tweet("hi", creds=CREDS, opener=lambda *a, **k: OK())
    assert got == {"id": "1899", "url": "https://x.com/i/web/status/1899"}


def test_long_posts_allow_up_to_the_premium_limit() -> None:
    with pytest.raises(x_post.XError, match="超过 X 的 25000"):
        x_post.post_tweet("中" * 12_501, long=True, creds=CREDS)
    sent = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"data":{"id":"7"}}'

    r = x_post.post_tweet("中" * 2000, long=True, creds=CREDS, opener=lambda req, timeout: sent.append(req) or Resp())
    assert r["id"] == "7" and len(sent) == 1


def test_reply_uses_existing_signed_endpoint():
    sent = []
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"data":{"id":"8"}}'
    x_post.post_tweet("reply", in_reply_to_tweet_id="7", creds=CREDS,
                      opener=lambda req, timeout: sent.append(req) or Resp())
    assert json.loads(sent[0].data)["reply"] == {"in_reply_to_tweet_id": "7"}
    assert sent[0].get_header("Authorization").startswith("OAuth ")
