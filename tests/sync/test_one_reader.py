"""Super test 2026-10-23: one broken connection never stops the others; one reader per connection at a time; the
Time zone or region box only takes what fits the tool."""
import threading
from datetime import timedelta

import pytest
from django.db import connection as db
from django.utils import timezone

from apps.connections.forms import ConnectionForm
from apps.connections.models import Connection, Status
from apps.sync import engine, tasks
from apps.sync.connector import CONNECTORS
from apps.sync.models import SyncCursor
from tests.sync.fake_tool import FakeTool, message
from tests.sync.test_engine import connect

pytestmark = pytest.mark.django_db


class PolledTool(FakeTool):
    mode = 'poll'  # asked every 2 minutes (most real tools)


class BrokenTool(FakeTool):
    def __init__(self, connection):
        raise ValueError('Unknown report time zone "mypurecloud.com"')


@pytest.fixture(autouse=True)
def tools(settings, monkeypatch):
    FakeTool.messages, FakeTool.down = [message(n) for n in range(1, 8)], False
    monkeypatch.setitem(CONNECTORS, 'twilio', PolledTool)
    monkeypatch.setitem(CONNECTORS, 'five9', BrokenTool)
    settings.SYNC_BATCH_SIZE = 3


def queue(monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.sync_connection, 'delay', lambda *args: queued.append(args))
    return queued


def test_a_broken_connection_is_marked_failed_and_the_others_are_still_read(company, other_company, monkeypatch):
    bad = Connection.objects.create(client=company, provider='five9', status=Status.CONNECTED, setting='mypurecloud.com')
    good = connect(other_company)
    queued = queue(monkeypatch)
    tasks.poll_due()
    tasks.full_sweep_due()
    assert (good.pk, 'poll') in queued and (good.pk, 'full_sweep') in queued
    bad.refresh_from_db()
    assert bad.status == Status.FAILED and 'time zone' in bad.last_message
    assert all(conn_id != bad.pk for conn_id, _ in queued)


def test_a_connection_still_reading_its_backlog_is_not_polled_again(company, monkeypatch):
    conn = connect(company)
    assert engine.run(conn.pk, 'catchup') is True  # 3 of 7 read: a backlog chain is running
    queued = queue(monkeypatch)
    tasks.poll_due()
    assert queued == []
    SyncCursor.objects.filter(connection=conn).update(last_heartbeat_at=timezone.now() - timedelta(minutes=30))
    tasks.poll_due()  # a chain that stopped moving long ago is polled again, so nothing is stuck for ever
    assert queued == [(conn.pk, 'poll')]


def test_a_second_reader_on_the_same_connection_skips_its_turn(company):
    conn = connect(company)
    with engine.only_reader(conn.pk) as mine:
        assert mine
        result = {}

        def other_worker():
            from django.db import connections
            try:
                with engine.only_reader(conn.pk) as theirs:
                    result['got'] = theirs
            finally:
                connections.close_all()
        t = threading.Thread(target=other_worker)
        t.start()
        t.join()
        assert result['got'] is False  # another worker could not read at the same time
    assert SyncCursor.objects.filter(connection=conn).count() <= 1 and db.is_usable()


def test_the_setting_box_takes_only_what_fits_the_tool(company):
    def form(provider, setting):
        return ConnectionForm(data={'client': company.pk, 'provider': provider, 'label': '', 'setting': setting})
    assert form('five9', 'America/Chicago').is_valid()
    assert 'setting' in form('five9', 'mypurecloud.com').errors  # a Genesys region for Five9
    assert 'setting' in form('genesys', 'America/Chicago').errors
    assert 'setting' in form('twilio', 'America/Chicago').errors  # Twilio needs none
    assert 'setting' in form('convoso', '').errors  # a dialer's time zone is required: no silent New York
    assert form('genesys', 'mypurecloud.com').is_valid()
