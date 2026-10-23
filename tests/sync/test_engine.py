"""Sync engine with a pretend tool: nothing kept, bookmark-safe, gaps found, fair turns, health, tenancy."""
import json
from datetime import timedelta

import pytest
from django.db import connection as db
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.ledger.models import Fingerprint, PurgeLog
from django.test import RequestFactory

from apps.sync import engine, handoff, health, tasks
from apps.sync.views import hook
from apps.sync.connector import CONNECTORS
from apps.sync.models import SyncCursor, SyncGap
from apps.tenancy.scope import _scope
from tests.sync.fake_tool import FakeTool, message, sign

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fake_tool(settings, monkeypatch):
    FakeTool.messages, FakeTool.down = [message(n) for n in range(1, 8)], False
    monkeypatch.setitem(CONNECTORS, 'twilio', FakeTool)  # the pretend tool stands in for a real provider code
    settings.SYNC_BATCH_SIZE = 3
    received = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, conn, record, tokens: received.append((client.pk, record.source_record_id, tokens))])
    return received


def connect(client):
    return Connection.objects.create(client=client, provider='twilio', status=Status.CONNECTED)


def drain(conn, kind='catchup'):
    while engine.run(conn.pk, kind):
        pass


def test_every_record_is_fingerprinted_coded_handed_on_and_nothing_kept(company, fake_tool):
    conn = connect(company)
    drain(conn)
    assert len(fake_tool) == 7 and Fingerprint.objects.filter(client=company).count() == 7
    assert all(len(tokens) == 1 and '9165550001' not in tokens[0] for _, _, tokens in fake_tool)
    with db.cursor() as c:  # store nothing: no phone number or message text anywhere in the database
        for table in ['fingerprint', 'sync_cursor', 'sync_gap', 'purge_log', 'merkle_anchor']:
            c.execute(f'SELECT * FROM {table}')
            dump = repr(c.fetchall())
            assert '9165550001' not in dump and 'solar quote' not in dump, table


def test_small_batches_and_the_bookmark(company, fake_tool):
    conn = connect(company)
    assert engine.run(conn.pk, 'catchup') is True  # 3 of 7: more waiting
    assert SyncCursor.objects.get(connection=conn).cursor == '3'
    drain(conn)
    cursor = SyncCursor.objects.get(connection=conn)
    assert cursor.cursor == '7' and not cursor.backlog and cursor.records_delivered == 7 and cursor.last_catchup_at


def test_a_failure_halfway_skips_and_doubles_nothing(company, fake_tool, monkeypatch):
    conn = connect(company)
    engine.run(conn.pk, 'catchup')
    calls = {'n': 0}

    def break_on_second(client, c, record, tokens):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('crash')
        fake_tool.append((client.pk, record.source_record_id, tokens))
    monkeypatch.setattr(handoff, 'RECEIVERS', [break_on_second])
    assert engine.run(conn.pk, 'catchup') is False
    cursor = SyncCursor.objects.get(connection=conn)
    assert cursor.cursor == '3' and cursor.failures_in_row == 1 and cursor.last_error == 'RuntimeError'
    assert Fingerprint.objects.filter(client=company).count() == 3  # the failed batch left nothing
    assert PurgeLog.objects.get().rows_removed == 2
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, c, record, tokens: fake_tool.append((client.pk, record.source_record_id, tokens))])
    drain(conn)
    ids = [r for _, r, _ in fake_tool]
    assert sorted(set(ids)) == [f'SM{n:04d}' for n in range(1, 8)]
    assert Fingerprint.objects.filter(client=company).count() == 7


def test_tool_down_is_retried_next_turn(company):
    conn = connect(company)
    FakeTool.down = True
    assert engine.run(conn.pk, 'catchup') is False
    assert SyncCursor.objects.get(connection=conn).last_error == 'ConnectionError'
    FakeTool.down = False
    drain(conn)
    assert SyncCursor.objects.get(connection=conn).failures_in_row == 0


def ring(conn_id, body, signature):
    """The door's code, called directly: the public /hooks/ address is closed (owner decision)."""
    request = RequestFactory().post(f'/hooks/{conn_id}', body, content_type='application/json', HTTP_X_FAKE_SIGNATURE=signature)
    return hook(request, conn_id)


def test_the_public_door_is_closed(client, company):
    conn = connect(company)
    body = json.dumps(message(1)).encode()
    assert client.post(f'/hooks/{conn.pk}', body, content_type='application/json', HTTP_X_FAKE_SIGNATURE=sign(body)).status_code == 404
    assert Fingerprint.objects.count() == 0


