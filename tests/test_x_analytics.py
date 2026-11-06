from datetime import datetime, timedelta, date
import json
from pathlib import Path
import subprocess
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from content_studio import x_analytics as analytics, platform_stats, daily_review
from content_studio.store import StudioStore, StoreError

CSV = 'date,verified_only,impressions,new_follows,unfollows\n2026-10-10,0,"91,604",120,20\n2026-10-10,1,1.2K,,\n'


def write_day(folder, text=CSV):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'daily.csv').write_text(text)


def test_originals_survive_120_replies_and_metrics_are_stored(tmp_path, monkeypatch, caplog):
    calls = []
    originals = [{'id': str(i), 'text': '原创', 'public_metrics': {'impression_count': 100, 'bookmark_count': 5},
                  'non_public_metrics': {'user_profile_clicks': 3}, 'created_at': '2026-10-10T02:00:00Z'} for i in range(3)]
    originals[2]['referenced_tweets'] = [{'type': 'quoted', 'id': 'other'}]
    replies = [{'id': f'r{i}', 'referenced_tweets': [{'type': 'replied_to'}], 'public_metrics': {'impression_count': i}} for i in range(120)]

    def get(req):
        if req.full_url.endswith('/users/me'):
            return {'data': {'id': '42'}}
        query = parse_qs(urlparse(req.full_url).query)
        calls.append(query)
        assert query['max_results'] == ['100']
        assert set(query['tweet.fields'][0].split(',')) == {'public_metrics', 'non_public_metrics', 'created_at', 'referenced_tweets'}
        return {'data': originals if query['exclude'] == ['retweets,replies'] else replies[:100], 'errors': [{'detail': 'non_public unavailable for old posts'}]}

    monkeypatch.setattr(platform_stats, '_get_json', get)
    monkeypatch.setattr('content_studio.x_post.authorization_header', lambda *a, **kw: 'fake')
    with caplog.at_level('INFO'):
        store = StudioStore(tmp_path / 'studio.db')
        platform_stats.sync(store, {'x': lambda: platform_stats.x_posts({'fake': 'yes'})})
    assert len(calls) == 2
    snapshots = store.post_snapshots('x', '2000-01-01')
    assert {str(i) for i in range(3)} <= {r['video_id'] for r in snapshots}
    rows = {r['post_id']: r for r in store.x_post_metrics()}
    assert rows['0']['kind'] == 'post' and rows['2']['kind'] == 'quote' and rows['r0']['kind'] == 'reply'
    assert rows['0']['bookmarks'] == 5 and rows['0']['profile_clicks'] == 3
    assert rows['r0']['profile_clicks'] is None
    assert caplog.text.count('X API day=') == 3
    store.close()


def test_paid_x_fetch_is_never_retried(tmp_path):
    calls = []
    def fail():
        calls.append(1)
        raise platform_stats.StatsError('失败')
    store = StudioStore(tmp_path / 's.db')
    assert not platform_stats.sync(store, {'x': fail})['x']['ok']
    assert len(calls) == 1
    store.close()


def test_csv_numbers_blanks_content_and_latest_skips_failed(tmp_path):
    good = tmp_path / '2026-10-11'
    write_day(good)
    (good / 'content.csv').write_text('post_id,impressions,bookmarks,text\n2107463816468455566,2M, 3.5K ,测试\n')
    result = analytics.read_day(good)
    assert result['daily'][0]['impressions'] == 91604
    assert result['daily'][1]['impressions'] == 1200 and result['daily'][1]['new_follows'] is None
    assert result['content'][0] == {'post_id': '2107463816468455566', 'impressions': 2000000, 'bookmarks': 3500, 'text': '测试'}
    bad = tmp_path / '2026-10-12'
    write_day(bad)
    (bad / 'error.txt').write_text('失败')
    write_day(tmp_path / '2026-10-13', 'broken\n')
    assert analytics.latest(tmp_path) == result
    assert analytics.latest(tmp_path / 'missing') is None


def test_due_bj_time_once_restart_and_command(tmp_path, monkeypatch):
    (tmp_path / 'spec.md').write_text('作者 的原样指令')
    monkeypatch.setenv('CONTENT_STUDIO_CODEX_BIN', '/fake/codex')
    calls = []
    def runner(argv, **kw):
        calls.append(argv)
        assert kw['input'] == '作者 的原样指令' and kw['timeout'] == 1800
        assert kw['cwd'] == tmp_path / '2026-10-11'
        assert argv == ['/fake/codex', 'exec', '-C', str(tmp_path / '2026-10-11'), '-s', 'workspace-write', '--skip-git-repo-check', '-o', 'last.txt', '-']
        write_day(Path(argv[3]))
        return subprocess.CompletedProcess(argv, 0, '', '')
    now = datetime(2026, 10, 11, 10, 29, tzinfo=analytics.BJ)
    assert not analytics.run_due(tmp_path, now=now, runner=runner)
    assert analytics.run_due(tmp_path, now=now.replace(minute=31), runner=runner)
    assert not analytics.run_due(tmp_path, now=now.replace(hour=23), runner=runner)
    assert len(calls) == 1
    assert analytics.latest(tmp_path)
    stop = threading.Event()
    stop.set()
    analytics.daily_loop(tmp_path, stop, runner=lambda *a, **k: pytest.fail('stopped'))


