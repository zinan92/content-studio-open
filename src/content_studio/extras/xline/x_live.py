"""X 小时采样与同口径的实时看板；只读 API、可注入请求函数。"""
from datetime import datetime, date, time, timedelta, timezone
import json
import logging
from pathlib import Path
import urllib.parse
import urllib.request

from ... import platform_stats
from ...daily_review import _read_rows, _stamp

BJ = timezone(timedelta(hours=8))
DEFAULT_KPI = {"posts": 100, "impressions": 200000, "quotes": 20, "replies_min": 100, "replies_max": 200, "articles": 2, "long_total": 3}
BASIS = "今天发的帖子（含回复）最新累计数 + 老原创帖较昨天最后读数的增量；老帖没有昨天读数不计。"


def follow_progress(current, today, settings=None, as_of=None):
    from ...store import DEFAULT_SETTINGS
    target = {**DEFAULT_SETTINGS['x_follow_target'], **(settings or {}).get('x_follow_target', {})}
    start, end = date.fromisoformat(target['start_day']), date.fromisoformat(target['end_day'])
    fraction = min(1, max(0, (today-start).days / max(1, (end-start).days)))
    expected = round(target['start'] + (target['end']-target['start'])*fraction)
    gap = current-expected if current is not None else None
    return dict(current=current, expected=expected, gap=gap, bad=gap is not None and gap < -expected*.2, as_of=as_of, target=target)


def kpi(studio_db, x_daily_path, day, settings=None, impressions=None):
    """10/12 作者：动作看两个——发帖数（原创 + 引用，不含回复，和 X 后台的 Posts 一个口径）和曝光；
    结果看涨粉和粉丝数（在 live / 复盘里）。回复数只是附带看一眼，不设目标。"""
    target = {**DEFAULT_KPI, **(settings or {}).get('x_kpi', {})}
    ids = {'post': set(), 'quote': set(), 'reply': set()}
    for row in _read_rows(studio_db, 'SELECT post_id, kind, posted_at FROM x_post_metrics'):
        posted = _stamp(row['posted_at'])
        if posted and posted.date() == day and row['kind'] in ids:
            ids[row['kind']].add(row['post_id'])
    posts = len(ids['post'] | ids['quote'])
    return [dict(key='posts', label='发帖', done=posts, target=target['posts'], ok=posts >= target['posts']),
            dict(key='impressions', label='曝光', done=impressions, target=target['impressions'],
                 ok=impressions is not None and impressions >= target['impressions']),
            dict(key='replies', label='回复', done=len(ids['reply']), target=None, ok=None)]