def test_live_notice_then_catchup_finds_only_what_was_missed(company, fake_tool):
    conn = connect(company)
    for n in (1, 2, 3, 4, 5, 6):  # the live feed delivered all but number 7
        body = json.dumps(message(n), sort_keys=True).encode()
        assert ring(conn.pk, body, sign(body)).status_code == 204
    drain(conn)
    assert len(fake_tool) == 7  # 6 live + 1 missed, nothing twice
    gap = SyncGap.objects.get()
    assert gap.source_record_id == 'SM0007' and gap.found_by == 'catchup'


def test_unsigned_live_notice_is_refused(company):
    conn = connect(company)
    body = json.dumps(message(1)).encode()
    assert ring(conn.pk, body, 'wrong').status_code == 403
    assert ring(99999, body, sign(body)).status_code == 404
    assert Fingerprint.objects.count() == 0


def test_a_changed_record_is_processed_again_an_unchanged_one_is_not(company, fake_tool):
    conn = connect(company)
    drain(conn)
    FakeTool.messages[0] = message(1, body='Updated text')
    SyncCursor.objects.filter(connection=conn).update(cursor='')
    drain(conn)
    assert [r for _, r, _ in fake_tool].count('SM0001') == 2 and len(fake_tool) == 8


def test_clients_take_turns(company, other_company, monkeypatch, settings):
    order = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, c, record, tokens: order.append(client.pk)])
    settings.CELERY_TASK_ALWAYS_EAGER = False  # look at the queue instead of running it
    queued = []
    monkeypatch.setattr(tasks.sync_connection, 'delay', lambda *args: queued.append(args))
    a, b = connect(company), connect(other_company)
    tasks.catchup_all()
    assert sorted(queued) == sorted([(a.pk, 'catchup'), (b.pk, 'catchup')])
    while queued:  # run the queue in order: each run does one small batch and goes to the back
        conn_id, kind = queued.pop(0)
        tasks.sync_connection(conn_id, kind)
    firsts = order[:6]
    assert firsts.count(company.pk) == 3 and firsts.count(other_company.pk) == 3  # both got a turn before either finished


def test_paused_clients_and_tools_without_an_adapter_are_not_read(company):
    conn = connect(company)
    company.status = company.Status.PAUSED
    company.save()
    assert engine.run(conn.pk, 'catchup') is False and Fingerprint.objects.count() == 0
    other = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    assert engine.run(other.pk, 'catchup') is False


def test_health_live_catching_up_stale_and_back(company):
    conn = connect(company)
    assert health.state(None) == 'never'
    engine.run(conn.pk, 'catchup')
    assert health.state(SyncCursor.objects.get(connection=conn)) == 'catching_up'
    drain(conn)
    assert health.state(SyncCursor.objects.get(connection=conn)) == 'live'
    SyncCursor.objects.filter(connection=conn).update(last_heartbeat_at=timezone.now() - timedelta(hours=3))
    assert [c.pk for c in health.check_all()] == [conn.pk]
    conn.refresh_from_db()
    assert conn.status == Status.STALE
    drain(conn, 'poll')
    health.check_all()
    conn.refresh_from_db()
    assert conn.status == Status.CONNECTED


def test_full_sweep_reads_everything_and_keeps_the_bookmark(company, fake_tool):
    conn = connect(company)
    drain(conn)
    drain(conn, 'full_sweep')
    cursor = SyncCursor.objects.get(connection=conn)
    assert cursor.cursor == '7' and cursor.last_full_sweep_at and len(fake_tool) == 7  # nothing new, nothing twice


def test_sync_data_is_locked_per_client(company, other_company):
    drain(connect(company))
    drain(connect(other_company))
    with _scope('client', str(company.pk)):
        assert set(SyncCursor.objects.values_list('client_id', flat=True)) == {company.pk}


def test_full_sweep_reports_every_record_it_read_and_when_it_finished(company, monkeypatch):
    seen, done = [], []
    monkeypatch.setattr(handoff, 'SEEN', [lambda client, conn, ids: seen.extend(ids)])
    monkeypatch.setattr(handoff, 'SWEEP_DONE', [lambda conn, started: done.append(started)])
    conn = connect(company)
    drain(conn)
    drain(conn, 'full_sweep')  # unchanged records are reported as seen too: only missing ones count as deleted
    cursor = SyncCursor.objects.get(connection=conn)
    assert sorted(seen) == [f'SM{n:04d}' for n in range(1, 8)] and done == [cursor.sweep_started_at] and done[0] is not None
