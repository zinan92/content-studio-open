"""每日复盘的所有输入均来自临时账本和数据库。"""
from datetime import date, datetime, timedelta
import json
import sqlite3

import pytest

from content_studio import daily_review as review

LEDGER = """# Wendy 实验账本

这段原话要保留。

## 在验证的猜测

| # | 猜测 | 把握 | 依据（第 1 轮，10/11） |
|---|---|---|---|
| A | 第一句话决定推出去 | 中，n=8 | 原始记录 |
| B | 标题一个结果和数字 | 中，n=7 | 原始记录 |
| C | 晚上发比上午好 | 低，n=10 | 原始记录 |

## 实验记录

| 发出 | 哪条 | 验证 | 改了什么 | 看哪个数（72h） | 哪天看 | 结果 | 结论 |
|---|---|---|---|---|---|---|---|
| 待拍 | 系列 1 第 3 集 | A、B、C | 改标题 | 点赞 ≥306 | 发出后 72h | | |

## 想试的

| 想法 | 为什么 | 你要花多少时间 | 看哪个数 | 试几天 | 状态 |
|---|---|---|---|---|---|
| 每天直播 | 离钱最近 | 每天 30 分钟 | 直播人数 | 7 | 待定 |
| 改开头 | 降跳出 | 10 分钟 | 2 秒跳出 | 3 | 待定 |
| 换标题 | 验证 B | 5 分钟 | 点赞 | 2 | 待定 |

## 其他

最后的文字也不要改。
"""


def test_parse_ledger_named_columns_and_missing_sections():
    parsed = review.parse_ledger(LEDGER)
    assert [len(parsed[k]) for k in ("hypotheses", "experiments", "proposals")] == [3, 1, 3]
    assert parsed["hypotheses"][0] == {"id": "A", "text": "第一句话决定推出去", "confidence": "中，n=8", "basis": "原始记录"}
    assert parsed["experiments"][0]["result"] == ""
    assert parsed["proposals"][0]["id"] == 0
    partial = review.parse_ledger(LEDGER.split("## 实验记录")[0])
    assert len(partial["hypotheses"]) == 3
    assert partial["experiments"] == partial["proposals"] == []
    reordered = LEDGER.replace("| # | 猜测 | 把握 |", "| 猜测 | # | 把握 |").replace("| A | 第一句话决定推出去 |", "| 第一句话决定推出去 | A |")
    assert review.parse_ledger(reordered)["hypotheses"][0] == parsed["hypotheses"][0]
    broken = review.parse_ledger(LEDGER.replace("| 想法 | 为什么 |", "| 缺列 | 为什么 |"))
    assert broken["error"] and broken["proposals"] == []


def test_set_proposal_changes_only_status_and_inserts_experiment():
    updated = review.set_proposal(LEDGER, 0, "try", date(2026, 10, 11))
    parsed = review.parse_ledger(updated)
    assert parsed["proposals"][0]["status"] == "试（10/11）"
    assert len(parsed["experiments"]) == 2
    assert parsed["experiments"][1] == {"sent": "待开始", "title": "每天直播", "hypothesis": "—", "change": "每天直播", "metric": "直播人数", "check_on": "10/18", "result": "", "conclusion": ""}
    extra = "| 待开始 | 每天直播 | — | 每天直播 | 直播人数 | 10/18 |  |  |\n"
    assert updated.replace(extra, "").replace("试（10/11）", "待定").splitlines(keepends=True) == LEDGER.splitlines(keepends=True)
    skipped = review.set_proposal(LEDGER, 1, "skip", date(2026, 10, 11))
    assert skipped == LEDGER.replace("| 改开头 | 降跳出 | 10 分钟 | 2 秒跳出 | 3 | 待定 |", "| 改开头 | 降跳出 | 10 分钟 | 2 秒跳出 | 3 | 不试（10/11） |")
    with pytest.raises(ValueError):
        review.set_proposal(updated, 0, "try", date(2026, 10, 11))


