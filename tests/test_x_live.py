import json
from datetime import datetime, date
from content_studio.store import StudioStore
from content_studio.extras.xline import x_live


def at(time):
    return datetime.fromisoformat('2026-10-11T'+time+'+08:00')


def test_hourly_window_pagination_failure_and_restart(tmp_path, caplog):
    store = StudioStore(tmp_path/'db')
    sampler = x_live.HourlySampler()
    calls = []
    def get(url, query):
        calls.append((url, query))
        if url.endswith('/me'):
            return {'data': {'id': 'me', 'public_metrics': {'followers_count': 12}}}
        return {'data': [{'id': str(len(calls)), 'created_at': '2026-10-11T00:00:00Z', 'public_metrics': {'impression_count': 8}, 'referenced_tweets': [{'type': 'replied_to'}]}], 'meta': {'next_token': 'next'}}
    assert not sampler.tick(store, now=at('07:59'), get=get)
    assert sampler.tick(store, now=at('08:00'), get=get)
    assert len(calls) == 4  # me + 今天两页 + 最近 72 小时原创一次
    assert calls[1][1]['start_time'] == '2026-10-10T16:00:00Z'
    assert calls[3][1]['start_time'] == '2026-10-08T00:00:00Z' and calls[3][1]['exclude'] == 'retweets,replies'
    assert len(store.x_post_metrics()) == 3
    assert not sampler.tick(store, now=at('08:59'), get=get)
    assert not x_live.HourlySampler().tick(store, now=at('08:59'), get=get)
    def fail(*args):
        raise RuntimeError('offline')
    assert sampler.tick(store, now=at('09:00'), get=fail)
    assert 'offline' in caplog.text
    assert not x_live.HourlySampler().tick(store, now=at('09:30'), get=fail)


def test_live_totals_and_baseline(tmp_path):
    store = StudioStore(tmp_path/'db')
    with store.tx() as con:
        con.execute('CREATE TABLE IF NOT EXISTS x_followers_hourly(at TEXT PRIMARY KEY,followers INTEGER NOT NULL)')
        con.executemany('INSERT INTO x_followers_hourly VALUES (?,?)', [('2026-10-11T08:00:00+08:00', 100), ('2026-10-11T09:00:00+08:00', 115)])
    def record(pid, posted, fetched, views, kind='post'):
        store.add_x_post_metrics([dict(post_id=pid, posted_at=posted, impressions=views, bookmarks=views, profile_clicks=views, kind=kind)], fetched)
    record('old', '2026-10-09T08:00:00+08:00', '2026-10-10T23:00:00+08:00', 80)
    record('old', '2026-10-09T08:00:00+08:00', '2026-10-11T08:00:00+08:00', 100)
    record('new', '2026-10-10T18:00:00Z', '2026-10-11T08:00:00+08:00', 50, 'reply')
    record('no-baseline', '2026-10-09T08:00:00+08:00', '2026-10-11T08:00:00+08:00', 1000)
    record('old', '2026-10-09T08:00:00+08:00', '2026-10-11T01:00:00Z', 95)
    out = x_live.live(store.path, tmp_path/'queue', now=at('10:00'), analytics_root=tmp_path/'analytics')
    assert out['followers_today'] == 15
    assert out['impressions_today'] == 65
    assert out['bookmarks_today'] == out['profile_clicks_today'] == 65
    assert [r['impressions'] for r in out['impressions_hourly']] == [70, 65]


def test_kpi_is_posts_and_impressions(tmp_path):
    """10/12 作者：动作看发帖数（原创 + 引用，不含回复）和曝光，目标 100 条、20 万。"""
    store = StudioStore(tmp_path/'db')
    rows = [dict(post_id=f'q{i}', kind='quote', posted_at='2026-10-11T08:00:00+08:00') for i in range(30)]
    rows += [dict(post_id=f'p{i}', kind='post', posted_at='2026-10-11T09:00:00+08:00') for i in range(69)]
    rows += [dict(post_id=f'r{i}', kind='reply', posted_at='2026-10-11T09:00:00+08:00') for i in range(40)]
    rows += [dict(post_id='old', kind='post', posted_at='2026-10-10T09:00:00+08:00')]
    store.add_x_post_metrics(rows, at('10:00').isoformat())
    posts, views, replies = x_live.kpi(store.path, tmp_path/'queue', date(2026, 10, 11), impressions=150000)
    assert (posts['done'], posts['target'], posts['ok']) == (99, 100, False)
    assert (views['done'], views['target'], views['ok']) == (150000, 200000, False)
    assert replies['done'] == 40 and replies['target'] is None
    assert x_live.kpi(store.path, tmp_path/'queue', date(2026, 10, 11), {'x_kpi': {'posts': 99}})[0]['ok']


