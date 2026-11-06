from io import BytesIO
import json
import sqlite3
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient

from content_studio import acceptance, diagnostics, updater, web


def test_bundle_carries_details_but_no_credentials(tmp_path, monkeypatch):
    cookie = "COOKIE-VALUE-123"
    root = tmp_path / "cs"
    (root / "acceptance").mkdir(parents=True)
    (root / "acceptance/latest.json").write_text(json.dumps({"at": "2026-10-06T13:00", "quick": True,
        "items": [{"layer": 1, "name": "硬盘可用", "ok": False, "hard": True, "note": "7GB，要 30GB", "fix": "先清理"}]}, ensure_ascii=False))
    (root / "douyin-cookies.json").write_text(cookie)
    (root / "douyin-chrome").mkdir()
    (root / "douyin-chrome" / "Cookies").write_text(cookie)
    (root / "data").mkdir()
    db = sqlite3.connect(root / "data" / "studio.sqlite3")
    db.executescript("CREATE TABLE jobs (id INTEGER PRIMARY KEY, kind TEXT, error TEXT);"
                     "INSERT INTO jobs (kind, error) VALUES ('sync', 'ValueError: 抖音返回空'), ('sync', NULL);"
                     "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                     "INSERT INTO settings VALUES ('obsidian_vault', '\"~/vault\"'), ('x_api_secret', 'S');")
    db.commit(); db.close()
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "content-studio.stderr.log").write_text(
        'Traceback (most recent call last):\n  File "/x/web.py", line 5189, in _swipe_download\nValueError: 坏了\n'
        f'Cookie: a=1; sessionid={cookie}\n?sid_tt={cookie}&x=1\n')
    prof = tmp_path / "profile.yaml"
    prof.write_text("brand:\n  name: 小王\n")
    monkeypatch.setenv("CONTENT_STUDIO_PROFILE", str(prof))
    monkeypatch.setattr(updater, "status", lambda *, fetch: {"head": {"hash": "abc1234"}, "dirty": True, "deps": []})
    monkeypatch.setattr(acceptance, "_service_answering", lambda *a: (True, "abc1234"))
    monkeypatch.setattr(acceptance, "_launchd_state", lambda *a: {"running": True, "pid": 123})
    monkeypatch.setattr(diagnostics, "_run", lambda argv, cwd=None: "ok " + argv[0])
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    name, data = diagnostics.build_bundle(root=root, logs_dir=logs)
    assert name.endswith(".zip")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"logs/content-studio.stderr.log", "acceptance/latest.json", "profile.yaml", "database.json", "files.json", "git.txt"} <= names
        decoded = "\n".join(archive.read(p).decode() for p in names)
        assert cookie not in decoded
        log = archive.read("logs/content-studio.stderr.log").decode()
        assert 'line 5189, in _swipe_download' in log and "ValueError: 坏了" in log and "Cookie: ***" in log and "sid_tt=***&x=1" in log
        assert json.loads(archive.read("acceptance/latest.json"))["items"][0]["note"] == "7GB，要 30GB"
        dbinfo = json.loads(archive.read("database.json"))
        assert dbinfo["rows"]["jobs"] == 2 and dbinfo["errors"]["jobs.error"][0]["error"] == "ValueError: 抖音返回空"
        assert "obsidian_vault" in dbinfo["settings"] and "x_api_secret" not in dbinfo["settings"]
        listed = {row["path"] for row in json.loads(archive.read("files.json"))}
        assert "douyin-chrome" in listed and "douyin-chrome/Cookies" not in listed
        assert "小王" in archive.read("profile.yaml").decode()
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_log_tail_starts_on_a_whole_line(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("x" * 50 + "\nkeep this line\n")
    assert diagnostics.log_tail(log, limit=20) == "keep this line\n"


def test_download_requires_the_workbench_header_and_never_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path / "cs"))
    monkeypatch.setattr(web, "LEGACY_REPORT_DIRS", ())
    monkeypatch.setattr(diagnostics, "build_bundle", lambda **kw: ("diagnostics.zip", b"PK\x03\x04"))
    monkeypatch.setattr(updater, "apply", lambda: (_ for _ in ()).throw(AssertionError("不该更新")))
    app = web.create_app(store_path=tmp_path / "s.db", cookie_path=tmp_path / "absent.json", creator_db=None,
                         data_dir=tmp_path / "data", downloads_dir=tmp_path / "downloads", start_worker=False)
    client = TestClient(app)
    try:
        assert client.post("/api/diagnostics").status_code == 403
        assert client.post("/api/diagnostics", headers={"X-Content-Studio": "1", "Origin": "https://other.example"}).status_code == 403
        response = client.post("/api/diagnostics", headers={"X-Content-Studio": "1"})
        assert response.status_code == 200 and response.content == b"PK\x03\x04"
        assert response.headers["content-type"] == "application/zip" and response.headers["cache-control"] == "no-store"
        assert 'filename="diagnostics.zip"' in response.headers["content-disposition"]
    finally:
        app.state.store.close()
