"""Uploaded lists: bursts of records by one user become bulk imports; typing and automatic feeds do not."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection as db

from apps.connections.models import Connection, Status
from apps.imports.batches import origin, rebuild
from apps.imports.creations import creation_seen
from apps.imports.models import CrmCreation, ImportBatch
from apps.sync.connector import Record
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def sf_lead(company, n, at, user='005EMP42', tokens=None):
    conn = Connection.objects.get_or_create(client=company, provider='salesforce', defaults={'status': Status.CONNECTED})[0]
    raw = json.dumps({'Id': f'00Q{n:012d}', 'CreatedDate': at.strftime('%Y-%m-%dT%H:%M:%S.000+0000'), 'CreatedById': user,
                      'FirstName': 'Sarah', 'Phone': '9165550001'}).encode()
    creation_seen(company, conn, Record(f'leads:00Q{n:012d}', raw, 'lead', at), tokens or [f'tok{n}'])


def hs_contact(company, n, at, how, user='77'):
    conn = Connection.objects.get_or_create(client=company, provider='hubspot', defaults={'status': Status.CONNECTED})[0]
    raw = json.dumps({'id': str(n), 'properties': {'createdate': at.isoformat().replace('+00:00', 'Z'), 'hs_object_source': how,
                                                   'hs_created_by_user_id': user}}).encode()
    creation_seen(company, conn, Record(f'contacts:{n}', raw, 'crm_record', at), [f'h{n}'])


def kinds(company):
    return sorted((b.kind, b.created_count) for b in ImportBatch.objects.filter(client=company))


def test_a_list_uploaded_in_3_minutes_is_one_bulk_import(company):
    for n in range(1240):
        sf_lead(company, n, T0 + timedelta(milliseconds=150 * n))  # 1,240 records in about 3 minutes
    assert rebuild(company) == 1
    assert kinds(company) == [('bulk_import', 1240)]


def test_typing_one_by_one_is_hand_entered_and_a_few_are_a_small_batch(company):
    for n in range(3):
        sf_lead(company, n, T0 + timedelta(minutes=30 * n), user='005EMP17')
    for n in range(10, 18):
        sf_lead(company, n, T0 + timedelta(hours=5, seconds=20 * n), user='005EMP17')
    rebuild(company)
    assert kinds(company) == [('hand_entered', 1), ('hand_entered', 1), ('hand_entered', 1), ('small_batch', 8)]


def test_a_gap_over_2_minutes_starts_a_new_batch_and_users_are_kept_apart(company):
    for n in range(25):
        sf_lead(company, n, T0 + timedelta(seconds=n))
    for n in range(25, 50):
        sf_lead(company, n, T0 + timedelta(minutes=10, seconds=n))  # same user, 10 minutes later
    for n in range(50, 75):
        sf_lead(company, n, T0 + timedelta(seconds=n - 50), user='005OTHER')  # another user at the same time
    rebuild(company)
    assert kinds(company) == [('bulk_import', 25)] * 3


def test_hubspot_import_label_wins_even_when_slow(company):
    for n in range(3):
        hs_contact(company, n, T0 + timedelta(seconds=n), 'IMPORT')
    hs_contact(company, 9, T0 + timedelta(hours=1), 'FORM')
    rebuild(company)
    batches = {b.kind: b for b in ImportBatch.objects.all()}
    assert batches['bulk_import'].labelled_by_tool and batches['bulk_import'].created_count == 3 and 'hand_entered' in batches


def test_an_automatic_feed_is_not_an_upload(company):
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    n = 0
    for day in range(6):
        for hour in range(0, 24, 2):  # steady, around the clock, every day
            for k in range(25):
                sf_lead(company, n, now - timedelta(days=day, hours=hour, seconds=k), user='005FEED')
                n += 1
    hs_contact(company, 99999, now, 'INTEGRATION', user='88')
    assert rebuild(company) == 0
    assert {b.kind for b in ImportBatch.objects.all()} == {'feed'}


def test_where_a_number_came_from(company):
    for n in range(30):
        sf_lead(company, n, T0 + timedelta(seconds=n), tokens=['sarah'] if n == 7 else None)
    rebuild(company)
    batch = origin(company, 'sarah', T0 + timedelta(days=2))
    assert batch.kind == 'bulk_import' and origin(company, 'sarah', T0 - timedelta(days=1)) is None


def test_no_names_and_creation_facts_never_change(company):
    sf_lead(company, 1, T0)
    sf_lead(company, 1, T0 + timedelta(days=3), user='005SOMEONE_ELSE', tokens=['tok1', 'new'])  # the same record seen again
    c = CrmCreation.objects.get()
    assert c.created_at == T0 and c.created_by == '005EMP42' and c.phone_tokens == ['new', 'tok1']
    with db.cursor() as cur:
        cur.execute('SELECT * FROM crm_creation')
        assert 'Sarah' not in repr(cur.fetchall())


def test_batches_are_locked_per_client(company, other_company):
    for client in (company, other_company):
        for n in range(20):
            sf_lead(client, n, T0 + timedelta(seconds=n))
        rebuild(client)
    with _scope('client', str(company.pk)):
        assert set(ImportBatch.objects.values_list('client_id', flat=True)) == {company.pk}


def test_crm_records_reach_the_import_watcher():
    from apps.sync import handoff
    assert creation_seen in handoff.RECEIVERS
