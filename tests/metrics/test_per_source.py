"""Who checked what → what CiV found for each vendor and each uploaded list (owner 2026-11-16)."""
from datetime import timedelta

import pytest

from apps.imports.models import CrmCreation
from apps.metrics.who import who_contact
from apps.uploads.models import DncCheck, InternalListEntry, RndQuery, Source
from apps.vendors.models import VendorLead
from tests.metrics.test_who import NOW, TODAY, call, upload

pytestmark = pytest.mark.django_db


def rows(company):
    return {r['name']: r for r in who_contact(company)['leadSources']}


def vendor(company, name, tokens):
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id=f'contacts:{name}', created_at=NOW, vendor=name, phone_tokens=tokens)


def test_no_files_is_cant_tell(company):
    vendor(company, 'Vendor A', ['p1'])
    call(company, 'p1')
    found = rows(company)['Vendor A']['found']
    assert found['national'] == {'tone': 'gray', 'text': "Can't tell · no DNC check file"}
    assert found['internal']['text'] == "Can't tell · no internal list" and found['reassigned']['text'] == "Can't tell · no query logs"


def test_each_vendor_counts_its_own_numbers(company):
    vendor(company, 'Vendor A', ['p1', 'p2', 'p3', 'p9'])  # p9 never called: not counted
    vendor(company, 'Vendor B', ['p4'])
    for token in ('p1', 'p2', 'p3', 'p4'):
        call(company, token, days_ago=2)
    up = upload(company, Source.DNC_CHECKS)
    for token, days in (('p1', 5), ('p2', 40), ('p4', 3)):  # p2's check is too old; p3 has none
        DncCheck.objects.create(client=company, upload=up, phone_token=token, checked_on=TODAY - timedelta(days=days), listed=False, list_name='national')
    a, b = rows(company)['Vendor A']['found'], rows(company)['Vendor B']['found']
    assert a['national'] == {'tone': 'warn', 'text': 'of 3 numbers called were checked', 'checked': 1, 'total': 3, 'count': {'n': 2, 'label': 'not checked'}}
    assert b['national']['tone'] == 'ok' and 'count' not in b['national']
    assert a['state'] == {'tone': 'bad', 'text': 'No state check found'}  # national rows only


def test_internal_list_and_query_logs(company):
    vendor(company, 'Vendor A', ['p1', 'p2'])
    call(company, 'p1', days_ago=2)
    call(company, 'p2', days_ago=2)
    InternalListEntry.objects.create(client=company, upload=upload(company, Source.INTERNAL_LIST), phone_token='p1', added_on=TODAY - timedelta(days=10))
    RndQuery.objects.create(client=company, upload=upload(company, Source.RND_QUERIES), phone_token='p2', queried_on=TODAY - timedelta(days=4), result='no')
    found = rows(company)['Vendor A']['found']
    assert found['internal'] == {'tone': 'bad', 'text': 'on your list still called', 'count': {'n': 1, 'label': 'on your list still called'}}
    assert found['reassigned']['checked'] == 1 and found['reassigned']['total'] == 2


def test_uploaded_vendor_lead_file_has_its_own_counts(company):
    up = upload(company, Source.VENDOR_LEADS)
    for i, token in enumerate(['p1', 'p2']):
        VendorLead.objects.create(client=company, upload=up, row=i + 2, phone_token=token, vendor='Roof Leads', received_at=NOW)
    call(company, 'p1')
    DncCheck.objects.create(client=company, upload=upload(company, Source.DNC_CHECKS), phone_token='p1', checked_on=TODAY - timedelta(days=3), listed=False, list_name='national')
    file_row = next(r for name, r in rows(company).items() if name.startswith('Vendor lead file'))
    assert file_row['found']['national']['checked'] == 1 and file_row['found']['national']['total'] == 1
    assert rows(company)['Roof Leads']['found']['national']['tone'] == 'ok'  # the vendor row from the same file
