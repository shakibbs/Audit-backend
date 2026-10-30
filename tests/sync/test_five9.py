"""Five9 adapter against a pretend Five9 SOAP service: runReport → isReportRunning → getReportResultCsv, with real
SOAP envelopes and faults, report times in the account's time zone."""
import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.connections import testers
from apps.connections.models import Connection, Status
from apps.sync import engine, handoff, tasks
from apps.sync.connectors import five9 as f9
from apps.sync.models import SyncCursor

pytestmark = pytest.mark.django_db
NY = ZoneInfo('America/New_York')
DAY = datetime(2026, 10, 1, tzinfo=UTC)
HEADER = ['CALL ID', 'TIMESTAMP', 'CAMPAIGN', 'CALL TYPE', 'DISPOSITION', 'ANI', 'DNIS', 'LENGTH']


def envelope(inner: str) -> bytes:
    return ('<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"><env:Body>'
            f'<ns2:r xmlns:ns2="{f9.NS}">{inner}</ns2:r></env:Body></env:Envelope>').encode()


FAULT = (b'<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"><env:Body><env:Fault>'
         b'<faultcode>env:Server</faultcode><faultstring>Access denied</faultstring></env:Fault></env:Body></env:Envelope>')


def call(n: int, at: datetime, disposition='Not Interested') -> dict:
    return {'CALL ID': f'3000{n:05d}', 'TIMESTAMP': at.astimezone(NY).strftime('%a, %d %b %Y %H:%M:%S'), 'CAMPAIGN': 'Roof',
            'CALL TYPE': 'Outbound', 'DISPOSITION': disposition, 'ANI': '4805550000', 'DNIS': f'916555{n:04d}', 'LENGTH': '00:00:42'}


class FakeFive9:
    """Parses CiV's SOAP request and answers like Five9; a report is 'running' for one isReportRunning call."""
    def __init__(self, calls, deny=False):
        self.calls, self.deny, self.reports, self.ran = calls, deny, {}, []

    def __call__(self, adapter, method, inner):
        if self.deny:
            return f9.Five9.answer(FAULT)
        if method == 'runReport':
            start, end = (datetime.strptime(re.search(f'<{t}>(.*?)</{t}>', inner).group(1), '%Y-%m-%dT%H:%M:%S.000%z') for t in ('start', 'end'))
            rows = [c for c in self.calls if start <= datetime.strptime(c['TIMESTAMP'], '%a, %d %b %Y %H:%M:%S').replace(tzinfo=NY) <= end]
            report_id = f'rep{len(self.reports)}'
            self.reports[report_id] = [rows, 1]
            self.ran.append((start, end))
            return f9.Five9.answer(envelope(f'<return>{report_id}</return>'))
        report_id = re.search('<identifier>(.*?)</identifier>', inner).group(1)
        if method == 'isReportRunning':
            self.reports[report_id][1] -= 1
            return f9.Five9.answer(envelope(f'<return>{"true" if self.reports[report_id][1] >= 0 else "false"}</return>'))
        out = io.StringIO()
        writer = csv.DictWriter(out, HEADER)
        writer.writeheader()
        writer.writerows(self.reports[report_id][0])
        return f9.Five9.answer(envelope(f'<return>{out.getvalue().replace("&", "&amp;").replace("<", "&lt;")}</return>'))


@pytest.fixture
def received(monkeypatch):
    got = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, conn, record, tokens: got.append((record.source_record_id, record.changed_at, tokens))])
    return got


@pytest.fixture
def conn(company):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider='five9', status=Status.CONNECTED)
    c.set_credentials({'account': 'civ_reports', 'key': 'pw', 'secret': 'America/New_York'})
    c.save()
    return c


@pytest.fixture
def clock(monkeypatch):
    def at(moment):
        monkeypatch.setattr(f9, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: moment)}))
    return at


def use(monkeypatch, api):
    monkeypatch.setattr(f9.Five9, 'soap', lambda self, method, inner: api(self, method, inner))
    return api


def drain(conn):
    turns = 0
    while engine.run(conn.pk, 'poll'):
        turns += 1
        assert turns < 500
    return turns


def test_reads_every_call_once_through_the_report_with_utc_times(conn, received, monkeypatch, clock):
    api = use(monkeypatch, FakeFive9([call(n, DAY + timedelta(minutes=13 * n)) for n in range(1, 12)]))
    clock(DAY + timedelta(hours=4))
    drain(conn)
    assert [r for r, _, _ in received] == [f'3000{n:05d}' for n in range(1, 12)]
    assert received[0][1] == DAY + timedelta(minutes=13)  # New York report time back to UTC
    assert all(len(t) == 2 for _, _, t in received)  # DNIS and ANI as phone codes
    assert len(api.ran) == 4  # one report per hour window: 00–01, 01–02, 02–03, 03–03:55


