"""X 主页资料：读现在的名字和简介，把工作台里写好的改上去。

9/30：X 新版接口（/2/users/me 带 description）用 作者 的密钥返回 401，但老的 v1.1 账号接口读得到
（verify_credentials 返回名字、简介、位置）。改资料走 v1.1 的 account/update_profile。
只在 作者 点了「改到 X 上」时调用——这是改他公开的主页。
"""
from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from ...x_post import XError, authorization_header, load_credentials

V11 = "https://api.x.com/1.1/account"
KEEP = ("name", "screen_name", "description", "location", "url", "followers_count")


def _call(method: str, url: str, params: dict[str, str] | None, creds: dict[str, str] | None, opener: Any) -> dict[str, Any]:
    creds = creds or load_credentials()
    data = urllib.parse.urlencode(params or {}, quote_via=urllib.parse.quote).encode() if method == "POST" else None
    request = urllib.request.Request(url, data=data, method=method)
    # 表单参数要进 OAuth 签名
    request.add_header("Authorization", authorization_header(method, url, creds, query=params or None))
    if data is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=30) as response:
            body = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:240]
        if exc.code in (401, 403):
            raise XError(f"X 不让这个密钥改主页（{exc.code}）：去 x.com 的「编辑个人资料」手动改。{detail}") from exc
        raise XError(f"X 返回 {exc.code}：{detail}") from exc
    except OSError as exc:
        raise XError(f"连不上 X：{exc}") from exc
    return {k: body.get(k) for k in KEEP}


def read(*, creds: dict[str, str] | None = None, opener: Any = None) -> dict[str, Any]:
    return _call("GET", f"{V11}/verify_credentials.json", None, creds, opener)


def update(*, name: str, bio: str, link: str = "", creds: dict[str, str] | None = None, opener: Any = None) -> dict[str, Any]:
    """只改给了的字段：名字、简介、链接。位置、头像、背景图不碰。"""
    params = {k: v for k, v in (("name", name.strip()), ("description", bio.strip()), ("url", link.strip())) if v}
    if not params:
        raise XError("没有要改的")
    return _call("POST", f"{V11}/update_profile.json", params, creds, opener)