def test_empty_success_is_zero_not_unavailable(tmp_path):
    store = StudioStore(tmp_path/'db')
    assert x_live.live(store.path, tmp_path/'queue', now=at('08:00'))['impressions_today'] is None
    x_live.HourlySampler().tick(store, now=at('08:00'), get=lambda url, query: {'data': {'id': 'u', 'public_metrics': {'followers_count': 10}}} if url.endswith('/me') else {'data': []})
    assert x_live.live(store.path, tmp_path/'queue', now=at('08:01'))['impressions_today'] == 0


def test_review_reuses_kpi_and_reply_halt(tmp_path, monkeypatch):
    from content_studio import daily_review
    from content_studio.extras.xline import x_replies
    store = StudioStore(tmp_path/'db')
    queue = tmp_path/'queue'
    queue.write_text(json.dumps({'days': {'2026-10-10': {'posts': [dict(state='sent', long=True, format='article'), dict(state='sent', long=True, format='article')]}}}))
    monkeypatch.setattr(x_replies, 'stop_message', lambda **kwargs: 'X 拦了回复：403 automated，今天停了')
    review = daily_review.x_yesterday(store.path, queue, today=date(2026,10,11), analytics_root=tmp_path/'analytics')
    assert review['kpi'] == x_live.kpi(store.path, queue, date(2026,10,10), impressions=review['impressions'])
    text = '\n'.join(daily_review.x_brief(review))
    assert '昨天 KPI：' in text and '发帖 0/100（未做到）' in text
    assert 'X 拦了回复：403 automated，今天停了' in text


def test_database_failure_only_logs_and_never_calls_api(caplog):
    class BrokenStore:
        def tx(self):
            raise OSError('database unavailable')
    def forbidden(*args):
        raise AssertionError('API must not run without persisted marker')
    assert x_live.HourlySampler().tick(BrokenStore(), now=at('08:00'), get=forbidden)
    assert 'database unavailable' in caplog.text


def test_no_today_reading_uses_newer_daily_count_without_fake_growth(tmp_path):
    store = StudioStore(tmp_path/'db')
    with store.tx() as con:
        con.execute('CREATE TABLE IF NOT EXISTS x_followers_hourly(at TEXT PRIMARY KEY,followers INTEGER NOT NULL)')
        con.execute('INSERT INTO x_followers_hourly VALUES (?,?)', ('2026-10-09T20:00:00+08:00', 80))
        con.execute("INSERT INTO follower_counts(day,platform,followers,source,updated_at) VALUES ('2026-10-10','x',100,'auto','2026-10-10T23:00:00+08:00')")
    out = x_live.live(store.path, tmp_path/'queue', now=at('08:00'))
    assert out['followers_now'] == out['followers_midnight'] == 100
    assert out['followers_today'] is None


def test_missing_metric_does_not_masquerade_as_complete_total(tmp_path):
    store = StudioStore(tmp_path/'db')
    store.add_x_post_metrics([dict(post_id='a', posted_at=at('08:00').isoformat(), impressions=10, profile_clicks=3), dict(post_id='b', posted_at=at('08:00').isoformat(), impressions=20)], at('09:00').isoformat())
    out = x_live.live(store.path, tmp_path/'queue', now=at('10:00'))
    assert out['impressions_today'] == 30
    assert out['profile_clicks_today'] is None
    assert out['bookmarks_today'] is None


def test_today_growth_counts_from_yesterdays_last_reading(tmp_path):
    """10/11 第一次读数在 19:36：起点不能是今天第一次读数（那样涨粉永远是 0），要用昨天最后一次。"""
    store = StudioStore(tmp_path/'db')
    with store.tx() as con:
        con.execute('CREATE TABLE IF NOT EXISTS x_followers_hourly(at TEXT PRIMARY KEY,followers INTEGER NOT NULL)')
        con.execute('INSERT INTO x_followers_hourly VALUES (?,?)', ('2026-10-11T19:36:00+08:00', 2630))
        con.execute("INSERT INTO follower_counts(day,platform,followers,source,updated_at) VALUES ('2026-10-10','x',2423,'auto','2026-10-10T23:55:00+08:00')")
    out = x_live.live(store.path, tmp_path/'queue', now=datetime(2026, 10, 11, 20, 0, tzinfo=x_live.BJ))
    assert out['followers_midnight'] == 2423 and out['followers_today'] == 207


def test_a_failed_hour_is_remembered_and_cleared_by_the_next_good_one(tmp_path):
    # 10/20：X API 额度用完（402）时页面上没一句话，X 的数悄悄停在昨天
    store = StudioStore(tmp_path/'db')
    def broke(url, query):
        raise RuntimeError('返回 402：{"detail":"credits depleted","status":402}')
    x_live.HourlySampler().tick(store, now=at('09:00'), get=broke)
    failed = x_live.read_failure(store.path)
    assert failed and failed['hour'].endswith('T09') and '额度用完' in failed['why']
    ok = lambda url, query: {'data': {'id': 'u', 'public_metrics': {'followers_count': 10}}} if url.endswith('/me') else {'data': []}
    x_live.HourlySampler().tick(store, now=at('10:00'), get=ok)
    assert x_live.read_failure(store.path) is None
