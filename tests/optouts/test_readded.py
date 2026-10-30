"""The STOP list and M34: opted-out numbers that come back in an uploaded list."""
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from django.db import connection as db

from apps.access_log.models import AccessEntry
from apps.connections.models import Connection, Status
from apps.contacts.normalize import codes_for
from apps.imports.batches import rebuild
from apps.imports.creations import creation_seen
from apps.imports.models import ImportBatch
from apps.optouts.detect import optout_seen, stop_word
from apps.optouts.models import OptOutEvent, ReaddedNumber
from apps.optouts.readded import check_batches
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connector import Record
from apps.sync.connectors import twilio as tw
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
JUNE, OCT = datetime(2026, 6, 3, 15, 0, tzinfo=UTC), datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
SARAH = '+19165550001'


def conn(client, provider):
    return Connection.objects.get_or_create(client=client, provider=provider, defaults={'status': Status.CONNECTED})[0]


def text_in(client, body, at=JUNE, sid='SM1', number=SARAH):
    c = conn(client, 'twilio')
    c.set_credentials({'account': 'AC' + '1' * 32, 'key': 'k'})
    c.save()
    row = {'sid': sid, 'date_sent': format_datetime(at), 'date_created': format_datetime(at), 'from': number, 'to': '+14805550000',
           'body': body, 'status': 'received', 'direction': 'inbound'}
    optout_seen(client, c, tw.Twilio(c).record(row, tw.TEXTS), [])


def upload(client, at, tokens_for, user='005EMP42', count=25):
    c = conn(client, 'salesforce')
    for n in range(count):
        raw = json.dumps({'Id': f'00Q{at:%m}{n:08d}', 'CreatedDate': (at + timedelta(seconds=n)).strftime('%Y-%m-%dT%H:%M:%S.000+0000'),
                          'CreatedById': user}).encode()
        creation_seen(client, c, Record(f'leads:00Q{at:%m}{n:08d}', raw, 'lead', at + timedelta(seconds=n)), tokens_for(n))
    rebuild(client)


@pytest.mark.parametrize('body, word', [('STOP', 'STOP'), ('stop', 'STOP'), (' Stop! ', 'STOP'), ('unsubscribe', 'UNSUBSCRIBE'),
                                        ('opt out', 'OPT OUT'), ('Stop by tomorrow?', ''), ('please stop calling', ''), ('', '')])
def test_only_a_whole_message_stop_word_counts(db, body, word):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    assert stop_word(body) == word


def test_a_stop_text_goes_on_the_list_without_the_text(company):
    text_in(company, 'STOP')
    text_in(company, 'Stop by tomorrow?', sid='SM2')
    event = OptOutEvent.objects.get()
    assert (event.method, event.keyword, event.channel, event.at) == ('keyword', 'STOP', 'text', JUNE)
    assert event.phone_token == codes_for(company).token(SARAH)
    with db.cursor() as cur:
        cur.execute('SELECT * FROM opt_out_event')
        dump = repr(cur.fetchall())
    assert '9165550001' not in dump and 'tomorrow' not in dump


def test_crm_do_not_call_box_goes_on_the_list(company):
    c = conn(company, 'salesforce')
    raw = json.dumps({'Id': '00Q1', 'DoNotCall': True}).encode()
    optout_seen(company, c, Record('leads:00Q1', raw, 'lead', JUNE), ['tok-a'])
    optout_seen(company, c, Record('leads:00Q2', json.dumps({'Id': '00Q2', 'DoNotCall': False}).encode(), 'lead', JUNE), ['tok-b'])
    assert list(OptOutEvent.objects.values_list('phone_token', 'method')) == [('tok-a', 'crm_flag')]


def test_an_upload_that_brings_back_an_opted_out_number(company):
    text_in(company, 'STOP')
    sarah = codes_for(company).token(SARAH)
    upload(company, OCT, lambda n: [sarah] if n == 7 else [f'other{n}'])
    assert check_batches(company) == 1
    batch = ImportBatch.objects.get(kind='bulk_import')
    assert batch.opted_out_readded == 1
    found = ReaddedNumber.objects.get()
    assert (found.phone_token, found.opted_out_at) == (sarah, JUNE)
    assert AccessEntry.objects.filter(action='optout_readded').count() == 1
    rebuild(company)
    assert check_batches(company) == 0  # found once; not logged again when batches are rebuilt
    assert AccessEntry.objects.filter(action='optout_readded').count() == 1


def test_an_opt_out_after_the_upload_is_not_re_added(company):
    sarah = codes_for(company).token(SARAH)
    upload(company, OCT, lambda n: [sarah] if n == 7 else [f'other{n}'])
    text_in(company, 'STOP', at=OCT + timedelta(days=5))
    assert check_batches(company) == 0 and ImportBatch.objects.get(kind='bulk_import').opted_out_readded == 0


def test_the_stop_list_is_locked_per_client(company, other_company):
    text_in(company, 'STOP')
    text_in(other_company, 'STOP')
    with _scope('client', str(company.pk)):
        assert list(OptOutEvent.objects.values_list('client_id', flat=True)) == [company.pk]


def test_synced_records_reach_the_stop_list():
    from apps.sync import handoff
    assert optout_seen in handoff.RECEIVERS