def test_a_call_at_the_window_edge_is_not_lost_or_doubled(conn, received, monkeypatch, clock):
    use(monkeypatch, FakeFive9([call(1, DAY + timedelta(hours=1) - timedelta(seconds=1)), call(2, DAY + timedelta(hours=1))]))
    clock(DAY + timedelta(hours=3))
    drain(conn)
    assert sorted(r for r, _, _ in received) == ['300000001', '300000002']


def test_five9_refuses_then_recovers(conn, received, monkeypatch, clock):
    api = use(monkeypatch, FakeFive9([call(1, DAY + timedelta(minutes=5))], deny=True))
    clock(DAY + timedelta(hours=2))
    assert engine.run(conn.pk, 'poll') is False
    assert SyncCursor.objects.get(connection=conn).last_error == 'Five9Error'
    api.deny = False
    drain(conn)
    assert [r for r, _, _ in received] == ['300000001']


def test_polled_no_more_than_every_10_minutes(conn, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.sync_connection, 'delay', lambda *a: queued.append(a))
    tasks.poll_due()
    assert queued == [(conn.pk, 'poll')]  # never read yet
    SyncCursor.objects.filter(connection=conn).update(last_heartbeat_at=timezone.now() - timedelta(minutes=4))
    queued.clear()
    tasks.poll_due()
    assert queued == []
    SyncCursor.objects.filter(connection=conn).update(last_heartbeat_at=timezone.now() - timedelta(minutes=11))
    tasks.poll_due()
    assert queued == [(conn.pk, 'poll')]


def test_columns_are_matched_loosely():
    row = {'Call Id ': '42', 'Date': '10/01/2026', 'Time': '14:05:00', 'dnis': '9165550001', 'ANI': ''}
    adapter = f9.Five9.__new__(f9.Five9)
    adapter.tz = NY
    record = adapter.record(row)
    assert record.source_record_id == '42' and record.phones == ['9165550001']
    assert record.changed_at == datetime(2026, 10, 1, 18, 5, tzinfo=UTC)


def test_the_test_button(monkeypatch):
    assert testers.test_five9({'account': 'u', 'key': 'p', 'secret': 'Nowhere/Here'})[0] == Status.FAILED
    use(monkeypatch, FakeFive9([], deny=True))
    status, message = testers.test_five9({'account': 'u', 'key': 'p', 'secret': 'America/New_York'})
    assert status == Status.FAILED and 'Access denied' in message
    use(monkeypatch, FakeFive9([]))
    assert testers.test_five9({'account': 'u', 'key': 'p', 'secret': 'America/New_York'})[0] == Status.CONNECTED


def test_the_real_soap_request_and_answers(conn, monkeypatch):
    import base64
    import urllib.error
    import xml.etree.ElementTree as ET
    sent = {}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout):
        sent['url'], sent['headers'], sent['body'] = request.full_url, dict(request.header_items()), request.data
        if b'isReportRunning' in request.data:  # Five9 sends faults with HTTP 500
            raise urllib.error.HTTPError(request.full_url, 500, 'Server Error', {}, io.BytesIO(FAULT))
        return Reply(envelope('<return>rep7</return>'))

    monkeypatch.setattr(f9.urllib.request, 'urlopen', fake_urlopen)
    adapter = f9.Five9(conn)
    assert adapter.soap('runReport', '<folderName>Call Log Reports</folderName>').text == 'rep7'
    assert sent['url'] == f9.API and sent['headers']['Authorization'] == 'Basic ' + base64.b64encode(b'civ_reports:pw').decode()
    body = ET.fromstring(sent['body'])
    assert body.find(f'.//{{{f9.NS}}}runReport/folderName').text == 'Call Log Reports'  # a well-formed SOAP envelope
    with pytest.raises(f9.Five9Error, match='Access denied'):
        adapter.soap('isReportRunning', '<identifier>rep7</identifier>')


def test_a_call_without_a_call_id_keeps_its_id_when_five9_changes_it():
    """Owner, 2026-10-31: no CALL ID column — Ringing → Answered and the length filled in is the same call, not a new one."""
    from apps.sync.connectors.five9 import steady_id
    before = {k: v for k, v in call(1, DAY, disposition='Ringing').items() if k != 'CALL ID'}
    after = {**before, 'DISPOSITION': 'Answered', 'LENGTH': '00:03:10'}
    other = {**before, 'DNIS': '9165559999'}
    assert steady_id(before) == steady_id(after) != steady_id(other)
    assert steady_id(before).startswith('nocallid-')
