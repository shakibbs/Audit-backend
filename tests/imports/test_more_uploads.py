"""Module 8 step 3: uploads that update existing CRM records, and lists put straight into a dialer."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.contacts.epochs import epoch_for
from apps.contacts.normalize import codes_for
from apps.imports import dialer_lists
from apps.imports.batches import rebuild_dialer, rebuild_updates
from apps.imports.creations import creation_seen
from apps.imports.models import CrmCreation, CrmUpdate, ImportBatch
from apps.optouts.models import OptOutEvent, ReaddedNumber
from apps.optouts.readded import check_batches
from apps.provenance.ladder import rebuild as trace
from apps.provenance.models import Provenance
from apps.sync.connector import Record
from apps.sync.connectors import vicidial as vd

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)


def sf(company, i, at, dnc, user='005EMP', source='Web'):
    conn = Connection.objects.get_or_create(client=company, provider='salesforce', defaults={'status': Status.CONNECTED})[0]
    raw = json.dumps({'Id': f'00Q{i}', 'CreatedDate': '2026-01-05T10:00:00.000+0000', 'CreatedById': '005OLD', 'LastModifiedById': user,
                      'DoNotCall': dnc, 'LeadSource': source, 'Phone': f'916555{i:04d}'}).encode()
    creation_seen(company, conn, Record(f'leads:00Q{i}', raw, 'lead', at), [f'tok{i}'])


def test_a_sheet_merged_into_existing_records_is_an_update_upload(company):
    for i in range(300):
        sf(company, i, T0 - timedelta(days=90), dnc=False)  # created long ago
    for i in range(300):
        sf(company, i, T0 + timedelta(seconds=i / 3), dnc=False, source='Spring list')  # one person changes 300 records in 2 minutes
    assert CrmUpdate.objects.count() == 300
    rebuild_updates(company)
    batch = ImportBatch.objects.get(system='crm_update')
    assert (batch.kind, batch.updated_count, batch.created_by) == ('bulk_import', 300, '005EMP')


def test_an_upload_that_clears_do_not_call_brings_back_a_stop_number(company):
    sf(company, 1, T0 - timedelta(days=90), dnc=True)
    OptOutEvent.objects.create(client=company, phone_token='tok1', at=T0 - timedelta(days=60), channel='crm', method='crm_flag',
                               source_system='salesforce', source_record_id='leads:00Q1')
    for i in range(2, 30):
        sf(company, i, T0 - timedelta(days=90), dnc=False)
    for i in range(1, 30):
        sf(company, i, T0 + timedelta(seconds=i), dnc=False, source='Old sheet')
    rebuild_updates(company)
    batch = ImportBatch.objects.get(system='crm_update')
    assert batch.optouts_cleared == 1
    check_batches(company)
    batch.refresh_from_db()
    assert batch.opted_out_readded == 1 and ReaddedNumber.objects.get().phone_token == 'tok1'


def test_everyday_edits_are_not_an_upload(company):
    for i in range(3):
        sf(company, i, T0 - timedelta(days=90), dnc=False)
        sf(company, i, T0 + timedelta(hours=i), dnc=True)  # staff ticking do-not-call one by one
    rebuild_updates(company)
    assert set(ImportBatch.objects.filter(system='crm_update').values_list('kind', flat=True)) == {'hand_entered'}


def test_only_the_watched_fields_count_never_their_values(company):
    sf(company, 1, T0 - timedelta(days=90), dnc=False)
    conn = Connection.objects.get(client=company, provider='salesforce')
    raw = json.dumps({'Id': '00Q1', 'CreatedDate': '2026-01-05T10:00:00.000+0000', 'CreatedById': '005OLD', 'DoNotCall': False,
                      'LeadSource': 'Web', 'Phone': '9165550001', 'Status': 'Contacted'}).encode()
    creation_seen(company, conn, Record('leads:00Q1', raw, 'lead', T0), ['tok1'])
    assert not CrmUpdate.objects.exists()  # a status change is not an upload
    record = CrmCreation.objects.get()
    assert len(record.watched_sha) == 64 and record.opted_out is False


@pytest.fixture
def vicidial(company, monkeypatch):
    c = Connection(client=company, provider='vicidial', status=Status.CONNECTED)
    c.set_credentials({'account': 'db.example:3306/asterisk', 'key': 'r', 'secret': 'p'})
    c.save()
    rows = [{'lead_id': 100 + i, 'list_id': 1002, 'entry_date': datetime(2026, 10, 5, 9, 0, i), 'phone_number': f'916555{i:04d}'} for i in range(25)]
    asked = []

    def query(self, sql, params):
        asked.append((sql, params))
        return [r for r in rows if r['lead_id'] > params[0]][:params[1]]
    monkeypatch.setattr(vd.Vicidial, 'query', query)
    return c, asked


def test_a_list_put_straight_into_the_dialer_is_a_dialer_upload(company, vicidial):
    conn, asked = vicidial
    assert dialer_lists.read_vicidial(conn) == 25
    assert dialer_lists.read_vicidial(conn) == 0 and asked[-1][1][0] == 124  # carries on after the last lead read
    assert asked[0][0].startswith('SELECT') and 'vicidial_list' in asked[0][0]
    rebuild_dialer(company)
    batch = ImportBatch.objects.get(system='dialer')
    assert (batch.kind, batch.list_id, batch.created_count) == ('bulk_import', '1002', 25)


def test_a_dialer_number_that_has_a_crm_record_is_not_counted_again(company, vicidial):
    conn, _ = vicidial
    dialer_lists.read_vicidial(conn)
    token = codes_for(company).token('+19165550003')
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:1', created_at=T0, phone_tokens=[token])
    rebuild_dialer(company)
    assert ImportBatch.objects.get(system='dialer').created_count == 24


def test_a_called_number_from_a_dialer_upload_is_traced_as_one(company, vicidial):
    conn, _ = vicidial
    dialer_lists.read_vicidial(conn)
    rebuild_dialer(company)
    token = codes_for(company).token('+19165550004')
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id='u1',
                                source_grade='C', channel='call', direction='outbound', occurred_at=T0, epoch=epoch_for(company.pk, token, T0))
    trace(company)
    p = Provenance.objects.get()
    assert p.basis == 'manual_import' and p.source_name == 'Dialer upload · list 1002 · 05 Oct 2026'


def test_numbers_are_never_stored(company, vicidial):
    from django.db import connection as db
    conn, _ = vicidial
    dialer_lists.read_vicidial(conn)
    with db.cursor() as cur:
        cur.execute('SELECT * FROM dialer_list_entry')
        assert '5550003' not in repr(cur.fetchall())
