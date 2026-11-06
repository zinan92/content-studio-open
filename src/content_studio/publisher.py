"""Publish a finished video to a platform, only after 作者 confirms the exact payload.

Two steps: prepare (freeze video file, copy and mode) → confirm (run). The channels are
the content-ops scripts 作者 already uses; the workbench never logs in for him.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

from . import conf
from .paths import config_dir

CONTENT_OPS = Path(os.environ.get("CONTENT_OPS_PATH", "~/work/content-ops")).expanduser()
PUBLISH_ROOT = conf.path("paths.publish_toolkit")
CONFIRM_WINDOW_SECONDS = 30 * 60
RUN_TIMEOUT_SECONDS = 45 * 60

XINGQIU = conf.path("paths.xingqiu")
# 抖音半自动用的 Chrome 配置：独立一份，不碰 作者 平时的 Chrome，也不和读作品列表的那份（douyin-chrome）抢


def _secret(section: str, key: str) -> str:
    try:
        import yaml

        data = yaml.safe_load(conf.path("paths.secrets").read_text(encoding="utf-8")) or {}
        return str((data.get(section) or {}).get(key) or "")
    except Exception:  # noqa: BLE001 - 没配就是空，调用方会说缺什么
        return ""


def _gzh_html(article: str) -> str:
    if not article:
        return ""
    from . import gzh_layout

    page = gzh_layout.current(Path(article))
    return str(page) if page else ""


# 9/29 作者：「都推到草稿箱，我再确认几天再说。」每个通道只留存草稿（YouTube 是私享），
# 直接发布 / 公开的模式先拿掉；最后一下他在平台后台自己点。
PUBLISHERS: dict[str, dict[str, Any]] = {
    "channels": {
        "label": "视频号",
        "needs": ("playwright",),
        "copy_key": "channels",
        "credential": PUBLISH_ROOT / "cookies/tencent_uploader/account.json",
        # 2026-09-21 作者：腾讯最近两个月开始封自动发布，以前能用。重新登录治不好平台侧的限制，
        # 所以这里不是「登录过期」——通道留着（万一他记错了或者以后解封），但按钮由 blocked 状态挡住。
        "blocked": "视频号最近开始限制自动发布，先手动上传",
        "login_hint": f"python3 {CONTENT_OPS}/scripts/push_wechat_channels_draft.py --login-only",
        "modes": {
            "draft": {"label": "存为视频号草稿", "argv": ["python3", str(CONTENT_OPS / "scripts/push_wechat_channels_draft.py"), "--headless", "--video", "{video}", "--title", "{title}", "--description", "{body}"]},
        },
    },
    "bilibili": {
        "label": "B 站",
        "needs": ("playwright",),
        "copy_key": "bilibili",
        "credential": PUBLISH_ROOT / "cookies/bilibili_creator.json",
        # 文件日期只能猜「大概过期了」，这条命令是真去问 B 站。2026-09-21 实测：cookie
        # 已经 4 个月没动，但依然 valid——只看 mtime 会把能用的通道报成要重新登录。
        "probe": [str(PUBLISH_ROOT / ".venv/bin/python"), str(PUBLISH_ROOT / "sau_cli.py"), "bilibili", "check", "--account", "creator"],
        "probe_ok": "valid",
        "login_hint": f"cd {PUBLISH_ROOT} && ./.venv/bin/python sau_cli.py bilibili login --account creator",
        "login_argv": [str(PUBLISH_ROOT / ".venv/bin/python"), str(PUBLISH_ROOT / "sau_cli.py"), "bilibili", "login", "--account", "creator"],
        "login_cwd": str(PUBLISH_ROOT),
        "modes": {
            "upload": {"label": "投稿（B 站审核后公开）", "argv": ["python3", str(CONTENT_OPS / "scripts/bilibili_web_upload.py"), "--headless", "upload", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}", "--cover", "{cover}"]},
        },
    },
    # 10/20 作者：「X 的 API 拿掉，X 也是手动上传的」——没有 X 通道，X 和视频号、小红书一样他自己传。
    "miniprogram": {
        "label": "研习室",
        "copy_key": "miniprogram",
        # 9/24 作者：研习室要一键发。云函数 admin-api 认「工作台钥匙」（研习室小程序仓库#338），
        # 本机脚本用网页后台同一套转换；同一选题再发会更新同一篇（brief_id 固定）。
        "credential": conf.path("paths.secrets"),
        "needs_keys": ("yanxishi", ("workbench_key", "env_id")),
        "secret_env": {"WORKBENCH_KEY": ("yanxishi", "workbench_key")},
        "login_hint": "研习室工作台钥匙在 ~/.config/content-studio/secrets.yaml 的 yanxishi: 段（workbench_key、env_id），云函数 admin-api 存它的哈希",
        "no_video": True,
        "needs_article": True,
        "modes": {
            "draft": {"label": "存成研习室草稿", "argv": ["node", str(XINGQIU / "scripts/workbench-submit.mjs"), "--md", "{article}", "--html", "{gzh_html}", "--env", "{yanxishi_env}", "--brief-id", "{brief_id}"]},
        },
    },
    "wechat_mp": {
        "label": "公众号",
        "copy_key": "wechat_mp",
        # 9/24 作者：公众号要一键发。研习室那篇文章排好版（橄榄手记）+ 公众号封面，进草稿箱；
        # 群发由 作者 在公众号后台自己点。
        "credential": conf.path("paths.secrets"),
        "needs_keys": ("wechat", ("appid", "secret")),
        "login_hint": "公众号后台 → 设置与开发 → 基本配置：AppID、AppSecret 写进 ~/.config/content-studio/secrets.yaml 的 wechat: 段，并把这台机器的 IP 加进白名单",
        "no_video": True,
        "needs_article": True,
        "modes": {
            # 9/27 作者：只存草稿箱。没看过排版效果不敢直接发，而且每次都要去公众号后台确认一遍再群发。
            "draft": {"label": "存进公众号草稿箱", "argv": ["python3", "-m", "content_studio.extras.autopost.wechat_publish", "--article", "{article}", "--cover", "{cover}"]},
        },
    },
    "youtube": {
        "label": "YouTube",
        "copy_key": "youtube",
        "credential": conf.path("paths.youtube_token"),
        "probe": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "check"],
        "probe_ok": "token_valid",
        "login_hint": f"python3 {CONTENT_OPS}/scripts/youtube_channel.py auth",
        # 10/3：工作台里点「登录 YouTube」直接跑它——弹出浏览器选频道、点允许，token 写好就退出
        "login_argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "auth"],
        "modes": {
            "private": {"label": "上传为私享（自己先看）", "argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "upload-private", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}"]},
            # 9/29 YouTube 降权：补发时直接公开，不占 作者 的时间
            "public": {"label": "直接公开上传", "argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "upload", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}", "--privacy-status", "public"]},
        },
    },
}


class PublishError(ValueError):
    """Publishing cannot proceed; the message is shown to 作者."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def readiness(publishers: dict[str, dict[str, Any]] = PUBLISHERS, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or now_utc()
    result = {}
    for key, spec in publishers.items():
        if spec.get("blocked"):
            # A platform-side block: the credential may be perfectly fine and re-scanning a QR
            # code fixes nothing. Saying 「要重新登录」 here would send 作者 off on a dead errand.
            result[key] = {"label": spec["label"], "credential": True, "age_days": None, "likely_expired": True,
                           "blocked": True, "note": spec["blocked"], "login_hint": "", "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")),
                           "modes": {m: v["label"] for m, v in spec["modes"].items()}}
            continue
        if spec.get("login_in_window"):
            result[key] = _window_readiness(spec)
            continue
        path = Path(spec["credential"])
        section = spec.get("needs_keys")
        if section and path.is_file():
            # A secrets file exists for other reasons (公众号 keys live there too), so its
            # presence proves nothing about X. Check the actual keys.
            try:
                import yaml

                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                have = (data.get(section[0]) or {}) if isinstance(data, dict) else {}
                missing = [k for k in section[1] if not str(have.get(k) or "").strip()]
            except Exception:  # noqa: BLE001 - unreadable means unconfigured
                missing = list(section[1])
            if missing:
                result[key] = {"label": spec["label"], "credential": False, "age_days": None, "likely_expired": True,
                               "setup": True, "note": f"还缺 {', '.join(missing)}", "login_hint": spec["login_hint"], "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")),
                               "modes": {m: v["label"] for m, v in spec["modes"].items()}}
                continue
        if path.is_file():
            updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            age = (now - updated).days
            stamp = updated.astimezone().strftime("%m-%d")
            # 有探测命令就以它为准：cookie 放了四个月照样可能有效，光看日期会误报。
            from .channel_probe import probe as probe_channel

            checked = probe_channel(key, spec)
            if checked is not None and checked.get("ok") is not None:
                expired = not checked["ok"]
                note = (f"登录信息更新于 {stamp}，刚才问过平台，能用" if checked["ok"]
                        else f"登录已失效（更新于 {stamp}），需要重新登录")
            else:
                expired = age > 30
                note = f"登录信息更新于 {stamp}" + ("，已超过 30 天，很可能需要重新登录" if expired else "")
            result[key] = {"label": spec["label"], "credential": True, "age_days": age, "likely_expired": expired, "note": note, "login_hint": spec["login_hint"],
                           "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")), "modes": {m: v["label"] for m, v in spec["modes"].items()}}
        else:
            result[key] = {"label": spec["label"], "credential": False, "age_days": None, "likely_expired": True, "note": "还没有登录信息", "login_hint": spec["login_hint"],
                           "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")), "modes": {m: v["label"] for m, v in spec["modes"].items()}}
    return result


