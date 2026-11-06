"""装机验收（10/6 作者 定的第 2 道闸）：一条命令七层，出红绿验收单；红的写客户该点哪里。"""
from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from content_studio import acceptance


class FakeProbe(acceptance.Probe):
    def __init__(self, *, have: set[str], service: bool, launchd: str, home: Path) -> None:
        self._have, self._service, self._launchd = have, service, launchd
        super().__init__(which=lambda t: f"/usr/bin/{t}" if t in have else None, find_spec=lambda m: object() if m in have else None,
                         run=self._run, get=self._get, home=home)

    def _run(self, argv, **kw):  # noqa: ANN001
        if argv[:2] == ["launchctl", "print"]:
            return SimpleNamespace(returncode=0 if self._launchd else 1, stdout=self._launchd, stderr="")
        if "claude" in argv[0]:
            return SimpleNamespace(returncode=0, stdout="好", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Please log in first (oauth)")

    def _get(self, url, timeout):  # noqa: ANN001
        if not self._service:
            raise OSError("refused")
        if url.endswith("/api/update?fetch=false"):
            return {"head": {"date": "2026-10-06", "hash": "abc1234"}}
        if url.endswith("/api/state"):
            return {"cookies": {"ok": True}, "self_account": {"nickname": "验收号", "last_synced_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}, "last_full_sync": {},
                    "settings": {"platform_accounts": {"youtube": {"on": True}, "channels": {"on": True}}}}
        if url.endswith("/api/platforms"):
            return {"platforms": [{"key": "youtube", "label": "YouTube", "state": "stale", "note": "登录过期", "login_hint": "去 YouTube 页「后台」重新登录"},
                                  {"key": "channels", "label": "视频号", "state": "blocked", "note": ""}, {"key": "douyin", "label": "抖音", "state": "linked"}]}
        raise OSError(url)


def test_machine_layer_marks_hard_and_soft_rows() -> None:
    facts = {"system": "Darwin", "machine": "arm64", "macos": "15.6", "ram": 16 * 1024 ** 3, "free": 100 * 1024 ** 3, "tools": {"brew": True}, "chrome": False, "obsidian": True}
    items = {i.name: i for i in acceptance.layer_machine(facts)}
    assert items["芯片"].ok and items["内存"].ok and items["Chrome"].ok is False and items["Chrome"].hard is False


def test_install_layer_reads_service_launchd_and_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_AI", "claude")
    (tmp_path / "Library/Caches/ms-playwright/chromium-1208").mkdir(parents=True)
    probe = FakeProbe(have={"fastapi", "uvicorn", "yaml", "httpx", "markdown", "PIL", "multipart", "ffmpeg", "ffprobe", "git", "claude"}, service=True,
                      launchd="state = running\n\tpid = 4242\n\truns = 7\n", home=tmp_path)
    items = {i.name: i for i in acceptance.layer_install(port=8780, label="com.test", probe=probe)}
    assert items["依赖包"].ok and items["后台服务 :8780"].ok and "abc1234" in items["后台服务 :8780"].note
    assert items["开机常驻"].ok and "4242" in items["开机常驻"].note
    assert items["浏览器组件"].ok and items["codex"].ok is False and items["codex"].hard is False
    assert items["转写模型"].ok is False and items["转写模型"].hard is False
    assert items["杀一次自己起来"].ok is None
    down = FakeProbe(have=set(), service=False, launchd="", home=tmp_path)
    items = {i.name: i for i in acceptance.layer_install(port=8780, label="com.test", probe=down)}
    assert items["后台服务 :8780"].ok is False and "launchctl" in items["后台服务 :8780"].fix
    assert items["依赖包"].ok is False and "pip install" in items["依赖包"].fix


def test_channels_layer_calls_ai_once_and_reads_platform_states(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_AI", "claude")
    probe = FakeProbe(have={"claude", "codex"}, service=True, launchd="", home=tmp_path)
    items = {i.name: i for i in acceptance.layer_channels(port=8780, ai=True, probe=probe)}
    assert items["claude"].ok and items["codex"].ok is False and items["codex"].note == "没登录" and items["codex"].hard is False
    assert items["抖音"].ok and "验收号" in items["抖音"].note
    assert items["YouTube"].ok is False and "重新登录" in items["YouTube"].fix and items["YouTube"].hard is False
    assert items["视频号"].ok is None
    quiet = {i.name: i for i in acceptance.layer_channels(port=8780, ai=False, probe=probe)}
    assert quiet["claude"].ok is None


def test_selected_ai_backend_is_the_hard_check(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CONTENT_STUDIO_AI", "codex")
    probe = FakeProbe(have={"claude", "codex"}, service=True, launchd="", home=tmp_path)
    items = {i.name: i for i in acceptance.layer_channels(port=8780, ai=True, probe=probe)}
    assert items["codex"].ok is False and items["codex"].hard and items["claude"].hard is False
    tools = {i.name: i for i in acceptance.layer_install(port=8780, label="com.test", probe=FakeProbe(have={"codex"}, service=True, launchd="", home=tmp_path))}
    assert tools["codex"].ok and tools["codex"].hard and tools["claude"].ok is False and tools["claude"].hard is False


def test_config_layer_asks_the_service_first(tmp_path: Path) -> None:
    class P(FakeProbe):
        def _get(self, url, timeout):  # noqa: ANN001
            if url.endswith("/api/state"):
                return {"setup": {"present": True, "missing_required": [{"label": "你的抖音主页链接"}]}, "vault": {"ok": False}, "settings": {"obsidian_vault": ""}, "cookies": {"ok": False, "message": "还没导入抖音登录信息"}}
            raise OSError(url)

    items = {i.name: i for i in acceptance.layer_config(port=8780, probe=P(have=set(), service=True, launchd="", home=tmp_path))}
    assert items["你是谁"].ok is False and "你的抖音主页链接" in items["你是谁"].fix
    assert items["Obsidian 库"].ok is False and "开始用" in items["Obsidian 库"].fix
    assert items["抖音登录信息"].ok is False and items["数据目录能写"].ok


def test_mainline_runs_in_a_sandbox_without_touching_the_real_home(monkeypatch) -> None:
    before = sorted(p.name for p in Path(os.environ["CONTENT_STUDIO_HOME"]).glob("*")) if os.environ.get("CONTENT_STUDIO_HOME") else None
    items = {i.name: i for i in acceptance.layer_mainline()}
    assert items["建选题、定标题"].ok and items["平台页看到待发"].ok and items["标记发了、进数据"].ok and items["今天、汇总接口"].ok
    assert items["成片、封面、文章"].ok is None
    if before is not None:
        assert sorted(p.name for p in Path(os.environ["CONTENT_STUDIO_HOME"]).glob("*")) == before


def test_mainline_isolates_files_and_vault_globals(tmp_path, monkeypatch) -> None:
    from content_studio import vault

    real = tmp_path / "real"
    real.mkdir()
    sentinel = real / "keep.txt"
    sentinel.write_text("客户原文")
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(real))
    before = repr(vault.INBOX_SOURCES), repr(vault.DAILY_SOURCES)
    items = acceptance.layer_mainline()
    assert not any(i.ok is False for i in items)
    assert list(real.iterdir()) == [sentinel] and sentinel.read_text() == "客户原文"
    assert (repr(vault.INBOX_SOURCES), repr(vault.DAILY_SOURCES)) == before


def test_disabled_access_is_a_failure_even_with_success_exit_code(tmp_path) -> None:
    p = acceptance.Probe(run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="Your organization has disabled Claude subscription access for Claude Code", stderr=""))
    result = acceptance._ai_once(p, "claude", ["claude"], hard=True, fix="登录")
    assert result.ok is False and result.note == "订阅访问被禁用"
    assert "管理员" in result.fix


def test_skipped_required_checks_never_count_as_passing(tmp_path) -> None:
    report = acceptance.Report(at="2026-10-06T13:00", quick=True, items=[
        acceptance.Item(4, "claude", None, "没试"), acceptance.Item(4, "抖音", None, "还没读过", "手动同步自己的号后重跑"),
        acceptance.Item(6, "界面", None, "没试"),
        acceptance.Item(7, "交接", None, "人做", hard=False),
    ])
    assert not report.passed() and report.to_dict()["status"] == "incomplete"
    assert report.layer_state(4) == "skip"
    assert "尚未完成" in acceptance.render_text(report) and "验收通过" not in acceptance.render_html(report)
    assert "→ 手动同步自己的号后重跑" in acceptance.render_text(report)
    assert "→ 手动同步自己的号后重跑" in acceptance.render_html(report)
    path = acceptance.save(report, tmp_path)
    assert json.loads((tmp_path / "latest.json").read_text())["saved"] == str(path)


def test_config_fallback_does_not_create_a_database(tmp_path, monkeypatch) -> None:
    from content_studio import profile

    monkeypatch.setattr(profile, "find_profile", lambda: None)
    items = acceptance._config_from_files(store_path=tmp_path / "absent.sqlite3", cookie_path=tmp_path / "absent.json")
    assert not (tmp_path / "absent.sqlite3").exists()
    assert any(i.ok is False for i in items)


def test_bad_profile_becomes_a_failed_row_instead_of_aborting(tmp_path, monkeypatch) -> None:
    from content_studio import profile

    monkeypatch.setattr(profile, "find_profile", lambda: tmp_path / "broken.yaml")
    monkeypatch.setattr(profile, "load", lambda *a: (_ for _ in ()).throw(ValueError("坏 YAML")))
    rows = acceptance._config_from_files(store_path=tmp_path / "absent.db", cookie_path=tmp_path / "absent.json")
    assert any(i.name == "你是谁" and i.ok is False and "无法解析" in i.note for i in rows)


def test_never_synced_and_stale_accounts_are_pending(tmp_path) -> None:
    class P(FakeProbe):
        at = None
        error = None
        def _get(self, url, timeout):
            result = super()._get(url, timeout)
            if url.endswith("/api/state"):
                result["self_account"].update(last_synced_at=self.at, last_error=self.error)
            return result
    p = P(have=set(), service=True, launchd="", home=tmp_path)
    for at in (None, "bad", (datetime.now(timezone.utc) - timedelta(hours=31)).isoformat()):
        p.at = at
        row = next(i for i in acceptance.layer_channels(port=8780, ai=False, probe=p) if i.name == "抖音")
        assert row.ok is None and row.hard and "手动同步" in row.fix
    p.at = datetime.now(timezone.utc).isoformat()
    p.error = "验证失败"
    row = next(i for i in acceptance.layer_channels(port=8780, ai=False, probe=p) if i.name == "抖音")
    assert row.ok is False


def test_sandbox_fails_closed_if_platform_code_attempts_a_process(tmp_path) -> None:
    marker = tmp_path / "should-not-exist"
    code = '''
import subprocess, sys
from pathlib import Path
from content_studio import acceptance, publisher
def forbidden(*args, **kwargs):
    subprocess.run([sys.executable, '-c', "from pathlib import Path; Path(" + repr(sys.argv[1]) + ").write_text('bad')"])
publisher.readiness = forbidden
items = acceptance.sandbox_entry()
assert any(i.name == '主线沙盒' and i.ok is False for i in items)
assert not Path(sys.argv[1]).exists()
'''
    run = subprocess.run([sys.executable, "-c", code, str(marker)], env={**os.environ, "CONTENT_STUDIO_HOME": str(tmp_path / "sandbox")}, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert not marker.exists()


def test_restart_uses_the_busy_guard_and_respects_refusal(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("CONTENT_STUDIO_RESTART", "/tmp/safe-restart")
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout="有任务在跑", stderr="")
    result = acceptance._restart_once(acceptance.Probe(run=run), 8780, "com.test", {"pid": 1})
    assert result.ok is False and "未执行" in result.note
    assert calls[0][0] == ["/tmp/safe-restart"]
    assert calls[0][1]["env"]["CONTENT_STUDIO_SERVICE_LABEL"] == "com.test"


def test_report_text_and_html_say_what_to_click(tmp_path: Path) -> None:
    report = acceptance.Report(at="2026-10-06T10:00", quick=True, items=[
        acceptance.Item(1, "芯片", True, "Apple M 芯片"),
        acceptance.Item(2, "后台服务 :8780", False, "没应答", "终端里 launchctl kickstart -k gui/$(id -u)/com.test"),
        acceptance.Item(4, "codex", False, "没登录", "终端里 codex login", hard=False),
        acceptance.Item(7, "客户在验收单上签字", None, "验收单在 ~/.config/content-studio/acceptance/ 里", hard=False),
    ])
    assert not report.passed() and report.layer_state(2) == "fail" and report.layer_state(4) == "warn" and report.layer_state(7) == "skip"
    text = acceptance.render_text(report)
    assert "❌ 2 安装" in text and "launchctl kickstart" in text and "不挡验收" in text and "1 项没过" in text
    path = acceptance.save(report, tmp_path)
    assert path.is_file() and (tmp_path / "latest.json").is_file()
    page = path.read_text(encoding="utf-8")
    assert "装机验收单" in page and "→ 终端里 launchctl kickstart" in page and "签字" in page


def test_cli_runs_quick_without_a_service(tmp_path: Path, monkeypatch) -> None:
    from content_studio import cli

    monkeypatch.setattr(acceptance, "layer_mainline", lambda keep=False: [acceptance.Item(5, "主线", True, "假的")])
    monkeypatch.setattr(acceptance, "save", lambda report, folder=None: tmp_path / "x.html")
    assert cli.main(["acceptance", "--quick", "--no-ai", "--port", "1", "--label", "com.nope"]) == 1  # 服务没应答 → 没过


def test_fix_same_as_note_is_not_repeated():
    report = acceptance.Report(at="2026-10-06T15:00", quick=True,
                               items=[acceptance.Item(1, "硬盘可用", False, "7GB，要 30GB，先清理", "7GB，要 30GB，先清理")])
    text = acceptance.render_text(report)
    assert "先清理 →" not in text and "硬盘可用：7GB，要 30GB，先清理" in text
    assert "→ 7GB" not in acceptance.render_html(report)
