"""Convoso (dialer). Built from Convoso's API docs (call log: /v1/log/retrieve); not yet tried on a real account.

- Polled every 2 minutes: call log rows between two times, one hour at a time, all pages (limit + offset), oldest
  first, the whole hour in one batch (asking again for each small batch re-read the hour, QA 2026-10-23). Bookmark
  "<time>#0"; older bookmarks with "#<n>" still work.
- Every hour the catch-up reads the last 3 hours again (`recent`): a long call Convoso writes only when it ends is
  found then. Calls already processed are skipped.
- Convoso gives times in the account's own time zone (saved with the connection); CiV turns them into UTC.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..localtime import LocalTimes
from ..connector import CONNECTORS, Connector, Page, Record, raise_for_status

API = 'https://api.convoso.com/v1'
WINDOW = timedelta(hours=1)  # a busy call center makes thousands of calls an hour
LAG = timedelta(minutes=2)  # calls still being written wait for the next run
PAGE = 1000
TIMEOUT_SECONDS = 30
WHEN = '%Y-%m-%d %H:%M:%S'


class ConvosoError(Exception):
    """Convoso answered with success = false (wrong token, bad request…)."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConvosoError(f'Unknown account time zone "{name}"') from None


class Convoso(LocalTimes, Connector):
    mode = 'poll'
    source_grade = 'C'
    counts = ('calls',)

    def __init__(self, connection):
        super().__init__(connection)
        creds = connection.get_credentials()
        self.token = creds.get('key', '')
        # The visible Time zone box; older connections kept it in the hidden secret box.
        self.tz = zone(getattr(connection, 'setting', '') or creds.get('secret') or 'America/New_York')

    def _get(self, path: str, params: dict) -> dict:
        # POST keeps the token out of URLs and server logs.
        body = urllib.parse.urlencode({'auth_token': self.token, **params}).encode()
        request = urllib.request.Request(f'{API}/{path}', data=body, headers={'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
                answer = json.loads(reply.read())
        except urllib.error.HTTPError as error:
            raise_for_status(error)  # refused → reconnect; too many requests → wait
        if not answer.get('success'):
            raise ConvosoError(str(answer.get('text') or answer.get('code') or 'Convoso refused the request'))
        return answer.get('data') or {}

    def naive(self, row: dict) -> datetime:
        return datetime.strptime(row['call_date'], WHEN)

    def called_at(self, row: dict) -> datetime:
        return self.reading(row, self.naive(row))[0]

    def calls_between(self, start: datetime, end: datetime) -> list[dict]:
        """Every call from start up to (not including) end, oldest first."""
        params = {'start_time': start.astimezone(self.tz).strftime(WHEN),
                  'end_time': (end - timedelta(seconds=1)).astimezone(self.tz).strftime(WHEN), 'limit': PAGE, 'order': 'asc'}
        rows, offset = [], 0
        while True:
            data = self._get('log/retrieve', {**params, 'offset': offset})
            chunk = data.get('results') or []
            rows.extend(chunk)
            offset += len(chunk)
            if len(chunk) < PAGE or offset >= int(data.get('total_found') or 0):
                break
        self.remember(rows, self.naive)  # in Convoso's own order (oldest first): the clock-change hour
        return sorted((r for r in rows if start <= self.called_at(r) < end), key=lambda r: (self.called_at(r), str(r['id'])))

    def count_between(self, measure: str, start: datetime, end: datetime) -> int:
        """Convoso's own count of calls in the range (total_found of a one-row page)."""
        data = self._get('log/retrieve', {'start_time': start.astimezone(self.tz).strftime(WHEN),
                                          'end_time': (end - timedelta(seconds=1)).astimezone(self.tz).strftime(WHEN), 'limit': 1, 'offset': 0})
        return int(data.get('total_found') or 0)

    def record(self, row: dict) -> Record:
        numbers = [row.get('phone_number'), row.get('number_dialed'), row.get('caller_id_displayed')]
        return Record(source_record_id=str(row['id']), raw=json.dumps(row, sort_keys=True, separators=(',', ':')).encode(),
                      content_kind='call', changed_at=self.called_at(row), time_note=self.reading(row, self.naive(row))[1], phones=list(dict.fromkeys(n for n in numbers if n)))

    def fetch_one(self, record_id: str) -> Record | None:
        """TO CONFIRM on a real account: the call log filtered by its ID."""
        rows = [r for r in self._get('log/retrieve', {'id': record_id, 'limit': 1, 'offset': 0}).get('results') or [] if str(r.get('id')) == record_id]
        return self.record(rows[0]) if rows else None

    def changes_since(self, cursor: str, limit: int) -> Page:
        mark, _, done = (cursor or '').partition('#')
        begin = datetime.fromisoformat(mark) if mark else datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC)
        skip = int(done or 0)
        safe_now = datetime.now(UTC) - LAG
        if begin >= safe_now:
            return Page([], cursor, False)
        end = min(begin + WINDOW, safe_now)
        calls = self.calls_between(begin, end)
        # The whole hour at once (one request series per hour). Calls at exactly the bookmark time come first;
        # `skip` of them were done in an older-style batch.
        rest = [c for c in calls if self.called_at(c) == begin][skip:] + [c for c in calls if self.called_at(c) > begin]
        return Page([self.record(c) for c in rest], f'{end.isoformat()}#0', end < safe_now)

    def recent(self, since: datetime) -> list[Record]:
        safe_now = datetime.now(UTC) - LAG
        out, start = [], since
        while start < safe_now:
            end = min(start + WINDOW, safe_now)
            out += [self.record(c) for c in self.calls_between(start, end)]
            start = end
        return out


CONNECTORS['convoso'] = Convoso
