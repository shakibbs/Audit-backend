"""Vicidial adapter: CiV's real SQL runs against an in-memory database shaped like Vicidial's call log tables."""
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pymysql
import pytest

from apps.connections import testers
from apps.connections.models import Connection, Status
from apps.ledger.models import Fingerprint
from apps.sync import engine, handoff
from apps.sync.connectors import vicidial as vd

pytestmark = pytest.mark.django_db
DAY = datetime(2026, 10, 1, tzinfo=UTC)
COLUMNS = ('uniqueid TEXT, lead_id INT, list_id INT, campaign_id TEXT, call_date TEXT, start_epoch INT, end_epoch INT, '
           'length_in_sec INT, status TEXT, phone_code TEXT, phone_number TEXT, user TEXT, term_reason TEXT')


class FakeVicidialDB:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute(f'CREATE TABLE vicidial_log ({COLUMNS}, alt_dial TEXT)')
        self.db.execute(f'CREATE TABLE vicidial_closer_log (closecallid INTEGER, {COLUMNS})')
        self.sql = []

    def outbound(self, n, at, status='NI'):
        self.db.execute('INSERT INTO vicidial_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (f'{int(at.timestamp())}.{n:04d}', n, 1001, 'ROOF', at.strftime('%Y-%m-%d %H:%M:%S'), int(at.timestamp()),
                         int(at.timestamp()) + 42, 42, status, '1', f'916555{n:04d}', 'agent7', 'CALLER', 'MAIN'))

    def inbound(self, n, at):
        self.db.execute('INSERT INTO vicidial_closer_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (n, f'{int(at.timestamp())}.9{n:03d}', n, 1001, 'INBOUND', at.strftime('%Y-%m-%d %H:%M:%S'), int(at.timestamp()),
                         int(at.timestamp()) + 30, 30, 'SALE', '1', f'480555{n:04d}', 'agent7', 'AGENT'))

    def __call__(self, adapter, sql, params):
        assert sql.lstrip().upper().startswith('SELECT')  # only reads are ever sent
        self.sql.append(sql)
        return [dict(r) for r in self.db.execute(sql.replace('%s', '?'), params)]


@pytest.fixture
def db(monkeypatch):
    fake = FakeVicidialDB()
    monkeypatch.setattr(vd.Vicidial, 'query', lambda self, sql, params: fake(self, sql, params))
    return fake


@pytest.fixture
def received(monkeypatch):
    got = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, conn, record, tokens: got.append((record.source_record_id, record.changed_at, tokens))])
    return got


@pytest.fixture
def conn(company):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider='vicidial', status=Status.CONNECTED)
    c.set_credentials({'account': 'db.callcenter.example:3306/asterisk', 'key': 'civ_read', 'secret': 'pw'})
    c.save()
    return c


@pytest.fixture
def clock(monkeypatch):
    def at(moment):
        monkeypatch.setattr(vd, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: moment),
                                                                       'fromtimestamp': staticmethod(datetime.fromtimestamp)}))
    return at


def drain(conn):
    turns = 0
    while engine.run(conn.pk, 'poll'):
        turns += 1
        assert turns < 500


def test_outbound_and_inbound_read_once_each_oldest_first(conn, db, received, clock, settings):
    settings.SYNC_BATCH_SIZE = 4
    for n in range(1, 8):
        db.outbound(n, DAY + timedelta(minutes=5 * n))
    for n in range(1, 4):
        db.inbound(n, DAY + timedelta(minutes=11 * n))
    clock(DAY + timedelta(hours=2))
    drain(conn)
    ids = [r for r, _, _ in received]
    assert len(ids) == 10 and len(set(ids)) == 10
    assert {i.split(':')[0] for i in ids} == {'outbound', 'inbound'}
    assert received[0][1] in (DAY + timedelta(minutes=5), DAY + timedelta(minutes=11))  # start_epoch is universal time
    assert all(len(t) == 1 for _, _, t in received)
    assert Fingerprint.objects.filter(client=conn.client).count() == 10


def test_many_calls_in_the_same_second(conn, db, received, clock, settings):
    settings.SYNC_BATCH_SIZE = 2
    for n in range(1, 10):
        db.outbound(n, DAY + timedelta(minutes=3))
    clock(DAY + timedelta(hours=1))
    drain(conn)
    ids = [r for r, _, _ in received]
    assert len(ids) == 9 and len(set(ids)) == 9


def test_new_calls_later_and_the_newest_wait(conn, db, received, clock):
    db.outbound(1, DAY + timedelta(minutes=10))
    db.outbound(2, DAY + timedelta(minutes=59, seconds=30))
    clock(DAY + timedelta(hours=1))
    drain(conn)
    assert [r for r, _, _ in received] == [f'outbound:{int((DAY + timedelta(minutes=10)).timestamp())}.0001']
    clock(DAY + timedelta(hours=1, minutes=5))
    drain(conn)
    assert len(received) == 2


def test_only_select_and_only_needed_columns(conn, db, clock):
    db.outbound(1, DAY + timedelta(minutes=10))
    clock(DAY + timedelta(hours=1))
    drain(conn)
    assert db.sql and all('SELECT uniqueid, lead_id' in q or 'SELECT closecallid' in q for q in db.sql)


def test_server_address(monkeypatch):
    monkeypatch.setattr(vd.socket, 'getaddrinfo', lambda host, port, proto=0: [(0, 0, 0, '', ('93.184.216.34' if host == 'db.cc.example' else host, port))])
    assert vd.server('db.cc.example:3307/vici') == {'host': 'db.cc.example', 'port': 3307, 'database': 'vici'}
    # QA 2026-10-23: blank, private or local addresses and bad ports are refused before any connection
    for bad in ('', '10.0.0.5', '127.0.0.1:3306', 'db.cc.example:abc', 'db.cc.example:99999'):
        with pytest.raises(vd.BadAddress):
            vd.server(bad)


def test_the_test_button(monkeypatch, db):
    creds = {'account': 'db:3306/asterisk', 'key': 'civ_read', 'secret': 'pw'}
    assert testers.test_vicidial(creds)[0] == Status.CONNECTED

    def refuse(self, sql, params):
        raise pymysql.err.OperationalError(1045, 'Access denied')
    monkeypatch.setattr(vd.Vicidial, 'query', refuse)
    status, message = testers.test_vicidial(creds)
    assert status == Status.FAILED and 'user or password' in message

    def no_rights(self, sql, params):
        raise pymysql.err.ProgrammingError(1142, 'SELECT command denied')
    monkeypatch.setattr(vd.Vicidial, 'query', no_rights)
    assert 'give the user SELECT' in testers.test_vicidial(creds)[1]