class HourlySampler:
    def __init__(self):
        self.last_hour = None

    def tick(self, store, *, now=None, get=None):
        now = (now or datetime.now(BJ)).astimezone(BJ)
        hour = now.strftime('%Y-%m-%dT%H')
        if now.hour < 8 or self.last_hour == hour:
            return False
        calls = count = 0
        def request(url, query):
            nonlocal calls
            calls += 1
            return get(url, query)
        try:
            with store.tx() as conn:
                conn.execute('CREATE TABLE IF NOT EXISTS x_live_samples(hour TEXT PRIMARY KEY, at TEXT NOT NULL, ok INTEGER NOT NULL DEFAULT 0)')
                if conn.execute('SELECT 1 FROM x_live_samples WHERE hour=?', (hour,)).fetchone():
                    return False
                conn.execute('INSERT INTO x_live_samples(hour,at) VALUES (?,?)', (hour, now.isoformat(timespec='seconds')))
            self.last_hour = hour  # Persist before calling the paid API, including failed attempts.
            if get is None:
                from ...x_post import authorization_header, load_credentials
                creds = load_credentials()
                def get(url, query):
                    full = url + '?' + urllib.parse.urlencode(query)
                    return platform_stats._get_json(urllib.request.Request(full, headers={'Authorization': authorization_header('GET', url, creds, query=query)}))
            me = request(platform_stats.X_API+'/users/me', {'user.fields': 'public_metrics'}).get('data') or {}
            if not me.get('id'):
                raise ValueError('X 没返回账号 id')
            stamp = now.isoformat(timespec='seconds')
            followers = (me.get('public_metrics') or {}).get('followers_count')
            if followers is not None:
                with store.tx() as conn:
                    conn.execute('CREATE TABLE IF NOT EXISTS x_followers_hourly(at TEXT PRIMARY KEY, followers INTEGER NOT NULL)')
                    conn.execute('INSERT OR REPLACE INTO x_followers_hourly VALUES (?,?)', (stamp, followers))
            query = {'start_time': datetime.combine(now.date(), time(), BJ).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'exclude': 'retweets', 'max_results': '100', 'tweet.fields': 'public_metrics,non_public_metrics,created_at,referenced_tweets'}
            for _ in range(2):
                response = request(platform_stats.X_API+f"/users/{me['id']}/tweets", query)
                rows = response.get('data') or []
                count += len(rows)
                store.add_x_post_metrics([platform_stats.parse_x_post(row) for row in rows], stamp)
                token = (response.get('meta') or {}).get('next_token')
                if not token:
                    break
                query = {**query, 'pagination_token': token}
            # 10/12：整点曝光是 0——老原创帖今天涨的要等 9:30 的日采集。每小时多读一次最近 72 小时的原创（不含回复）
            old = request(platform_stats.X_API+f"/users/{me['id']}/tweets", {
                'start_time': (now - timedelta(hours=72)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'exclude': 'retweets,replies', 'max_results': '100', 'tweet.fields': 'public_metrics,non_public_metrics,created_at,referenced_tweets'})
            rows = old.get('data') or []
            count += len(rows)
            store.add_x_post_metrics([platform_stats.parse_x_post(row) for row in rows], stamp)
            with store.tx() as conn:
                conn.execute('UPDATE x_live_samples SET ok=1 WHERE hour=?', (hour,))
        except Exception as exc:
            logging.getLogger(__name__).warning('X 小时采样失败 hour=%s: %s', hour, exc)
            # 10/20：额度用完（402）时页面上一句话都没有，X 的数就悄悄停在昨天。记下最近一次为什么没读成，左栏底下报出来
            try:
                with store.tx() as conn:
                    _ensure_error_column(conn)
                    conn.execute('UPDATE x_live_samples SET error=? WHERE hour=?', (str(exc)[:300], hour))
            except Exception:  # noqa: BLE001 — 记不下来不影响采样本身
                pass
        finally:
            logging.getLogger(__name__).info('X 小时采样 hour=%s calls=%s rows=%s', hour, calls, count)
        return True


def _ensure_error_column(conn):
    cols = {row[1] for row in conn.execute('PRAGMA table_info(x_live_samples)')}
    if 'error' not in cols:
        conn.execute('ALTER TABLE x_live_samples ADD COLUMN error TEXT')


def read_failure(studio_db):
    """最近一次整点采样没读成：返回 {hour, error, why}；最近一次读成了（或从没采过）返回 None。"""
    try:
        rows = _read_rows(studio_db, 'SELECT * FROM x_live_samples ORDER BY hour DESC LIMIT 1')
    except Exception:  # noqa: BLE001 — 表还没建
        return None
    if not rows or rows[0].get('ok') or not rows[0].get('error'):
        return None
    err = rows[0]['error']
    why = 'X API 额度用完了，去 X 开发者后台充值' if ('402' in err or 'credits' in err.lower()) else '读 X 数据出错了'
    return {'hour': rows[0]['hour'], 'error': err, 'why': why}


def live(studio_db, x_daily_path, *, now=None, settings=None, analytics_root=None):
    from ... import x_analytics
    now = (now or datetime.now(BJ)).astimezone(BJ)
    day, yesterday = now.date(), now.date()-timedelta(days=1)
    followers = [r for r in _read_rows(studio_db, 'SELECT * FROM x_followers_hourly ORDER BY at') if _stamp(r['at']) and _stamp(r['at']) <= now]
    followers.sort(key=lambda r: _stamp(r['at']))
    today_followers = [r for r in followers if _stamp(r['at']).date() == day]
    fallback = _read_rows(studio_db, "SELECT followers,updated_at FROM follower_counts WHERE platform='x' AND day=?", (yesterday.isoformat(),))
    # 今天涨粉的起点：昨天最后一次读数（每小时那张表，没有就用每天同步记的昨天那个数）；都没有才用今天第一次读数
    before = [(r['followers'], _stamp(r['at'])) for r in followers if _stamp(r['at']).date() < day]
    if fallback:
        before.append((fallback[0]['followers'], _stamp(fallback[0]['updated_at']) or datetime.combine(yesterday, time.max, BJ)))
    midnight = (max(before, key=lambda pair: pair[1])[0] if before
                else today_followers[0]['followers'] if today_followers else None)
    evidence = [(r['followers'], _stamp(r['at'])) for r in followers]
    if fallback:
        evidence.append((fallback[0]['followers'], _stamp(fallback[0]['updated_at']) or datetime.combine(yesterday, time.max, BJ)))
    current = max(evidence, key=lambda pair: pair[1])[0] if evidence else None
    rows = [r for r in _read_rows(studio_db, 'SELECT * FROM x_post_metrics ORDER BY fetched_at') if _stamp(r['fetched_at']) and _stamp(r['fetched_at']) <= now]
    rows.sort(key=lambda r: _stamp(r['fetched_at']))
    sampling = [r for r in _read_rows(studio_db, 'SELECT * FROM x_live_samples WHERE ok=1') if _stamp(r['at']) and _stamp(r['at']).date() == day and _stamp(r['at']) <= now]
    baseline, samples = {}, {}
    for row in rows:
        fetched = _stamp(row['fetched_at'])
        if fetched.date() == yesterday:
            baseline[row['post_id']] = row
        elif fetched.date() == day:
            samples.setdefault(fetched.replace(minute=0, second=0, microsecond=0).isoformat(), []).append(row)
    latest = {}
    def totals():
        result = {}
        for field in ('impressions', 'profile_clicks', 'bookmarks'):
            values, missing = [], False
            for pid, row in latest.items():
                posted = _stamp(row['posted_at'])
                if not posted:
                    continue
                if posted.date() == day:
                    if row[field] is None:
                        missing = True
                    else:
                        values.append(row[field])
                elif posted.date() < day and row['kind'] == 'post' and pid in baseline:
                    if row[field] is None or baseline[pid][field] is None:
                        missing = True
                    else:
                        values.append(row[field]-baseline[pid][field])
            # A missing private metric is unknown, never silently a partial total.
            result[field] = None if missing else sum(values) if values else 0 if sampling else None
        return result
    for sample in sampling:
        samples.setdefault(_stamp(sample['at']).replace(minute=0, second=0, microsecond=0).isoformat(), [])
    series = []
    for at, batch in sorted(samples.items()):
        for row in batch:
            latest[row['post_id']] = row
        series.append(dict(at=at, **totals()))
    total = totals()
    from ...paths import config_dir
    analytics = x_analytics.latest(analytics_root if analytics_root is not None else config_dir() / 'x-analytics')
    verified = next((r.get('impressions') for r in (analytics or {}).get('daily', []) if r.get('date') == yesterday.isoformat() and r.get('verified_only') == 1), None)
    updated = max([r['at'] for r in today_followers] + [r['fetched_at'] for r in latest.values()] + [r['at'] for r in sampling], default=None, key=lambda at: _stamp(at))
    return dict(followers_now=current, followers_midnight=midnight, followers_today=current-midnight if today_followers and midnight is not None else None,
                followers_hourly=today_followers, impressions_today=total['impressions'], impressions_hourly=series,
                profile_clicks_today=total['profile_clicks'], bookmarks_today=total['bookmarks'], impressions_basis=BASIS,
                progress=follow_progress(current, day, settings, updated), verified_yesterday=verified, updated_at=updated,
                kpi=kpi(studio_db, x_daily_path, day, settings, total['impressions']))
