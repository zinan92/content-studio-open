from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

import httpx

from . import conf
from .paths import config_dir
from .creator_metrics import CREATOR_MANAGE_URL, CreatorMetricsError, CreatorMetricsStore, CreatorMetricsSyncer, DEFAULT_USER_AGENT, load_cookie_file
from .accounts import AccountError, ContentDownloaderClient, PLATFORM_DOUYIN, add_account, sync_account
from .pipeline import DEFAULT_GLOSSARY_PATH, PipelineError, run_pipeline
from .store import DEFAULT_STORE_PATH, StoreError, StudioStore
from .structure import ReportError


DEFAULT_COOKIE_PATH = config_dir() / "douyin-cookies.json"
DEFAULT_DB_PATH = config_dir() / "data/creator-metrics.sqlite3"
DEFAULT_DATA_DIR = config_dir()
DEFAULT_REPORTS_DIR = DEFAULT_DATA_DIR / "studio"
DEFAULT_DOWNLOADS_DIR = DEFAULT_DATA_DIR / "downloads"
DEFAULT_PORT = 8780
PLIST_LABEL = "com.content-studio.daily-sync"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="content-studio")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser(
        "creator-sync",
        help="manually snapshot creator.douyin.com work metrics for the last 90 days",
    )
    sync.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    sync.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    sync.add_argument("--days", type=int, default=90)
    sync.add_argument("--delay-seconds", type=float, default=1.0)
    sync.add_argument("--page-size", type=int, default=12)
    pipeline = commands.add_parser(
        "pipeline",
        help="run Douyin links through download, transcription, structure, and report",
    )
    pipeline.add_argument("--url", dest="urls", action="append", required=True)
    pipeline.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    pipeline.add_argument("--data-dir", type=Path, default=config_dir())
    pipeline.add_argument("--downloads-dir", type=Path, default=None)
    pipeline.add_argument("--whisper-model", default="turbo")
    pipeline.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)
    pipeline.add_argument("--glossary", type=Path, default=DEFAULT_GLOSSARY_PATH)
    add = commands.add_parser("add-account", help="add a creator profile link to the library")
    add.add_argument("url")
    add.add_argument("--self", dest="is_self", action="store_true", help="mark as 作者's own account")
    add.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    add.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)

    sync_all = commands.add_parser(
        "sync", help="one serial pass: sync every Douyin account, creator metrics, and queue breakouts"
    )
    sync_all.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    sync_all.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    sync_all.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)

    screen = commands.add_parser("screen-reach", help="read 小红书 views from a screenshot of 作者's own Chrome")
    screen.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)

    work = commands.add_parser("work", help="process queued teardown jobs and exit")
    work.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    work.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    work.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)
    work.add_argument("--data-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    work.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)
    work.add_argument("--max-jobs", type=int, default=None)

    serve = commands.add_parser("serve", help="start the local web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    serve.add_argument("--cookies", type=Path, default=DEFAULT_COOKIE_PATH)
    serve.add_argument("--creator-db", type=Path, default=DEFAULT_DB_PATH)

    check = commands.add_parser("check", help="核对 profile.yaml：哪些必填没填、哪些可选没填")
    check.add_argument("--profile", type=Path, default=None, help="不给就按 环境变量 → 仓库根目录 → ~/.config/content-studio 找")
    serve.add_argument("--data-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    serve.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)

    check_plan = commands.add_parser("check-visual-plan", help="视觉规格的算术检查（在叫评审之前跑）")
    check_plan.add_argument("project", type=Path, help="口播项目目录")
    check_plan.add_argument("--shots", type=Path, default=conf.path("skills.shots"))

    phone = commands.add_parser("phone-preview", help="成片压成 540p、切成每段不超过 28 MB 的手机预览")
    phone.add_argument("project", type=Path, help="口播项目目录，或配置根目录下的项目名")
    phone.add_argument("--out", type=Path, default=None, help="输出到别的目录（默认 项目/final/手机预览）")

    ev = commands.add_parser("evidence", help="一次给一批还没发完的内容找证据图（视频里的笔记截图、名人原推），只出提案；平时在打包页点按钮找")
    ev.add_argument("--server", default=f"http://127.0.0.1:{DEFAULT_PORT}")
    ev.add_argument("--topic", type=int, default=None, help="只跑这一篇（跑过的也重跑）")
    ev.add_argument("--budget-minutes", type=int, default=270, help="总共最多跑多久，到点停（早上 9:25 有同步）")

    acc = commands.add_parser("acceptance", help="装机验收：机器 → 安装 → 配置 → 通道 → 主线（沙盒）→ 界面 → 交接，出一张红绿验收单")
    acc.add_argument("--quick", action="store_true", help="不叫 AI、不开浏览器")
    acc.add_argument("--no-ai", action="store_true", help="不真叫 claude / codex")
    acc.add_argument("--restart", action="store_true", help="杀一次后台服务，看它自己起来")
    acc.add_argument("--port", type=int, default=DEFAULT_PORT)
    acc.add_argument("--label", default=None, help="launchd 里服务的名字（默认读 profile 的 service.label）")
    org = commands.add_parser("organize-videos", help="本机新出的视频归档到 SSD 视频库（按内容分类）；默认只列出来，加 --apply 才搬")
    org.add_argument("--apply", action="store_true", help="真的搬：复制 → 核对 → 删本机原件")
    org.add_argument("--library", type=Path, default=None, help="视频库根目录（默认 video_projects_root 的上一层）")
    org.add_argument("--min-age", type=float, default=30, help="多少分钟内改过的不搬（可能还在录、在导出）")
    plist = commands.add_parser(
        "write-schedule", help="write (but do not load) a launchd plist for a daily sync"
    )
    plist.add_argument("--hour", type=int, default=9)
    plist.add_argument("--minute", type=int, default=30)
    plist.add_argument("--output", type=Path, default=DEFAULT_DATA_DIR / f"{PLIST_LABEL}.plist")
    return parser


def _cookie_client_factory(cookie_path: Path):
    cookies = load_cookie_file(cookie_path)
    return lambda: ContentDownloaderClient(cookies)


def run_add_account(args: argparse.Namespace) -> int:
    with _open_store(args.store) as store:
        factory = None
        if "douyin.com" in args.url and "/user/" not in args.url:
            factory = _cookie_client_factory(args.cookies)
        account = add_account(store, args.url, client_factory=factory, is_self=args.is_self)
    print(json.dumps({"status": "ok", "account": account}, ensure_ascii=False))
    return 0


def sync_everything(
    store: StudioStore,
    *,
    cookie_path: Path,
    creator_db: Path,
    platform_fetchers: dict | None = None,
    benchmarks: bool = True,
) -> dict:
    """自己的账号先同步，再（benchmarks=True 时）同步对标。撞上风控整趟停下。

    9/29 作者：对标用处不大、每天看一眼有没有更新就够，别占抖音额度把主号搞限流。所以工作台上的
    「同步全部账号」只同步自己的号（benchmarks=False），对标只在对标雷达页单独同步；每天 9:30 的
    自动同步两样都做，对标每个号只看最新一页。
    """
    from . import platform_stats

    factory = _cookie_client_factory(cookie_path)
    # B站 / X / 研习室 的触达和抖音无关，放最前面：抖音撞上风控提前结束也不耽误它们。
    summary: dict = {"accounts": [], "creator_metrics": None, "enqueued": 0, "platforms": platform_stats.sync(store, platform_fetchers)}
    mine = [a for a in store.my_accounts() if a["platform"] == PLATFORM_DOUYIN]
    stopped = _sync_douyin(store, mine, factory, summary)
    summary["followers"] = _record_followers(store)
    if stopped:
        return summary
    if mine:
        summary["creator_metrics"] = sync_creator_metrics(cookie_path=cookie_path, creator_db=creator_db)
    if benchmarks:
        bench = sync_benchmarks(store, cookie_path=cookie_path, factory=factory)
        summary["accounts"] += bench["accounts"]
        summary["enqueued"] = bench["enqueued"]
        if bench.get("stopped"):
            summary["stopped"] = bench["stopped"]
    return summary


def _record_followers(store: StudioStore) -> dict:
    """全网粉丝今天记一笔（followers.py）。读不到不影响同步。"""
    from datetime import date

    from . import followers

    try:
        return followers.sync(store, date.today())
    except Exception as exc:  # noqa: BLE001 - 粉丝记不上，同步照样算成功
        return {"error": str(exc)[:160]}


BENCHMARK_PAGES = 1  # 对标只看最新一页（约 20 条）：够看出有没有新发的，少占抖音额度


def sync_benchmarks(store: StudioStore, *, cookie_path: Path, factory=None) -> dict:
    """关注的账号（老师和对标）：每个号读资料 + 最新一页作品，只为了知道有没有新发的。撞上风控整趟停下。

    9/30 作者：「拆解必须是我主动要求，而不是你自动看到一条就拆一条，这个没有意义。」所以这里不再排任何拆解；
    新发的列在进项的「老师」「对标」里，他自己去看，想拆、想复刻再点。
    """
    factory = factory or _cookie_client_factory(cookie_path)
    summary: dict = {"accounts": [], "enqueued": 0}
    _sync_douyin(store, store.followed_accounts(), factory, summary, pages=BENCHMARK_PAGES)
    return summary


def _sync_douyin(store: StudioStore, accounts: list[dict], factory, summary: dict, pages: int | None = None) -> bool:
    """一个个同步；撞上风控记下 stopped 并返回 True（后面的都不再碰抖音）。"""
    from .accounts import RiskControlStop

    for account in accounts:
        if account["platform"] != PLATFORM_DOUYIN:
            continue
        try:
            result = sync_account(store, account["id"], client_factory=factory, pages=pages)
            summary["accounts"].append({"id": account["id"], "status": "ok", "videos": result["video_count"]})
        except RiskControlStop as exc:
            summary["accounts"].append({"id": account["id"], "status": "stopped", "error": str(exc)})
            summary["stopped"] = str(exc)
            return True
        except AccountError as exc:
            summary["accounts"].append({"id": account["id"], "status": "failed", "error": str(exc)})
    return False


def sync_creator_metrics(*, cookie_path: Path, creator_db: Path) -> dict:
    """Snapshot creator-backend metrics for 作者's own videos (last 90 days)."""
    try:
        cookies = load_cookie_file(cookie_path)
        headers = {"Referer": CREATOR_MANAGE_URL, "User-Agent": DEFAULT_USER_AGENT}
        with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
            with CreatorMetricsStore(creator_db) as metrics_store:
                result = CreatorMetricsSyncer(client=client, store=metrics_store).sync(days=90, delay_seconds=1.5)
        return {"status": "ok", **result.__dict__}
    except CreatorMetricsError as exc:
        return {"status": "failed", "error": str(exc)}


def archive_new_videos(store: StudioStore, *, cookie_path: Path, limit: int = 5, **kwargs) -> dict:
    """同步完顺手把新发的抖音视频存一份到本机。一次最多几条：平常一天就一条新的。"""
    from . import archive

    me = store.self_account()
    if me is None:
        return {"skipped": "还没有连接自己的抖音号"}
    settings = store.settings()
    root = archive.usable_root(settings.get("douyin_archive"))
    search = [Path(p).expanduser() for p in settings.get("local_video_roots") or []]
    return archive.archive_pending(store.public_videos(me["id"]), root=root, cookie_path=cookie_path, search=search, limit=limit, **kwargs)


def run_sync(args: argparse.Namespace) -> int:
    with _open_store(args.store) as store:
        summary = sync_everything(
            store, cookie_path=args.cookies, creator_db=args.creator_db
        )
        if not summary.get("stopped"):
            summary["archive"] = archive_new_videos(store, cookie_path=args.cookies)
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("stopped") else 0


def run_evidence(args: argparse.Namespace) -> int:
    """问工作台要跑哪几篇，一篇一篇跑；一篇失败记一行接着下一篇。到点就停。"""
    import time
    import urllib.request

    from .extras.proof import evidence

    started = time.monotonic()
    with urllib.request.urlopen(f"{args.server}/api/evidence/queue", timeout=120) as r:
        queue = json.loads(r.read().decode())["topics"]
    stamp = lambda: time.strftime("%m-%d %H:%M:%S")  # noqa: E731
    todo = [t for t in queue if (t["topic_id"] == args.topic if args.topic else not t["done"] and not t["skip"])]
    print(f"{stamp()} 证据图：{len(todo)} 篇要跑（共 {len(queue)} 篇，跳过 {sum(1 for t in queue if t['skip'])} 篇）", flush=True)
    for t in queue:
        if t["skip"] and (not args.topic or t["topic_id"] == args.topic):
            print(f"{stamp()}   跳过《{t['title'][:20]}》：{t['skip']}", flush=True)
    failed = 0
    for t in todo:
        if time.monotonic() - started > args.budget_minutes * 60:
            print(f"{stamp()} 到点了，剩下的明晚接着跑", flush=True)
            break
        if t["skip"]:
            continue
        segments = []
        if t["transcript"]:
            try:
                segments = json.loads(Path(t["transcript"]).read_text(encoding="utf-8")).get("segments") or []
            except (OSError, ValueError):
                segments = []
        try:
            res = evidence.run_topic(Path(t["article"]), Path(t["video"]), segments=segments)
            ok = [i for i in res["items"] if i.get("placed")]
            print(f"{stamp()}   《{t['title'][:20]}》：提案 {len(ok)} 张（视频截图 {sum(i['kind'] == 'frame' for i in ok)}、"
                  f"推文 {sum(i['kind'] == 'tweet' for i in ok)}），扔掉 {len(res['rejected'])} 张", flush=True)
        except Exception as exc:  # noqa: BLE001 - 一篇失败不拖累下一篇
            failed += 1
            print(f"{stamp()}   《{t['title'][:20]}》失败：{exc}", flush=True)
    return 1 if failed else 0


def run_screen_reach(args: argparse.Namespace) -> int:
    """小红书触达：用 作者 的 Chrome 截数据页读。由「内容工作台读数」小 App 每天早上调用——
    后台 launchd 进程弹不出「允许控制 Chrome / 录屏」的授权框，App 可以。"""
    from . import platform_stats, screen_stats

    with _open_store(args.store) as store:
        summary = platform_stats.sync(store, {"xiaohongshu": screen_stats.xiaohongshu_posts})
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if all(v.get("ok") for v in summary.values()) else 1


def run_work(args: argparse.Namespace) -> int:
    from .worker import TeardownWorker, WorkerConfig

    with _open_store(args.store) as store:
        store.recover_interrupted_jobs()
        worker = TeardownWorker(
            store,
            WorkerConfig(
                cookie_path=args.cookies,
                data_dir=args.data_dir,
                downloads_dir=args.downloads_dir,
                creator_db=args.creator_db,
            ),
        )
        processed = worker.drain(args.max_jobs)
    print(json.dumps({"status": "ok", "processed": processed}, ensure_ascii=False))
    return 0


def run_check(args: argparse.Namespace) -> int:
    from . import profile

    path = profile.find_profile(args.profile)
    data = profile.load(path) if path else {}
    checks = profile.check(data)
    print(profile.render_checklist(checks, path))
    return 0 if profile.summary(checks)["ok"] else 1


def run_acceptance(args: argparse.Namespace) -> int:
    """装机验收（10/6）：一条命令，七层，出验收单。红的写清楚客户该点哪里。"""
    from . import acceptance

    report = acceptance.run(quick=args.quick, ai=False if args.no_ai else None, port=args.port, label=args.label, restart=args.restart)
    acceptance.save(report)
    print(acceptance.render_text(report), flush=True)
    return 1 if report.failed() else 2 if report.pending() else 0


def run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from . import profile
    from .web import create_app

    # 启动前把 profile 读进来。缺必填项不拦着起服务——页面上会有横幅说缺什么，
    # 比直接退出对第一次装的人友好；但终端里也打一遍，别让人对着空白页猜。
    profile_path = profile.find_profile()
    profile_data = profile.load(profile_path) if profile_path else None
    checks = profile.check(profile_data or {})
    if profile_path is None or not profile.summary(checks)["ok"]:
        print(profile.render_checklist(checks, profile_path), flush=True)
        print("", flush=True)

    # Without this nothing the service logs ever reaches the launchd log, and access logs are
    # off — so a batch of jobs appearing in the queue cannot be traced to the request that made it.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app(
        store_path=args.store,
        cookie_path=args.cookies,
        creator_db=args.creator_db,
        data_dir=args.data_dir,
        downloads_dir=args.downloads_dir,
        profile=profile_data,
    )
    print(f"内容拆解台已启动：http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info", access_log=True)
    return 0


def run_write_schedule(args: argparse.Namespace) -> int:
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    log_dir = DEFAULT_DATA_DIR.expanduser() / "logs"
    output.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string><string>-m</string><string>content_studio</string><string>sync</string>
  </array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>{repo / "src"}</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{args.hour}</integer><key>Minute</key><integer>{args.minute}</integer></dict>
  <key>StandardOutPath</key><string>{log_dir / "daily-sync.log"}</string>
  <key>StandardErrorPath</key><string>{log_dir / "daily-sync.log"}</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "written_not_loaded",
                "plist": str(output),
                "enable": f"mkdir -p {log_dir} && cp {output} ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/{PLIST_LABEL}.plist",
                "disable": f"launchctl unload ~/Library/LaunchAgents/{PLIST_LABEL}.plist && rm ~/Library/LaunchAgents/{PLIST_LABEL}.plist",
            },
            ensure_ascii=False,
        )
    )
    return 0


