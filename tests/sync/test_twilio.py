"""Twilio adapter against a pretend Twilio API that behaves like the docs: newest first, paged, filtered by sent date."""
import json
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime

import pytest

from apps.connections.models import Connection, Status
from apps.ledger.models import Fingerprint
from apps.sync import engine, handoff
from apps.sync.connector import BadSignature
from apps.sync.connectors import twilio as tw

pytestmark = pytest.mark.django_db
TOKEN = 'f3a1b2c3d4e5f60718293a4b5c6d7e8f'
DAY = datetime(2026, 10, 1, tzinfo=UTC)


def msg(n: int, at: datetime, body='Hi, your solar quote is ready') -> dict:
    return {'sid': f'SM{n:032d}', 'date_sent': format_datetime(at), 'date_created': format_datetime(at), 'to': f'+1916555{n:04d}',
            'from': '+14805550000', 'body': body, 'status': 'delivered', 'direction': 'outbound-api'}


def call(n: int, at: datetime, status='completed') -> dict:
    return {'sid': f'CA{n:032d}', 'start_time': format_datetime(at), 'date_created': format_datetime(at), 'to': f'+1602555{n:04d}',
            'from': '+14805550000', 'status': status, 'direction': 'outbound-api', 'duration': '42'}


class FakeTwilioAPI:
    """Answers GET Messages.json / Calls.json like Twilio: filtered by DateSent / StartTime, newest first, paged."""
    def __init__(self, messages, calls=(), page_size=4):
        self.rows = {'Messages': (list(messages), tw.TEXTS), 'Calls': (list(calls), tw.CALLS)}
        self.page_size, self.requests = page_size, 0
        self.messages = self.rows['Messages'][0]

    def __call__(self, adapter, path_or_url, params=None):
        self.requests += 1
        path = urllib.parse.urlparse(path_or_url).path
        resource = 'Calls' if path.endswith('Calls.json') else 'Messages'
        rows, stream = self.rows[resource]
        if params is None:  # a next_page_uri
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(path_or_url).query))
        page = int(params.get('Page', 0))
        lo = datetime.fromisoformat(params[f'{stream.time_filter}>'].replace('Z', '+00:00'))
        hi = datetime.fromisoformat(params[f'{stream.time_filter}<'].replace('Z', '+00:00'))
        hits = sorted((r for r in rows if lo <= tw.happened_at(r, stream) <= hi), key=lambda r: tw.happened_at(r, stream), reverse=True)
        chunk = hits[page * self.page_size:(page + 1) * self.page_size]
        more = (page + 1) * self.page_size < len(hits)
        nxt = f'/2010-04-01/Accounts/AC1/{resource}.json?' + urllib.parse.urlencode({**params, 'Page': page + 1}) if more else None
        return {stream.list_key: chunk, 'next_page_uri': nxt}


@pytest.fixture
def received(monkeypatch):
    got = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [lambda client, conn, record, tokens: got.append((record.source_record_id, tokens))])
    return got


@pytest.fixture
def conn(company):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider='twilio', status=Status.CONNECTED)
    c.set_credentials({'account': 'AC1', 'key': TOKEN})
    c.save()
    return c


def use_api(monkeypatch, messages, calls=(), **kw):
    api = FakeTwilioAPI(messages, calls, **kw)
    monkeypatch.setattr(tw.Twilio, '_get', lambda self, p, params=None: api(self, p, params))
    return api


def drain(conn, kind='poll'):
    turns = 0
    while engine.run(conn.pk, kind):
        turns += 1
        assert turns < 500
    return turns


def test_reads_every_message_oldest_first_across_pages(conn, received, monkeypatch, settings):
    settings.SYNC_BATCH_SIZE = 5
    use_api(monkeypatch, [msg(n, DAY + timedelta(minutes=n)) for n in range(1, 12)])
    monkeypatch.setattr(tw, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: DAY + timedelta(days=3))}))
    drain(conn)
    assert [r for r, _ in received] == [f'SM{n:032d}' for n in range(1, 12)]
    assert all(len(t) == 2 for _, t in received)  # to and from, as phone codes
    assert Fingerprint.objects.filter(client=conn.client).count() == 11


