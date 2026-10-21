"""Card coverage, batch 4: Who You Contact from consent results, uploaded lists and CRM marks; the client's own switches."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.consent.models import ConsentProof, ConsentResult
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation, CrmUpdate, ImportBatch
from apps.metrics.models import LeadSourceCheck
from apps.metrics.who import who_contact
from apps.uploads.models import DncCheck, InternalListEntry, RndQuery, Source, UploadedFile
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now()
TODAY = NOW.date()
n = iter(range(10**6))


def call(company, token='p1', days_ago=2):
    at = NOW - timedelta(days=days_ago)
    return ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id=f'c{next(n)}',
                                       source_grade='C', channel='call', direction='outbound', occurred_at=at, masked_label='(916) •••-0001',
                                       epoch=epoch_for(company.pk, token, at))


def upload(company, source):
    return UploadedFile.objects.create(client=company, source=source, original_name='f.csv', sha256='0' * 64)


def area(company, area_id):
    return next(a for a in who_contact(company)['areas'] if a['id'] == area_id)


def checks(company, area_id):
    return {c['name']: c for c in area(company, area_id)['checks']}


def test_expired_customer_relationship(company):
    c = call(company)
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', primary_code='NP_NONE',
                                 codes=['NP_NONE', 'NP_RELATIONSHIP_LAPSED'], evaluation_as_of=NOW, rulebook_version='3.0')
    assert checks(company, 'dnc')['Expired customer relationship used']['result'] == '1 call'


def test_dnc_rows_wait_for_check_records_then_become_real(company):
    call(company, 'p1')
    call(company, 'p2')
    assert set(checks(company, 'dnc')) == {'Expired customer relationship used'}  # the rest keep "not supplied"
    up = upload(company, Source.DNC_CHECKS)
    DncCheck.objects.create(client=company, upload=up, phone_token='p1', checked_on=TODAY - timedelta(days=5), listed=True, list_name='national')
    DncCheck.objects.create(client=company, upload=up, phone_token='p2', checked_on=TODAY - timedelta(days=60), listed=False, list_name='CA')
    rows = checks(company, 'dnc')
    assert rows['National registry checked']['result'] == '50% of contacts'
    assert rows['Called after your provider flagged the number']['result'] == '1 contact'
    assert rows['Registry copy older than 31 days']['result'] == '1 contact'
    assert rows['State lists checked (CA, AZ, TX, FL, NV)']['result'] == 'Checked: CA'
    assert area(company, 'dnc')['flags'][0]['known'] == 'Flagged by your DNC check (national)'


def test_called_after_joining_the_internal_list_and_removed_too_early(company):
    call(company, 'p1')
    InternalListEntry.objects.create(client=company, upload=upload(company, Source.INTERNAL_LIST), phone_token='p1', added_on=TODAY - timedelta(days=10))
    CrmUpdate.objects.create(client=company, source_system='salesforce', record_id='leads:1', updated_at=NOW, cleared_optout=True)
    rows = checks(company, 'idn')
    assert rows['Called after joining your list']['result'] == '1 contact' and rows['Removed from the list too early']['state'] == 'fail'
    assert area(company, 'idn')['flags'][0]['known'] == 'Joined your do-not-call list'


def test_consent_age_and_safe_harbor(company):
    c = call(company, 'p1')
    proof = ConsentProof.objects.create(client=company, phone_token='p1', kind='certificate', proof_type='web_cert',
                                        captured_at=NOW - timedelta(days=500), source_system='salesforce', source_record_id='l1')
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='verified', proof=proof, evaluation_as_of=NOW, rulebook_version='3.0')
    RndQuery.objects.create(client=company, upload=upload(company, Source.RND_QUERIES), phone_token='p1', queried_on=TODAY - timedelta(days=3), result='no')
    rows = checks(company, 'rnd')
    assert rows['Consent older than 12 months']['result'] == '100%' and rows['Covered by the safe harbor']['result'] == '100% of contacts'


def test_lead_sources_are_your_vendors_and_uploads_with_your_switches(company, admin_user, member_user):
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:1', created_at=NOW, vendor='SolarLeads Inc')
    ImportBatch.objects.create(client=company, source_system='salesforce', created_by='005U', starts=NOW, ends=NOW, created_count=40, kind='bulk_import')
    api = browser_for(admin_user)
    rows = api.get('/api/who-contact').json()['leadSources']
    assert [(r['group'], r['name']) for r in rows][0] == ('vendor', 'SolarLeads Inc') and rows[1]['group'] == 'upload'
    reply = api.call('patch', f"/api/who-contact/{rows[0]['id']}", {'column': 'national', 'checked': True})
    assert reply.json()['checked']['national'] is True and LeadSourceCheck.objects.get().checked
    assert api.get('/api/who-contact').json()['leadSources'][0]['checked']['national'] is True
    assert AccessEntry.objects.filter(action='lead_source_marked').exists()
    assert browser_for(member_user).call('patch', f"/api/who-contact/{rows[0]['id']}", {'column': 'state', 'checked': True}).status_code == 403


def test_services_say_what_was_uploaded(company):
    up = upload(company, Source.INTERNAL_LIST)
    InternalListEntry.objects.create(client=company, upload=up, phone_token='p1', added_on=TODAY)
    services = {s['name']: s for s in who_contact(company)['services']}
    assert services['Internal do-not-contact list']['note'].startswith('Uploaded') and services['DNC check records']['note'] == 'Not supplied · blocks M13'


def test_nothing_real_yet_sends_no_empty_lists(company):
    """An empty list would wipe the portal's rows for checks that are not built yet (the page crashed on it)."""
    data = who_contact(company)
    assert all(a.get('checks') for a in data['areas']) and all(a.get('flags', [1]) for a in data['areas'])
    assert 'rnd' not in [a['id'] for a in data['areas']]  # no consent ages and no query logs yet: the sample stays