class _open_store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> StudioStore:
        self.store = StudioStore(self.path)
        return self.store

    def __exit__(self, *_: object) -> None:
        self.store.close()


def run_creator_sync(args: argparse.Namespace) -> int:
    cookie_path = args.cookies.expanduser().resolve()
    repo_root = Path.cwd().resolve()
    try:
        cookie_path.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise CreatorMetricsError("cookies must be stored outside the content-studio repository")

    cookies = load_cookie_file(cookie_path)
    headers = {"Referer": CREATOR_MANAGE_URL, "User-Agent": DEFAULT_USER_AGENT}
    with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
        with CreatorMetricsStore(args.db) as store:
            summary = CreatorMetricsSyncer(client=client, store=store).sync(
                days=args.days,
                delay_seconds=args.delay_seconds,
                page_size=args.page_size,
            )
    print(json.dumps({"status": "ok", **summary.__dict__}, ensure_ascii=False))
    return 0


def run_pipeline_command(args: argparse.Namespace) -> int:
    receipt = run_pipeline(
        args.urls,
        cookie_path=args.cookies,
        data_dir=args.data_dir,
        downloads_dir=args.downloads_dir,
        whisper_model=args.whisper_model,
        creator_db=args.creator_db,
        glossary_path=args.glossary,
    )
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["status"] == "ok" else 1