def test_many_messages_in_the_same_second_are_neither_skipped_nor_doubled(conn, received, monkeypatch, settings):
    settings.SYNC_BATCH_SIZE = 2
    same = DAY + timedelta(hours=5)
    use_api(monkeypatch, [msg(n, same) for n in range(1, 8)] + [msg(9, same + timedelta(seconds=1))])
    monkeypatch.setattr(tw, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: DAY + timedelta(days=2))}))
    drain(conn)
    ids = [r for r, _ in received]
    assert sorted(ids) == sorted({*ids}) and len(ids) == 8


def test_empty_days_are_stepped_over_and_the_newest_two_minutes_wait(conn, received, monkeypatch):
    now = DAY + timedelta(days=4, hours=10)
    use_api(monkeypatch, [msg(1, DAY + timedelta(days=3, hours=1)), msg(2, now - timedelta(seconds=30))])
    monkeypatch.setattr(tw, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: now)}))
    drain(conn)
    assert [r for r, _ in received] == [f'SM{1:032d}']  # the 30-second-old one is read next run
    marks = json.loads(conn.sync.cursor)
    assert marks['texts'].startswith((now - tw.LAG).isoformat()[:16]) and marks['calls'].startswith((now - tw.LAG).isoformat()[:16])


def test_calls_and_texts_both_read_each_with_its_own_bookmark(conn, received, monkeypatch, settings):
    settings.SYNC_BATCH_SIZE = 4
    use_api(monkeypatch, [msg(n, DAY + timedelta(minutes=n)) for n in range(1, 10)],
            [call(n, DAY + timedelta(minutes=n, seconds=30)) for n in range(1, 6)])
    monkeypatch.setattr(tw, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: DAY + timedelta(days=2))}))
    engine.run(conn.pk, 'poll')
    first = [r for r, _ in received]
    assert sum(r.startswith('SM') for r in first) == 9 and sum(r.startswith('CA') for r in first) == 5  # each reads its whole hour
    drain(conn)
    ids = [r for r, _ in received]
    assert sorted(i for i in ids if i.startswith('CA')) == [f'CA{n:032d}' for n in range(1, 6)]
    assert sorted(i for i in ids if i.startswith('SM')) == [f'SM{n:032d}' for n in range(1, 10)]
    kinds = set(Fingerprint.objects.filter(client=conn.client).values_list('content_kind', flat=True))
    assert kinds == {'text', 'call'}


def test_a_status_change_is_read_again_and_nothing_else(conn, received, monkeypatch):
    api = use_api(monkeypatch, [msg(1, DAY + timedelta(hours=1))])
    messages = api.messages  # the pretend Twilio's own list
    monkeypatch.setattr(tw, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: DAY + timedelta(days=2))}))
    drain(conn)
    messages[0] = {**messages[0], 'status': 'undelivered'}
    drain(conn, 'full_sweep')
    assert len(received) == 2  # first as delivered, then again when its status changed


# Signature made by Twilio's official library (twilio.request_validator) for these exact values.
SIGNED_URL = 'https://app.complyiv.com/hooks/12'
SIGNED_FIELDS = {'MessageSid': 'SM1234', 'From': '+14805551234', 'To': '+19165550000', 'Body': 'STOP please', 'SmsStatus': 'received'}
OFFICIAL_SIGNATURE = 'Caa35VqfKRcYsSTzp4FDsOuXqzQ='


def test_signature_matches_twilios_official_library(conn):
    adapter = tw.Twilio(conn)
    body = urllib.parse.urlencode(SIGNED_FIELDS).encode()
    records = adapter.parse_event(body, {'_url': SIGNED_URL, 'X-Twilio-Signature': OFFICIAL_SIGNATURE})
    assert records[0].source_record_id == 'SM1234' and records[0].raw == body and len(records[0].phones) == 2
    with pytest.raises(BadSignature):
        adapter.parse_event(body, {'_url': SIGNED_URL, 'X-Twilio-Signature': 'x' + OFFICIAL_SIGNATURE[1:]})
    with pytest.raises(BadSignature):
        adapter.parse_event(body.replace(b'STOP', b'OKAY'), {'_url': SIGNED_URL, 'X-Twilio-Signature': OFFICIAL_SIGNATURE})