def _window_readiness(spec: dict[str, Any]) -> dict[str, Any]:
    """登录在弹出的窗口里做：不看 cookie 日期，只看跑脚本的工具在不在。"""
    base = {"label": spec["label"], "age_days": None, "login_hint": spec["login_hint"], "no_video": False, "needs_article": False,
            "modes": {m: v["label"] for m, v in spec["modes"].items()}}
    runner = Path(next(iter(spec["modes"].values()))["argv"][0])
    if not runner.is_file():
        return {**base, "credential": False, "likely_expired": True, "setup": True,
                "note": f"发布工具没装好：找不到 {runner}"}
    profile = Path(spec["credential"])
    return {**base, "credential": True, "likely_expired": False,
            "note": "登录记在专用的 Chrome 里" if profile.is_dir() and any(profile.iterdir()) else "第一次会在弹出的 Chrome 里扫码登录"}


def build_payload(platform: str, mode: str, *, video: Path | None, copy: dict[str, Any] | None, publishers: dict[str, dict[str, Any]] = PUBLISHERS,
                  article: Path | None = None, cover: Path | None = None, cover_portrait: Path | None = None,
                  traffic: dict[str, list[str]] | None = None, product: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = publishers.get(platform)
    if spec is None:
        raise PublishError("这个平台还不能一键发布")
    if mode not in spec["modes"]:
        raise PublishError("发布方式无效")
    if spec.get("needs_article"):
        if article is None or not article.is_file():
            raise PublishError("先在「研习室文章」写好文章，X 发的是图文文章")
        heading = next((l[2:].strip() for l in article.read_text(encoding="utf-8").splitlines() if l.startswith("# ")), "")
        return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
                "video": "", "video_mb": 0, "title": heading or article.stem, "body": "", "tags": [],
                "article": str(article), "cover": str(cover) if cover and cover.is_file() else ""}
    text_only = bool(spec.get("no_video"))
    if not text_only and (video is None or not video.is_file()):
        raise PublishError("找不到成片文件")
    # 这个平台没单独写，就用共用的那份（补发的旧视频只种了抖音的标题和话题）
    entry = (copy or {}).get(spec["copy_key"]) or next(
        (e for e in (copy or {}).values() if isinstance(e, dict) and (e.get("title") or e.get("body"))), {})
    title = str(entry.get("title") or "").strip()
    body = str(entry.get("body") or "").strip()
    tags = [str(t).strip() for t in entry.get("tags") or [] if str(t).strip()]
    if traffic is not None:
        from .copypack import with_traffic

        tags = with_traffic(platform, tags, traffic)
    if product:
        from .copypack import with_product

        body = with_product(platform, body, product, tags)
    if text_only:
        # X 发的是正文本身，没有标题这一栏——要求填标题会把他卡在一个根本不存在的字段上。
        if not body:
            raise PublishError(f"先在「打包」页写好{spec['label']}的正文并保存")
        return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
                "video": "", "video_mb": 0, "title": title or body[:20], "body": body, "tags": tags}
    if not title:
        raise PublishError(f"先在「打包」页写好标题并保存")
    return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
            "video": str(video), "video_mb": round(video.stat().st_size / 1_048_576, 1), "title": title, "body": body, "tags": tags,
            "cover": str(cover) if cover and cover.is_file() else "",
            "cover_portrait": str(cover_portrait) if cover_portrait and cover_portrait.is_file() else ""}


