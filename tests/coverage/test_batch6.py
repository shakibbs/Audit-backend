"""Card coverage, batch 6: Overview M01 / M10, Lead Provenance's first cards, Vendor Ledger names, Updated time, search."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.consent.models import ConsentResult
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation
from apps.metrics.overview import overview_metrics
from apps.sync.models import SyncCursor
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now()
TOKEN = 'ab' * 12 + 'c' * 40
n = iter(range(10**6))


def result(company, status, legal=True, codes=(), token=None):
    token = token or f'{next(n):024x}'
    c = ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id=f'c{next(n)}',
                                    source_grade='C', channel='call', direction='outbound', occurred_at=NOW - timedelta(days=1),
                                    masked_label='(916) •••-0001', epoch=epoch_for(company.pk, token, NOW))
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status=status, is_legal_basis=legal, codes=list(codes),
                                 evaluation_as_of=NOW, rulebook_version='3.0')
    return c


def test_consent_coverage_and_contacts_after_opt_out(company):
    result(company, 'verified')
    result(company, 'no_proof')
    result(company, 'verified', legal=False)
    result(company, 'no_proof', codes=['NP_AFTER_OPT_OUT'])
    m01, m10, *_ = overview_metrics(company, None)
    assert m01['value'] == 33.3 and 'including CiV-policy contacts' in m01['note'] and m01['history'][-1] == 33.3
    assert (m10['value'], m10['note']) == (1, '1 number affected')


def test_metrics_api_has_the_overview_numbers_too(company, member_user):
    result(company, 'verified')
    codes = [m['code'] for m in browser_for(member_user).get('/api/metrics').json()]
    assert 'M01' in codes and 'M10' in codes and 'M16' in codes


def test_leads_inspected_this_month(company, member_user):
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:1', created_at=NOW)
    data = browser_for(member_user).get('/api/leads').json()
    assert data == {'inspected': 1}  # no page photos yet: completeness and missing keep their sample


def test_vendors_are_your_own_and_search_finds_them_and_numbers(company, member_user):
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='contacts:1', created_at=NOW, vendor='SolarLeads Inc')
    result(company, 'verified', token=TOKEN)
    api = browser_for(member_user)
    vendor = api.get('/api/vendors').json()['vendors'][0]
    assert (vendor['name'], vendor['leads'], vendor['notEnoughData']) == ('SolarLeads Inc', 1, True)
    hits = api.get('/api/search?q=solar').json()
    assert hits == [{'kind': 'vendor', 'id': vendor['id'], 'label': 'SolarLeads Inc', 'hint': 'Vendor'}]
    assert api.get('/api/search?q=0001').json()[0]['label'] == '(916) •••-0001'


def test_no_vendors_says_so_instead_of_the_sample(company, member_user):
    page = browser_for(member_user).get('/api/vendors').json()
    assert page['vendors'] == [] and page['gradeMix'] == 'Not measured' and page['disputeCandidates'] == 0


def test_updated_time_is_the_last_read(company, member_user):
    conn = Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    SyncCursor.objects.create(client=company, connection=conn, source_system='twilio', last_event_at=NOW - timedelta(minutes=3))
    assert browser_for(member_user).get('/api/session').json()['updatedAt'].startswith((NOW - timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M'))
