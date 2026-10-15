"""A pretend tool for the tests: a list of text messages with numbers, optional live notices, and a switch to fail."""
import hmac
import json
from datetime import UTC, datetime, timedelta

from apps.sync.connector import BadSignature, Connector, Page, Record

SECRET = b'fake-tool-signing-secret'
START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def message(n: int, body: str = 'Hi, your solar quote is ready') -> dict:
    return {'sid': f'SM{n:04d}', 'to': f'+1916555{n:04d}', 'body': body, 'at': (START + timedelta(minutes=n)).isoformat()}


class FakeTool(Connector):
    mode = 'live'
    messages: list[dict] = []  # shared by every instance, like a real account
    down = False

    def _record(self, m: dict) -> Record:
        return Record(source_record_id=m['sid'], raw=json.dumps(m, sort_keys=True).encode(), content_kind='text',
                      changed_at=datetime.fromisoformat(m['at']), phones=[m['to']])

    def changes_since(self, cursor: str, limit: int) -> Page:
        if FakeTool.down:
            raise ConnectionError('tool down')
        start = int(cursor or 0)
        chunk = FakeTool.messages[start:start + limit]
        return Page([self._record(m) for m in chunk], str(start + len(chunk)), start + len(chunk) < len(FakeTool.messages))

    def parse_event(self, body: bytes, headers: dict) -> list[Record]:
        expected = hmac.new(SECRET, body, 'sha256').hexdigest()
        if not hmac.compare_digest(expected, headers.get('X-Fake-Signature', '')):
            raise BadSignature
        return [self._record(json.loads(body))]


def sign(body: bytes) -> str:
    return hmac.new(SECRET, body, 'sha256').hexdigest()