# 9/24 B 站投稿报 No module named 'playwright'：工作台后台 PATH 里第一个 python3 是 Homebrew 的，
# 没装 playwright。命令里写的「python3」不再交给 PATH 去猜，按这个通道要的库挑解释器。
PYTHON_CANDIDATES = (sys.executable, "/usr/local/bin/python3", "/usr/bin/python3", "/opt/homebrew/bin/python3")
_PYTHON_FOR: dict[tuple[str, ...], str] = {}


def python_with(modules: tuple[str, ...], candidates: tuple[str, ...] = PYTHON_CANDIDATES) -> str:
    if not modules:
        return sys.executable
    if modules in _PYTHON_FOR:
        return _PYTHON_FOR[modules]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            done = subprocess.run([candidate, "-c", "import " + ", ".join(modules)], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            _PYTHON_FOR[modules] = candidate
            return candidate
    raise PublishError(f"这台机器上找不到装了 {'、'.join(modules)} 的 Python：在终端运行 /usr/local/bin/python3 -m pip install {' '.join(modules)}")


def command_for(payload: dict[str, Any], publishers: dict[str, dict[str, Any]] = PUBLISHERS) -> list[str]:
    spec = publishers[payload["platform"]]
    template = list(spec["modes"][payload["mode"]]["argv"])
    if template and template[0] == "python3":
        template[0] = python_with(tuple(spec.get("needs") or ()))
    article = payload.get("article", "")
    values = {"video": payload["video"], "title": payload["title"], "body": payload["body"], "tags": ",".join(payload["tags"]),
              "article": article, "cover": payload.get("cover", ""), "cover_portrait": payload.get("cover_portrait", ""),
              # 同一选题的文章放在 drafts/topic-<id>/ 下：拿目录名当稳定 id，再发会更新同一篇而不是新建
              "brief_id": f"content-studio-{Path(article).parent.name}" if article else "",
              "yanxishi_env": _secret("yanxishi", "env_id") if "{yanxishi_env}" in template else "",
              # gzh skill 排好的版（和文章对得上才用）；没有就空着，脚本按 Markdown 导入
              "gzh_html": _gzh_html(article) if "{gzh_html}" in template else ""}
    # Only whole-argument placeholders are substituted, so titles with braces never break the command.
    return [values[part[1:-1]] if part[1:-1] in values and part.startswith("{") and part.endswith("}") else part for part in template]


def confirmable(job: dict[str, Any], now: datetime | None = None) -> None:
    if job["state"] != "awaiting_confirm":
        raise PublishError("这个发布任务不在等待确认")
    created = datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if ((now or now_utc()) - created).total_seconds() > CONFIRM_WINDOW_SECONDS:
        raise PublishError("确认已超过 30 分钟，请重新准备发布")


def parse_result(stdout: str) -> dict[str, Any]:
    """The scripts print one JSON object; take the last parseable one."""
    for match in reversed(list(re.finditer(r"\{", stdout))):
        try:
            value = json.loads(stdout[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def run(payload: dict[str, Any], *, publishers: dict[str, dict[str, Any]] = PUBLISHERS, timeout: float | None = None) -> dict[str, Any]:
    argv = command_for(payload, publishers)
    spec = publishers[payload["platform"]]
    timeout = timeout or spec.get("timeout") or RUN_TIMEOUT_SECONDS
    env = None
    wanted = spec.get("secret_env") or {}
    if wanted:
        # 钥匙走环境变量，不进命令行参数（ps 里看得见）
        env = {**os.environ, **{name: _secret(*where) for name, where in wanted.items()}}
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=env,
                                   cwd=str(CONTENT_OPS) if CONTENT_OPS.is_dir() else None)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "message": "发布超时（45 分钟），去平台后台看看有没有上传成功"}
    except OSError as exc:
        return {"ok": False, "status": "command_missing", "message": f"找不到发布脚本：{exc}"}
    result = parse_result(completed.stdout)
    if not result:
        result = {"ok": False, "status": "no_result", "message": (completed.stderr or completed.stdout).strip()[-400:]}
    result.setdefault("ok", completed.returncode == 0)
    if result.get("ok") and payload["platform"] == "youtube" and result.get("privacy_status") == "private":
        # 私享 = 草稿：9/29 作者 先都存草稿、自己在后台公开。公开后的链接现在就知道，先带着，他点「发出去了」时填好。
        result["published"] = False
        if result.get("video_id"):
            result["public_url"] = f"https://www.youtube.com/watch?v={result['video_id']}"
    if result.get("ok") and payload["platform"] == "youtube" and result.get("video_id") and payload.get("cover"):
        result.update(youtube_cover(str(result["video_id"]), Path(payload["cover"]), publishers=publishers))
        if result["thumbnail"] == "failed":
            result["message"] = f"{result.get('message') or '视频传上去了'}；{result['thumbnail_message']}"
    return result


YOUTUBE_THUMB = Path(__file__).parent / "youtube_thumb.py"


def youtube_cover(video_id: str, cover: Path, *, publishers: dict[str, dict[str, Any]] = PUBLISHERS,
                  runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """9/29：YouTube 传完把打包里定稿的封面（16:9 优先）设上去。设不上不算发布失败，只在消息里说一句。"""
    python = CONTENT_OPS / ".venv/bin/python"
    token = (publishers.get("youtube") or {}).get("credential")
    try:
        done = runner([str(python), str(YOUTUBE_THUMB), "--video-id", video_id, "--image", str(cover), "--token", str(token)],
                      capture_output=True, text=True, timeout=180, check=False)
        got = parse_result(done.stdout) or {"ok": False, "message": (done.stderr or done.stdout).strip()[-200:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        got = {"ok": False, "message": f"封面没设上：{exc}"}
    return {"thumbnail": "set" if got.get("ok") else "failed", "thumbnail_message": got.get("message") or ""}


def result_url(result: dict[str, Any]) -> str | None:
    for key in ("url", "video_url", "link", "watch_url"):
        if str(result.get(key) or "").startswith("http"):
            return result[key]
    if result.get("video_id") and str(result.get("platform") or "youtube") == "youtube":
        return f"https://www.youtube.com/watch?v={result['video_id']}"
    return None


# 发完（尤其是存草稿、要去平台确认的）之后该打开哪一页：作者 9/27「存了 X 草稿，我都不知道发过去没有，
# 还得自己去 x.com 找」。能直达那一篇就直达，不能就打开草稿箱 / 稿件管理。
CONFIRM_PAGES = {
    "wechat_mp": "https://mp.weixin.qq.com/",
    "miniprogram": None,
    "channels": "https://channels.weixin.qq.com/platform/post/list",
    "bilibili": "https://member.bilibili.com/platform/upload-manager/article",
}


def confirm_url(platform: str, result: dict[str, Any]) -> str | None:
    """这一条发完后给 作者 打开的页面。"""
    if platform == "x" and result.get("id"):
        return f"https://x.com/compose/articles/edit/{result['id']}"
    if platform == "bilibili" and str(result.get("platform_url") or "").startswith("http"):
        return result["platform_url"]  # 在审核中，打开稿件管理比打开视频页有用
    if platform == "youtube" and result.get("video_id"):
        return f"https://studio.youtube.com/video/{result['video_id']}/edit"
    return CONFIRM_PAGES.get(platform) or result_url(result)


# 10/3 作者：「只给我展示 error 是没有用的」——出了问题要说清：为什么、我要做什么、在这一页就能做，做完自己检测、自己再发。
# fix：login = 页面上给「登录 X」按钮（跑 login_argv），retry = 「再发一次」，setup = 去后台改设置的链接，wait = 等。
LOGIN_LABEL = {"youtube": "登录 YouTube", "bilibili": "登录 B 站"}
NETWORK_HINTS = ("连不上", "urlopen error", "SSL", "timed out", "Connection reset", "Connection refused", "Temporary failure in name resolution",
                 "Network is unreachable", "RemoteDisconnected", "EOF occurred")


LOGIN_FIX = {
    "youtube": ("YouTube 的登录过期了（Google 隔几天就要重新授权一次）。", "点「登录 YouTube」，在弹出的网页里选你的频道、点「允许」。登好了这里会自己再发一次。"),
    "bilibili": ("B 站的登录失效了。", "点「登录 B 站」，在弹出的窗口里用 B 站 App 扫码。登好了这里会自己再发一次。"),
}


def login_fix(platform: str) -> dict[str, Any]:
    """发之前一查就知道要重新登录（还没发）、或者发的时候报了登录过期：都是这一句。"""
    why, todo = LOGIN_FIX.get(platform, (f"{platform} 要重新登录。", "点登录按钮，登好了这里会自己再发一次。"))
    return {"fix": "login", "label": LOGIN_LABEL.get(platform, "登录"), "link": None, "why": why, "todo": todo}


def _last_line(message: str) -> str:
    """Python 报错时，有用的是最后一行异常；别把整段 traceback 摆给他看。"""
    lines = [x.strip() for x in str(message or "").splitlines() if x.strip() and not x.strip().startswith(("File \"", "Traceback", "^", "~"))]
    return (lines[-1] if lines else "")[:200]


LOGIN_EXPIRED = ("invalid_grant", "refresherror", "needs_reauth", "token has been expired", "token_missing", "未授权")


def diagnose(platform: str, message: str, *, can_login: bool | None = None) -> dict[str, Any]:
    """一格没发出去：{why 为什么, todo 你要做什么, fix login/retry/setup/wait, label 按钮字, link 要打开的页面}。
    can_login：这个通道在工作台里能登录（有 login_argv）；不给就看 PUBLISHERS。"""
    text = str(message or "")
    low = text.lower()
    label = (PUBLISHERS.get(platform) or {}).get("label", platform)
    if can_login is None:
        can_login = bool((PUBLISHERS.get(platform) or {}).get("login_argv"))
    if can_login and platform != "bilibili" and any(k in low for k in LOGIN_EXPIRED):
        return login_fix(platform)
    if platform == "bilibili" and any(k in low for k in ("login", "登录", "cookie", "-101", "账号未登录")):
        return login_fix("bilibili")
    # 10/20：B 站投稿页等不到「请输入稿件标题」——页面没走到填表那一步，多半是登录失效被带去了登录页。先让他重新扫码
    if platform == "bilibili" and any(k in low for k in ("wait_for_selector", "locator(", "稿件标题", "timeout")):
        fix = login_fix("bilibili")
        return {**fix, "why": "B 站投稿页没打开到填标题那一步，多半是登录失效了。"}
    if "429" in text or "超额" in text:
        return {"fix": "wait", "label": "再发一次", "link": None, "why": f"{label} 说今天发得太多了（额度用完）。", "todo": "不用做什么，明天再点「再发一次」。"}
    if platform == "x" and ("401" in text or "403" in text):
        return {"fix": "setup", "label": "去 X 开发者后台 ↗", "link": "https://developer.x.com/en/portal/dashboard",
                "why": "X 不认这把钥匙：应用权限不是 Read and Write，或者账号的 Premium 过期了。",
                "todo": "在 X 开发者后台把应用权限改成 Read and Write、重新生成 Access Token，填进 ~/.config/content-studio/secrets.yaml 的 x: 段，回来点「再发一次」。"}
    if platform == "wechat_mp" and ("40164" in text or "ip" in low and "white" in low or "白名单" in text):
        ip = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
        return {"fix": "setup", "label": "去公众号后台 ↗", "link": "https://mp.weixin.qq.com/",
                "why": "公众号不认这台机器的网络地址（IP 白名单）。",
                "todo": f"公众号后台 → 设置与开发 → 基本配置 → IP 白名单，加上 {ip.group(1) if ip else '这台机器现在的 IP'}，回来点「再发一次」。"}
    if any(k in text for k in NETWORK_HINTS):
        return {"fix": "retry", "label": "再发一次", "link": None,
                "why": f"网络断了一下，没连上 {label}（不是你的问题，已经自动重试过）。", "todo": "点「再发一次」。"}
    return {"fix": "retry", "label": "再发一次", "link": None,
            "why": _last_line(text) or "没发出去，也没说为什么。", "todo": "点「再发一次」。还不行就点开详情，把它发给 Claude。"}


STATUS_TEXT = {
    "cookie_missing": "还没有登录信息，需要先在电脑上登录",
    "cookie_invalid": "登录已过期，需要在电脑上重新扫码登录",
    "window_closed": "窗口关了，没发",
    "video_missing": "找不到视频文件",
}


def explain(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    # X / 公众号 / 研习室的脚本把原因放在 error 里；只看 message 的话页面上只剩「发布失败」
    return STATUS_TEXT.get(status) or str(result.get("message") or result.get("error") or status or "发布失败")[:300]