def make_db(tmp_path):
    db, creator = tmp_path / "studio.db", tmp_path / "creator.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE videos (video_id TEXT, account_id INTEGER, platform TEXT, title TEXT, published_at TEXT);
            CREATE TABLE video_snapshots (video_id TEXT, fetched_at TEXT, likes INTEGER);
            CREATE TABLE post_snapshots (platform TEXT, post_id TEXT, fetched_at TEXT, views INTEGER);
        """)
    with sqlite3.connect(creator) as conn:
        conn.execute("CREATE TABLE creator_video_metrics (video_id TEXT, bounce_rate_2s REAL, completion_rate_5s REAL, avg_view_second REAL, view_count INTEGER, fan_increment INTEGER, raw_json TEXT)")
    return db, creator


def test_douyin_72h_all_mature_baseline_and_latest_valid_snapshot(tmp_path):
    db, creator = make_db(tmp_path)
    now = datetime.now(review.BJ)
    with sqlite3.connect(db) as conn:
        for i, likes in enumerate([100, 200, 600, None]):
            published = now - timedelta(days=8 - i) if likes is not None else now - timedelta(hours=40)
            conn.execute("INSERT INTO videos VALUES (?,1,'抖音',?,?)", (str(i), "标题" * 20, published.isoformat()))
            for hour, count in [(20, 1), (59, 9), (72, likes), (78, likes), (79, 9999)]:
                if hour <= 40 or likes is not None:
                    conn.execute("INSERT INTO video_snapshots VALUES (?,?,?)", (str(i), (published + timedelta(hours=hour)).isoformat(), count))
        conn.execute("INSERT INTO videos VALUES ('other',2,'douyin','别人',?)", ((now - timedelta(days=10)).isoformat(),))
        conn.execute("INSERT INTO video_snapshots VALUES ('other',?,99999)", ((now - timedelta(days=7)).isoformat(),))
    with sqlite3.connect(creator) as conn:
        conn.execute("INSERT INTO creator_video_metrics VALUES ('2',0.35,0.4,12.5,1000,6,'{\"video_info\": {\"duration\": 379552}}')")
    result = review.douyin_72h(db, creator, account_id=1, limit=2)
    assert result["median"] == 200 and result["n"] == 3
    assert len(result["rows"]) == 2
    pending, mature = result["rows"]
    assert pending["likes_72h"] is None and pending["status"] == "还不到 72 小时"
    assert mature["likes_72h"] == 600 and mature["multiple"] == 3
    assert mature["fans_per_1k"] == 6
    assert mature["views"] == 1000 and mature["fans"] == 6 and mature["duration_s"] == 379.552
    assert pending["duration_s"] is None
    assert mature["bounce_rate_2s"] == 0.35 and mature["completion_rate_5s"] == 0.4
    assert len(mature["title"]) == 20
    assert mature["time"] == (now - timedelta(days=6)).strftime("%H:%M")


def test_build_due_stuck_yesterday_and_brief(tmp_path):
    today = {"day": "2026-10-11", "days": [{"day": "2026-10-10", "ship": "miss"}], "streak": {"kind": "miss", "days": 2}}
    reach = {"days": [{"day": "2026-10-10", "by_platform": {"douyin": 30, "x": 100}}, {"day": "2026-10-09", "by_platform": {"douyin": 100, "x": 200}}]}
    home = {"money": {"total": 800, "yesterday": 50}, "upcoming": [{"title": "明天", "ready": False, "why": "骨架还没写"}, {"title": "后天", "ready": True}]}
    result = review.build(studio_db=tmp_path / "none.db", creator_db=tmp_path / "none2.db", account_id=None, x_daily_path=tmp_path / "none.json", today_payload=today, reach_payload=reach, home_payload=home, ledger_text=LEDGER.replace("发出后 72h", "10/10"), today=date(2026, 10, 11))
    assert result["stuck"]["days"] == 2 and len(result["stuck"]["options"]) == 5
    assert len(result["due"]) == 1
    assert result["yesterday"]["douyin"] == {"value": 30, "previous": 100}
    assert result["yesterday"]["money"] == {"yesterday": 50, "month": 800}
    assert result["next_missing"] == [{"title": "明天", "why": "骨架还没写"}]
    result["verdict"] = {"text": "今天再等一等。"}
    brief = review.brief_text(result)
    assert "[每日复盘]" in brief and "今天再等一等。" in brief and "该对账了" in brief
    prompt = review.verdict_prompt(result, "角色", "[战况] 抖音粉丝：现在 8,314")
    assert '"headline"' in prompt and "阿拉伯数字" in prompt and "叉平台" in prompt and "[战况] 抖音粉丝" in prompt
    assert "全中文" not in prompt
    assert result["facts"] == [["抖音", "没发（连续 2 天） · 播放 30"], ["X", "曝光 100"], ["收入", "¥50 · 本月 ¥800"]]


def test_build_reads_nightly_reports_and_adds_the_consult_row(tmp_path):
    folder = tmp_path / "report"
    folder.mkdir()
    (folder / "2026-10-10.json").write_text(json.dumps({"leads": 3, "booked": 1, "paid": None, "missing": ["收款"]}), encoding="utf-8")
    (folder / "2026-10-09.json").write_text(json.dumps({"leads": 1, "booked": 0, "paid": 0}), encoding="utf-8")
    (folder / "2026-09-01.json").write_text("{}", encoding="utf-8")  # 超过 14 天
    (folder / "2026-10-11.json").write_text("{}", encoding="utf-8")  # 今天的还没过完
    (folder / "坏了.json").write_text("{", encoding="utf-8")
    today = {"day": "2026-10-11", "days": [{"day": "2026-10-10", "ship": "ok"}], "streak": {"kind": "ok", "days": 1}}
    result = review.build(studio_db=tmp_path / "none.db", creator_db=tmp_path / "none2.db", account_id=None, x_daily_path=tmp_path / "none.json", today_payload=today, reach_payload={"days": []}, home_payload={}, ledger_text=LEDGER, today=date(2026, 10, 11), report_dir=folder)
    assert result["report"]["day"] == "2026-10-10" and result["report_days"] == 2
    assert [r["day"] for r in result["report_history"]] == ["2026-10-09", "2026-10-10"]
    assert result["facts"][-1] == ["咨询", "线索 3 · 约上 1 · 成交 没有记录"]
    prompt = review.verdict_prompt(result, "角色")
    assert "唯一的改法" in prompt and "report_days 不到 14" in prompt
    empty = review.build(studio_db=tmp_path / "none.db", creator_db=tmp_path / "none2.db", account_id=None, x_daily_path=tmp_path / "none.json", today_payload=today, reach_payload={"days": []}, home_payload={}, ledger_text=LEDGER, today=date(2026, 10, 11), report_dir=tmp_path / "nothing")
    assert empty["report"] is None and empty["report_days"] == 0 and len(empty["facts"]) == 3


def test_facts_prefer_x_backend_numbers_for_the_same_day():
    y = {"day": "2026-10-12", "ship": "ok", "streak": {"kind": "ok", "days": 1}, "douyin": {"value": 10463}, "x": {"value": 9}, "money": {"yesterday": None, "month": 0}}
    assert review.facts({"yesterday": y, "x": {"day": "2026-10-12", "impressions": 33347, "net_follows": 180}}) == [
        ["抖音", "发了 · 播放 10,463"], ["X", "曝光 33,347 · 净涨粉 +180"], ["收入", "¥没有记录 · 本月 ¥0"]]
    assert review.facts({"yesterday": y, "x": {"day": "2026-10-11", "impressions": 1}})[1] == ["X", "曝光 9"]


def test_parse_verdict_reads_the_json_and_keeps_a_plain_text_copy():
    raw = '```json\n{"headline": "抖音差 3.2 倍，卡在你 4 天没发", "wrong": "昨天又没发视频", "today": ["把《版本答案》发到抖音", " ", "回 10 条私信", "多的", "再多"], "wait": ["10/14 看踩坑清单 24 小时曝光", "b", "c"]}\n```'
    v = review.parse_verdict(raw)
    assert v["headline"] == "抖音差 3.2 倍，卡在你 4 天没发" and v["wrong"] == "昨天又没发视频"
    assert v["today"] == ["把《版本答案》发到抖音", "回 10 条私信", "多的"] and len(v["wait"]) == 2
    assert v["text"].splitlines()[:3] == ["抖音差 3.2 倍，卡在你 4 天没发", "你做错了：昨天又没发视频", "今天你做 1. 把《版本答案》发到抖音"]
    assert review.parse_verdict("昨天没出摊，今天先拍这一条。") is None
    assert review.parse_verdict('{"headline": ""}') is None
    assert review.parse_verdict('{"headline": "好", "today": "不是列表"}')["today"] == []


def test_verdict_cache_only_uses_tmp_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_HOME", str(tmp_path))
    assert review.load_verdict("2026-10-11") is None
    review.save_verdict("2026-10-11", "昨天发了，今天再等一等。")
    assert review.load_verdict("2026-10-11")["text"] == "昨天发了，今天再等一等。"
    assert review.load_verdict("2026-10-11")["at"]
    review.save_verdict("2026-10-11", {"error": "失败", "attempts": 2})
    assert review.load_verdict("2026-10-11") == {"error": "失败", "attempts": 2}
    with pytest.raises(ValueError):
        review.save_verdict("../../escape", "不要写")


def test_money_scoring_stops_without_changing_october_10():
    from content_studio import driver

    days = driver.kpi_range(date(2026, 10, 10), date(2026, 10, 13), date(2026, 10, 12),
                            posted={"2026-10-10", "2026-10-11", "2026-10-12"}, dms={}, started="2026-10-10",
                            money=set(), money_started="2026-10-10", money_ended="2026-10-11")
    assert [d['mn'] for d in days] == ['miss', 'n/a', 'n/a', 'n/a']
    assert driver.demerits(days) == 1
    assert driver.demerits(days[1:]) == 0
    recent = driver.kpi_days(date(2026, 10, 12), posted=set(), dms={}, started="2026-10-10",
                             money=set(), money_started="2026-10-10", money_ended="2026-10-11")
    assert recent[-2]['mn'] == recent[-1]['mn'] == 'n/a'


@pytest.fixture
def review_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from content_studio import web
    from tests.test_web import FakeClient

    monkeypatch.setenv('CONTENT_STUDIO_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('CONTENT_STUDIO_HERMES_HOME', str(tmp_path / 'hermes'))
    monkeypatch.setenv('CONTENT_STUDIO_CONSULTS', str(tmp_path / 'consults'))
    role = tmp_path / 'Wendy.md'
    role.write_text('你是测试 Wendy。', encoding='utf-8')
    monkeypatch.setenv('CONTENT_STUDIO_WENDY_ROLE', str(role))
    ledger = role.with_name('Wendy 实验账本.md')
    ledger.write_text(LEDGER, encoding='utf-8')
    monkeypatch.setattr(web, 'LEGACY_REPORT_DIRS', ())
    calls = []
    behavior = {'text': '昨天没出摊，今天先拍这一条。'}

    def fake(system, prompt, session_id):
        calls.append((system, prompt, session_id))
        if behavior.get('wait'):
            behavior['entered'].set()
            assert behavior['wait'].wait(5)
        if behavior.get('error'):
            raise RuntimeError(behavior['error'])
        return {'text': behavior['text'], 'session_id': None}

    app = web.create_app(store_path=tmp_path / 'studio.db', cookie_path=tmp_path / 'cookie', creator_db=None,
                         data_dir=tmp_path / 'data', downloads_dir=tmp_path / 'downloads', drafts_dir=tmp_path / 'drafts',
                         client_factory=FakeClient, start_worker=False, wendy_fn=fake)
    app.state.store.update_settings({'obsidian_vault': str(tmp_path / 'vault')})
    with TestClient(app, headers={'X-Content-Studio': '1'}) as client:
        yield client, behavior, calls, ledger
    app.state.store.close()


def wait_verdict(client):
    import time

    for _ in range(100):
        rv = client.get('/api/today/review').json()
        if rv['verdict'].get('state') != 'writing':
            return rv
        time.sleep(0.01)
    pytest.fail('复盘后台线程没有结束')


def test_review_api_cached_rewrite_and_shared_brief(review_client):
    client, behavior, calls, _ = review_client
    rv = client.get('/api/today/review').json()
    assert rv['verdict'] == {'state': 'waiting', 'from': '09:35'} and not calls  # 没开始写就不说「在写」
    assert client.post('/api/today/review/verdict').json() == {'started': True}
    rv = wait_verdict(client)
    assert rv['verdict']['text'] == behavior['text'] and rv['verdict']['at']
    assert len(calls) == 1
    assert calls[0][0].startswith('你是测试 Wendy。\n\n你在写今天早上给 作者 的复盘')
    assert '当天的 X 主打' in calls[0][0]
    assert '"headline"' in calls[0][1] and '[战况]' in calls[0][1] and calls[0][2] is None
    for _ in range(2):
        assert client.get('/api/today/review').json()['verdict'] == rv['verdict']
    assert len(calls) == 1
    brief = client.get('/api/wendy/brief').json()['text']
    assert '[每日复盘]' in brief and behavior['text'] in brief and 'X 昨天' in brief
    behavior['text'] = '今天再等一等。'
    assert client.post('/api/today/review/verdict').json()['started']
    assert wait_verdict(client)['verdict']['text'] == behavior['text']
    assert len(calls) == 2
    behavior['text'] = '{"headline": "X 差 1.2 倍", "wrong": "", "today": ["发抖音"], "wait": []}'
    assert client.post('/api/today/review/verdict').json()['started']
    v = wait_verdict(client)['verdict']
    assert v['headline'] == 'X 差 1.2 倍' and v['today'] == ['发抖音'] and v['text'] == 'X 差 1.2 倍\n今天你做 1. 发抖音' and v['at']
    assert 'X 差 1.2 倍' in client.get('/api/wendy/brief').json()['text']


def test_verdict_duplicate_start_does_not_invoke_twice(review_client):
    import threading

    client, behavior, calls, _ = review_client
    behavior.update(wait=threading.Event(), entered=threading.Event())
    try:
        assert client.post('/api/today/review/verdict').json()['started']
        assert behavior['entered'].wait(3)
        assert client.get('/api/today/review').json()['verdict'] == {'state': 'writing'}
        assert client.post('/api/today/review/verdict').json() == {'started': False}
    finally:
        behavior['wait'].set()
    assert wait_verdict(client)['verdict']['text']
    assert len(calls) == 1


def test_verdict_schedule_time_cache_retry_limit_and_stop(review_client):
    client, behavior, calls, _ = review_client
    tick = client.app.state.daily_review_tick
    day = datetime.now(review.BJ).replace(hour=9, minute=34, second=0, microsecond=0)
    assert tick(day) is False
    behavior['error'] = '模拟模型失败'
    for attempt in range(1, 4):
        assert tick(day.replace(minute=35)) is True
        assert wait_verdict(client)['verdict'] == {'error': '模拟模型失败', 'attempts': attempt}
    assert tick(day.replace(hour=12)) is False
    assert len(calls) == 3
    behavior.pop('error')
    assert client.post('/api/today/review/verdict').json()['started']  # 人可以再试
    assert wait_verdict(client)['verdict']['text']
    assert tick(day.replace(hour=13)) is False
    # 关闭应用后 stop_auto 已置位，下一天的自动检查也不能开新线程。
    client.__exit__(None, None, None)
    assert tick(day + timedelta(days=1)) is False


def test_proposal_api_changes_ledger_only_and_logs_git_failure(review_client, monkeypatch, caplog):
    import subprocess
    from content_studio.extras.team import routes

    client, _, _, ledger = review_client
    seen = []
    real_run = subprocess.run

    def fake_git(argv, **kwargs):
        if argv[:1] != ['git']:
            return real_run(argv, **kwargs)
        seen.append(argv)
        if 'commit' in argv:
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0, str(ledger.parent), '')

    monkeypatch.setattr(routes.subprocess, 'run', fake_git)
    response = client.post('/api/today/review/proposal', json={'index': 0, 'decision': 'try'})
    assert response.status_code == 200
    today = datetime.now(review.BJ).date()
    assert response.json()['proposals'][0]['status'] == f'试（{today.month}/{today.day}）'
    assert len(response.json()['experiments']) == 2
    assert ledger.read_text() == review.set_proposal(LEDGER, 0, 'try', today)
    assert seen[-1][-3:] == ['--only', '--', ledger.name]
    assert 'docs: 实验账本：每天直播 → 试' in seen[-1]
    assert 'ledger commit failed' in caplog.text
    assert client.post('/api/today/review/proposal', json={'index': 0, 'decision': 'try'}).status_code == 400
    before = ledger.read_text()
    for body in ({'index': -1, 'decision': 'try'}, {'index': 9, 'decision': 'skip'}, {'index': True, 'decision': 'try'}, {'index': 1, 'decision': 'delete'}):
        assert client.post('/api/today/review/proposal', json=body).status_code in (400, 422)
        assert ledger.read_text() == before


def test_review_money_uses_all_yesterday_rows_and_home_stops_scoring(review_client):
    client, _, _, _ = review_client
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for _ in range(10):
        assert client.post('/api/revenue', json={'day': yesterday, 'amount': 100, 'source': 'consult'}).status_code == 200
    home = client.get('/api/today/home').json()
    assert len(home['money']['rows']) == 8
    assert home['money']['scored'] is (date(2026, 10, 10) <= date.today() < date(2026, 10, 11))
    rv = client.get('/api/today/review').json()
    assert rv['yesterday']['money']['yesterday'] == 1000
    assert rv['yesterday']['money']['month'] == home['money']['total']


def test_x_follow_target_can_be_changed_through_settings(review_client):
    client, _, _, _ = review_client
    response = client.put('/api/settings', json={'x_follow_target': {'end': 12000}})
    assert response.status_code == 200
    assert response.json()['x_follow_target']['end'] == 12000
    assert client.get('/api/today/review').json()['x']['progress']['target']['end'] == 12000
    assert client.put('/api/settings', json={'x_follow_target': {'end_day': 'bad'}}).status_code == 400
