"""Convoso (dialer). Built from Convoso's API docs (call log: /v1/log/retrieve); not yet tried on a real account.

- Polled every 2 minutes: call log rows between two times, one hour at a time, all pages (limit + offset), oldest
  first. Bookmark "<time>#<how many at exactly that time are done>", so nothing is skipped or doubled.
- Convoso gives times in the account's own time zone (saved with the connection); CiV turns them into UTC.
"""
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..connector import CONNECTORS, Connector, Page, Record

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


class Convoso(Connector):
    mode = 'poll'
    source_grade = 'C'
    counts = ('calls',)

    def __init__(self, connection):
        super().__init__(connection)
        creds = connection.get_credentials()
        self.token = creds.get('key', '')
        self.tz = zone(creds.get('secret') or 'America/New_York')

    def _get(self, path: str, params: dict) -> dict:
        # POST keeps the token out of URLs and server logs.
        body = urllib.parse.urlencode({'auth_token': self.token, **params}).encode()
        request = urllib.request.Request(f'{API}/{path}', data=body, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            answer = json.loads(reply.read())
        if not answer.get('success'):
            raise ConvosoError(str(answer.get('text') or answer.get('code') or 'Convoso refused the request'))
        return answer.get('data') or {}

    def called_at(self, row: dict) -> datetime:
        return datetime.strptime(row['call_date'], WHEN).replace(tzinfo=self.tz).astimezone(UTC)

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
        return sorted((r for r in rows if start <= self.called_at(r) < end), key=lambda r: (self.called_at(r), str(r['id'])))

    def count_between(self, measure: str, start: datetime, end: datetime) -> int:
        """Convoso's own count of calls in the range (total_found of a one-row page)."""
        data = self._get('log/retrieve', {'start_time': start.astimezone(self.tz).strftime(WHEN),
                                          'end_time': (end - timedelta(seconds=1)).astimezone(self.tz).strftime(WHEN), 'limit': 1, 'offset': 0})
        return int(data.get('total_found') or 0)

    def record(self, row: dict) -> Record:
        numbers = [row.get('phone_number'), row.get('number_dialed'), row.get('caller_id_displayed')]
        return Record(source_record_id=str(row['id']), raw=json.dumps(row, sort_keys=True, separators=(',', ':')).encode(),
                      content_kind='call', changed_at=self.called_at(row), phones=list(dict.fromkeys(n for n in numbers if n)))

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
        # Calls at exactly the bookmark time come first; `skip` of them were done in the last batch.
        rest = [c for c in calls if self.called_at(c) == begin][skip:] + [c for c in calls if self.called_at(c) > begin]
        batch = rest[:limit]
        if len(rest) > limit:
            last = self.called_at(batch[-1])
            same = sum(1 for c in batch if self.called_at(c) == last) + (skip if last == begin else 0)
            return Page([self.record(c) for c in batch], f'{last.isoformat()}#{same}', True)
        return Page([self.record(c) for c in batch], f'{end.isoformat()}#0', end < safe_now)


CONNECTORS['convoso'] = Convoso