@pytest.mark.parametrize('mode', ['exit', 'missing', 'timeout', 'exception'])
def test_failure_is_recorded_and_never_retried(tmp_path, mode):
    (tmp_path / 'spec.md').write_text('spec')
    calls = []
    def runner(argv, **kw):
        calls.append(1)
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(argv, 1800)
        if mode == 'exception':
            raise RuntimeError('fake')
        return subprocess.CompletedProcess(argv, 1 if mode == 'exit' else 0, '', 'failed')
    now = datetime(2026, 10, 11, 10, 31, tzinfo=analytics.BJ)
    assert not analytics.run_due(tmp_path, now=now, runner=runner)
    assert (tmp_path / '2026-10-11/error.txt').is_file()
    assert not analytics.run_due(tmp_path, now=now, runner=runner)
    assert len(calls) == 1 and analytics.latest(tmp_path) is None


def test_missing_spec_skips_and_logs_once(tmp_path, caplog):
    with caplog.at_level('INFO'):
        for _ in range(2):
            assert not analytics.run_due(tmp_path, now=datetime(2026, 10, 11, 11), runner=lambda *a, **k: pytest.fail('missing spec'))
    assert caplog.text.count('spec.md 不存在') == 1


def test_review_backend_fallback_progress_and_26h_metrics(tmp_path):
    store = StudioStore(tmp_path / 'studio.db')
    store.set_followers('2026-10-09', 'x', 2423, 'auto')
    store.set_followers('2026-10-10', 'x', 2500, 'auto')
    root = tmp_path / 'analytics'
    write_day(root / '2026-10-11')
    queue = tmp_path / 'x_daily.json'
    queue.write_text(json.dumps({'days': {'2026-10-10': {'posts': [
        {'url': 'https://x.com/i/status/1', 'long': True, 'format': 'post'},
        {'url': 'https://x.com/i/status/2', 'long': True, 'format': 'article'},
    ]}}}))
    sent = datetime(2026, 10, 10, 1, tzinfo=analytics.BJ)
    for hours, views in [(1, 2), (24, 1000), (26, 2000), (27, 99999)]:
        store.add_x_post_metrics([{'post_id': str(i), 'kind': kind, 'published_at': sent.isoformat(), 'views': views + i,
                                  'bookmarks': 20 if i else 0, 'title': '正文' * 40}
                                 for i, kind in enumerate(['post', 'post', 'post', 'quote', 'reply'])], (sent + timedelta(hours=hours)).isoformat())
    target = {'x_follow_target': {'start_day': '2026-10-11', 'start': 2500, 'end_day': '2026-10-31', 'end': 10000}}
    x = daily_review.x_yesterday(store.path, queue, today=date(2026, 10, 11), reach_value=42, analytics_root=root, settings=target)
    assert x['impressions'] == 91604 and x['verified_impressions'] == 1200
    assert x['verified_ratio'] == pytest.approx(1200 / 91604)
    assert x['net_follows'] == 100
    assert x['progress']['current'] == x['progress']['expected'] == 2500
    assert not x['progress']['bad']
    assert [r['post_id'] for r in x['top']] == ['2', '1', '0']
    assert len(x['top'][0]['text']) == 40
    assert x['top'][0]['impressions'] == 2002
    assert x['top'][0]['bookmarks_per_1k'] == pytest.approx(20 / 2002 * 1000)
    assert [r['sent'] for r in x['kinds']] == [1] * 5
    assert x['kinds'][0]['bookmarks_per_1k'] == 0
    fallback = daily_review.x_yesterday(store.path, queue, today=date(2026, 10, 11), reach_value=42, analytics_root=root / 'missing', settings=target)
    assert fallback['impressions'] == 42 and fallback['verified_impressions'] is None and fallback['net_follows'] == 77
    later = daily_review.x_yesterday(store.path, queue, today=date(2026, 10, 21), analytics_root=root, settings=target)
    assert later['progress']['expected'] == 6250 and later['progress']['bad']
    assert later['impressions'] is None  # 过期后台数据不能当昨天
    assert 'X 昨天' in daily_review.brief_text({'x': x})
    store.update_settings({'x_follow_target': {'end': 12000}})
    assert store.settings()['x_follow_target']['end'] == 12000
    with pytest.raises(StoreError):
        store.update_settings({'x_follow_target': {'end_day': '2025-12-01'}})
    store.close()


def test_missing_spec_can_be_supplied_later_and_concurrent_tick_does_not_repeat(tmp_path):
    now = datetime(2026, 10, 11, 11, tzinfo=analytics.BJ)
    assert not analytics.run_due(tmp_path, now=now, runner=lambda *a, **k: pytest.fail('missing spec'))
    (tmp_path / 'spec.md').write_text('spec')
    entered, release = threading.Event(), threading.Event()
    calls = []
    def runner(argv, **kw):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        write_day(Path(argv[3]))
        return subprocess.CompletedProcess(argv, 0, '', '')
    thread = threading.Thread(target=lambda: analytics.run_due(tmp_path, now=now, runner=runner))
    thread.start()
    try:
        assert entered.wait(5)
        assert not analytics.run_due(tmp_path, now=now, runner=runner)
        assert analytics.latest(tmp_path) is None
    finally:
        release.set()
        thread.join(5)
    assert len(calls) == 1 and analytics.latest(tmp_path)
