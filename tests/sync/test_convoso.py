"""Convoso adapter against a pretend Convoso that behaves like its docs: call log by time range, limit + offset pages,
times in the account's time zone, success = false on errors."""
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.connections import testers
from apps.connections.models import Connection, Status
from apps.ledger.models import Fingerprint
from apps.sync import engine, handoff
from apps.sync.connectors import convoso as cv
from apps.sync.models import SyncCursor

pytestmark = pytest.mark.django_db
LA = ZoneInfo('America/Los_Angeles')
DAY = datetime(2026, 10, 1, tzinfo=UTC)


def call(n: int, at_utc: datetime, status='NI') -> dict:
    return {'id': str(9000 + n), 'lead_id': str(n), 'campaign': 'SP-Q3-Roof', 'phone_number': f'916555{n:04d}',
            'number_dialed': f'1916555{n:04d}', 'caller_id_displayed': '4805550000', 'status': status, 'call_length': '42',
            'call_type': 'OUTBOUND', 'call_date': at_utc.astimezone(LA).strftime(cv.WHEN)}


class FakeConvoso:
    def __init__(self, calls, page=3, fail=False):
        self.calls, self.page, self.fail = calls, page, fail

    def __call__(self, adapter, path, params):
        assert path == 'log/retrieve'
        if self.fail:
            raise cv.ConvosoError('Invalid auth token')
        lo = datetime.strptime(params['start_time'], cv.WHEN).replace(tzinfo=LA)
        hi = datetime.strptime(params['end_time'], cv.WHEN).replace(tzinfo=LA)
        hits = sorted((c for c in self.calls if lo <= datetime.strptime(c['call_date'], cv.WHEN).replace(tzinfo=LA) <= hi),
                      key=lambda c: c['call_date'])
        limit = min(int(params['limit']), self.page)  # Convoso may return fewer than asked
        chunk = hits[int(params['offset']):int(params['offset']) + limit]
        return {'offset': params['offset'], 'limit': limit, 'total_found': len(hits), 'entries': len(chunk), 'results': chunk}


@pytest.fixture
def received(monkeypatch):
    got = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, conn, record, tokens: got.append((record.source_record_id, record.changed_at, tokens))])
    return got


@pytest.fixture
def conn(company):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider='convoso', status=Status.CONNECTED)
    c.set_credentials({'key': 'tok', 'secret': 'America/Los_Angeles'})
    c.save()
    return c


@pytest.fixture
def clock(monkeypatch):
    def at(moment):
        monkeypatch.setattr(cv, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: moment)}))
    return at


def use(monkeypatch, api):
    monkeypatch.setattr(cv.Convoso, '_get', lambda self, path, params: api(self, path, params))
    monkeypatch.setattr(cv, 'PAGE', api.page)
    return api


def drain(conn):
    turns = 0
    while engine.run(conn.pk, 'poll'):
        turns += 1
        assert turns < 2000
    return turns


def test_every_call_read_once_oldest_first_with_the_right_utc_time(conn, received, monkeypatch, clock, settings):
    settings.SYNC_BATCH_SIZE = 4
    calls = [call(n, DAY + timedelta(minutes=7 * n)) for n in range(1, 15)]
    use(monkeypatch, FakeConvoso(calls))
    clock(DAY + timedelta(days=1))
    drain(conn)
    assert [r for r, _, _ in received] == [str(9000 + n) for n in range(1, 15)]
    assert received[0][1] == DAY + timedelta(minutes=7)  # Los Angeles time turned back into UTC
    assert all(len(t) == 3 for _, _, t in received)  # number, number dialed and caller ID, as phone codes
    assert Fingerprint.objects.filter(client=conn.client).count() == 14


def test_many_calls_in_the_same_second(conn, received, monkeypatch, clock, settings):
    settings.SYNC_BATCH_SIZE = 2
    same = DAY + timedelta(hours=3)
    use(monkeypatch, FakeConvoso([call(n, same) for n in range(1, 8)]))
    clock(DAY + timedelta(hours=5))
    drain(conn)
    ids = [r for r, _, _ in received]
    assert len(ids) == 7 and len(set(ids)) == 7


def test_quiet_hours_are_stepped_over_and_the_newest_minutes_wait(conn, received, monkeypatch, clock):
    now = DAY + timedelta(hours=9)
    use(monkeypatch, FakeConvoso([call(1, DAY + timedelta(hours=7)), call(2, now - timedelta(seconds=40))]))
    clock(now)
    drain(conn)
    assert [r for r, _, _ in received] == ['9001']


def test_convoso_refuses_then_recovers(conn, received, monkeypatch, clock):
    api = use(monkeypatch, FakeConvoso([call(1, DAY + timedelta(minutes=5))], fail=True))
    clock(DAY + timedelta(hours=2))
    assert engine.run(conn.pk, 'poll') is False
    assert SyncCursor.objects.get(connection=conn).last_error == 'ConvosoError'
    api.fail = False
    drain(conn)
    assert [r for r, _, _ in received] == ['9001']


def test_a_changed_result_code_is_read_again(conn, received, monkeypatch, clock):
    calls = [call(1, DAY + timedelta(minutes=5))]
    use(monkeypatch, FakeConvoso(calls))
    clock(DAY + timedelta(hours=2))
    drain(conn)
    calls[0] = {**calls[0], 'status': 'DNC'}  # the agent changed the result code afterwards
    while engine.run(conn.pk, 'full_sweep'):
        pass
    assert [r for r, _, _ in received] == ['9001', '9001']


class Reply:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_test_button(monkeypatch):
    assert testers.test_convoso({'key': 'tok', 'secret': 'Mars/Base'})[0] == Status.FAILED  # wrong time zone
    monkeypatch.setattr(testers.urllib.request, 'urlopen', lambda req, timeout: Reply({'success': False, 'code': 401}))
    assert testers.test_convoso({'key': 'bad', 'secret': 'America/New_York'})[0] == Status.FAILED
    monkeypatch.setattr(testers.urllib.request, 'urlopen', lambda req, timeout: Reply({'success': True, 'data': {'results': []}}))
    status, message = testers.test_convoso({'key': 'tok', 'secret': 'America/New_York'})
    assert status == Status.CONNECTED and 'America/New_York' in message