def run_check_visual_plan(args: argparse.Namespace) -> int:
    """视觉规格的算术检查。在叫独立评审之前跑——评审只该看判断题。"""
    from . import visual_check

    base = args.project.expanduser()
    result = visual_check.run(
        base / "part-b-body" / "visual-plan.json",
        shots_root=args.shots.expanduser(),
        words_path=base / "subtitles" / "words.json",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


def run_phone_preview(args: argparse.Namespace) -> int:
    from . import phone, profile, release

    base = args.project.expanduser()
    if not base.is_dir():
        root = (profile.load(profile.find_profile()) if profile.find_profile() else {}).get("video_projects_root")
        base = Path(str(root or "")).expanduser() / str(args.project)
    if not base.is_dir():
        raise ValueError(f"找不到项目：{args.project}")
    found = release.find_video(base)
    if not found:
        raise ValueError(f"{base.name} 里还没有成片")
    parts = phone.make_preview(base, base / found, out=args.out.expanduser() if args.out else None)
    for part in parts:
        print(f"{part['name']}  {part['mb']} MB")
    return 0


def run_organize_videos(args: argparse.Namespace) -> int:
    from . import videolib

    library = args.library
    if library is None:
        with _open_store(DEFAULT_STORE_PATH) as store:
            library = videolib.library_from(store.settings().get("video_projects_root"))
    if library is None:
        raise ValueError("没配视频库：设置里填 video_projects_root，或者加 --library")
    library = videolib.check_library(library)
    moves, skipped = videolib.plan(library, min_age_minutes=args.min_age)
    print("\n".join(videolib.describe(library, moves, skipped)))
    if not args.apply:
        if moves:
            print("\n只是列出来；加 --apply 才搬。")
        return 0
    done = videolib.apply(library, moves)
    print(f"\n搬了 {done['moved']} 个（{done['bytes'] / (1 << 30):.1f} GB），删了本机重复的 {done['duplicate']} 个，失败 {done['failed']} 个。"
          f"记录在 {library / videolib.MANIFEST}")
    return 1 if done["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "creator-sync":
            return run_creator_sync(args)
        if args.command == "pipeline":
            return run_pipeline_command(args)
        handlers = {
            "add-account": run_add_account,
            "sync": run_sync,
            "evidence": run_evidence,
            "screen-reach": run_screen_reach,
            "work": run_work,
            "serve": run_serve,
            "check": run_check,
            "write-schedule": run_write_schedule,
            "acceptance": run_acceptance,
            "check-visual-plan": run_check_visual_plan,
            "phone-preview": run_phone_preview,
            "organize-videos": run_organize_videos,
        }
        if args.command in handlers:
            return handlers[args.command](args)
    except (CreatorMetricsError, PipelineError, ReportError, AccountError, StoreError, OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
