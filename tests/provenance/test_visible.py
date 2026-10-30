"""Module 8 step 5: the Lead Provenance page, the number page line, the Overview reminder and the admin tile."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation, ImportBatch
from apps.provenance.ladder import rebuild
from apps.provenance.requests import send
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now().replace(microsecond=0)


@pytest.fixture
def traced(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    batch = ImportBatch.objects.create(client=company, source_system='salesforce', created_by='005U', starts=NOW - timedelta(days=3),
                                       ends=NOW - timedelta(days=3), created_count=25, kind='bulk_import')
    for i in range(25):
        CrmCreation.objects.create(client=company, source_system='salesforce', record_id=f'leads:u{i}', created_at=NOW - timedelta(days=3),
                                   phone_tokens=[f'{i:02d}' + 'a' * 22], batch=batch)
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:7', created_at=NOW - timedelta(days=2),
                               phone_tokens=['b1' + 'b' * 22], vendor='SolarLeads Inc')
    for token, label in [*((f'{i:02d}' + 'a' * 22, f'(916) •••-{i:04d}') for i in range(25)), ('b1' + 'b' * 22, '(850) •••-0001'),
                         ('c1' + 'c' * 22, '(415) •••-0009')]:
        ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id=f'c{token}',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=NOW - timedelta(hours=1),
                                    masked_label=label, epoch=epoch_for(company.pk, token, NOW))
    rebuild(company)
    send(company)
    return company


def test_the_lead_provenance_page_shows_the_ladder_sources_untraced_and_uploads(traced, member_user):
    page = browser_for(member_user).get('/api/provenance').json()
    shares = {row['basis']: row['count'] for row in page['ladder']}
    assert page['numbers'] == 27 and shares == {'feed': 0, 'crm_field': 1, 'invoice': 0, 'cert_domain': 0, 'manual_import': 25, 'untraced': 1}
    assert {r['basis']: r['available'] for r in page['ladder']}['feed'] is False
    assert page['topSources'] == [{'name': 'SolarLeads Inc', 'basis': 'CRM lead source', 'count': 1}]
    assert [u['number'] for u in page['untraced']] == ['(415) •••-0009']
    upload = page['uploads'][0]
    assert (upload['numbers'], upload['withEvidence'], upload['asked']) == (25, 0, 25) and upload['label'].startswith('Uploaded list')


def test_the_number_page_says_where_it_came_from(traced, member_user):
    api = browser_for(member_user)
    ref = next(r['phoneE164'] for r in api.get('/api/contacts').json() if r['phoneDisplay'] == '(850) •••-0001')
    assert api.get(f'/api/evidence/{ref}').json()['cameFrom'] == 'CRM lead source · SolarLeads Inc'


def test_the_overview_reminds_about_unanswered_proof_requests(traced, member_user):
    assert browser_for(member_user).get('/api/data-health').json()['proofRequestsWaiting'] == 25


def test_another_client_sees_nothing(traced, other_admin):
    api = browser_for(other_admin)
    assert api.get('/api/provenance').json()['numbers'] == 0 and api.get('/api/proof-requests').json()['requests'] == []


def test_the_admin_client_page_has_a_provenance_tile(traced, client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    html = client.get(f'/civ-admin/clients/client/{traced.pk}/change/').content.decode()
    assert 'Lead provenance' in html and '4%' in html and 'No proof files to check' in html
    assert client.get(f'/civ-admin/provenance/proofrequest/?client__id__exact={traced.pk}').status_code == 200
