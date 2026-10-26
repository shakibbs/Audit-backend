"""Super test 2026-10-23, group 1: reading from the tools.
- refused access → the connection says so and the client gets an alert; "slow down" → CiV waits as long as asked;
- the hourly catch-up reads the last hours again (late calls, changed statuses), never doubling;
- Five9's weekly check runs one report per day; Vicidial is encrypted and its address checked;
- HubSpot reads one window at a time and searches a paged window again."""
import io
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.alerts.raise_ import gather
from apps.connections.models import Connection, Status
from apps.sync import engine, handoff, tasks
from apps.sync.connector import CONNECTORS, AccessRemoved, Page, SlowDown, raise_for_status
from apps.sync.connectors import five9 as f9
from apps.sync.connectors import hubspot as hs
from apps.sync.connectors import vicidial as vd
from apps.sync.models import SyncCursor
from tests.sync.fake_tool import FakeTool, message
from tests.sync.test_five9 import FakeFive9, call as f9call
from tests.sync.test_five9 import conn as five9_conn  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


class Tool(FakeTool):
    mode = 'poll'
    problem: Exception | None = None
    late: list = []

    def changes_since(self, cursor, limit):
        if Tool.problem:
            raise Tool.problem
        return super().changes_since(cursor, limit)

    def recent(self, since):
        return [self._record(m) for m in Tool.late]


@pytest.fixture
def got(monkeypatch, settings):
    FakeTool.messages, FakeTool.down, Tool.problem, Tool.late = [message(n) for n in range(1, 4)], False, None, []
    monkeypatch.setitem(CONNECTORS, 'twilio', Tool)
    settings.SYNC_BATCH_SIZE = 10
    received = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, conn, record, tokens: received.append(record.source_record_id)])
    return received


def test_refused_access_marks_the_connection_and_alerts_the_client(company, got):
    conn = Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    Tool.problem = AccessRemoved('HTTP 401')
    assert engine.run(conn.pk, 'poll') is False
    conn.refresh_from_db()
    assert conn.status == Status.FAILED and conn.last_message.startswith('Access removed')
    assert any(a['kind'] == 'Source disconnected' for a in gather(company, timezone.now()).values())


def test_slow_down_is_respected(company, got, monkeypatch):
    conn = Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    Tool.problem = SlowDown(120)
    engine.run(conn.pk, 'poll')
    cursor = SyncCursor.objects.get(connection=conn)
    assert cursor.wait_until > timezone.now() + timedelta(seconds=100)
    Tool.problem = None
    assert engine.run(conn.pk, 'poll') is False and got == []  # not asked again before the time it gave
    queued = []
    monkeypatch.setattr(tasks.sync_connection, 'delay', lambda *a: queued.append(a))
    tasks.poll_due()
    assert queued == []


def test_http_answers_become_the_engines_own_errors():
    def error(code, retry=None):
        return urllib.error.HTTPError('https://x', code, 'x', {'Retry-After': retry} if retry else {}, io.BytesIO(b''))
    with pytest.raises(SlowDown) as slow:
        raise_for_status(error(429, '30'))
    assert slow.value.seconds == 30
    with pytest.raises(AccessRemoved):
        raise_for_status(error(403))


def test_the_hourly_catch_up_finds_late_records_once(company, got):
    conn = Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    while engine.run(conn.pk, 'catchup'):
        pass
    Tool.late = [message(1), message(9, 'a long call written when it ended')]  # one already read, one new
    engine.run(conn.pk, 'catchup')
    assert got.count('SM0001') == 1 and got.count('SM0009') == 1


def test_five9_weekly_check_runs_one_report_per_day(five9_conn, monkeypatch):  # noqa: F811
    api = FakeFive9([f9call(1, datetime(2026, 10, 1, 14, tzinfo=UTC))])
    monkeypatch.setattr(f9.Five9, 'soap', lambda self, method, inner: api(self, method, inner))
    tool = f9.Five9(five9_conn)
    page = tool.list_all('', 100)
    start, end = api.ran[0]
    assert (end - start) >= timedelta(hours=23) and page.next_cursor.startswith('2026-10-02') and len(page.records) == 1


def test_vicidial_is_always_encrypted_and_never_reaches_a_local_server(monkeypatch):
    seen = {}

    class Done(Exception):
        pass

    def connect(**kwargs):
        seen.update(kwargs)
        raise Done
    monkeypatch.setattr(vd.socket, 'getaddrinfo', lambda host, port, proto=0: [(0, 0, 0, '', ('93.184.216.34', port))])
    monkeypatch.setattr(vd.pymysql, 'connect', connect)

    class Probe:
        def get_credentials(self):
            return {'account': 'db.cc.example:3306/asterisk', 'key': 'u', 'secret': 'p'}
    with pytest.raises(Done):
        vd.Vicidial(Probe()).query('SELECT 1', ())
    assert seen['ssl_verify_cert'] is True and seen['ssl_verify_identity'] is True
    monkeypatch.setattr(vd.socket, 'getaddrinfo', lambda host, port, proto=0: [(0, 0, 0, '', ('127.0.0.1', port))])
    with pytest.raises(vd.BadAddress):
        vd.server('db.cc.example')


def test_hubspot_halves_a_crowded_window_and_searches_a_paged_one_again(monkeypatch):
    bodies = []

    def call(self, url, body=None):
        if '/properties/' in url:
            return {'results': []}
        bodies.append(body)
        lo, hi = (int(f['value']) for f in body['filterGroups'][0]['filters'])
        if hi - lo > 6 * 3600 * 1000:
            return {'total': 20_000, 'results': []}  # too many for one search
        first = 'after' not in body
        return {'total': 150, 'results': [{'id': '1' if first else '2', 'properties': {'hs_lastmodifieddate': '2026-10-01T00:00:01Z'}}],
                'paging': {'next': {'after': '100'}} if first else {}}
    monkeypatch.setattr(hs.HubSpot, 'call', call)
    tool = hs.HubSpot.__new__(hs.HubSpot)
    start = hs.ms(datetime(2026, 10, 1, tzinfo=UTC))
    rows, end = tool.window(hs.OBJECTS[0], start, start + 10 * 24 * 3600 * 1000)
    assert end - start <= 6 * 3600 * 1000  # halved until it fits one search
    assert sum(1 for b in bodies if 'after' not in b and int(b['filterGroups'][0]['filters'][1]['value']) == end) == 2  # searched again
    assert {r['id'] for r in rows} == {'1', '2'}
