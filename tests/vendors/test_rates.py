"""Module 12 step 1: each vendor's leads (and sub-IDs) over 90 days with the four rates CiV can measure; high-risk
signals and name match not measured yet; a rate with nothing to count is left out."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.consent.models import ConsentProof, ConsentResult
from apps.contacts.models import ContactEvent
from apps.imports.creations import sub_of, vendor_of
from apps.imports.models import CrmCreation
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.vendors.rates import vendor_rates

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 10, 20, tzinfo=UTC)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def lead(company, vendor, sub='', days_ago=40, token=None, consent_hours_before=None, status=None, codes=(), stop_after_days=None):
    token = token or f'p{next(n)}'
    created = NOW - timedelta(days=days_ago)
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id=f'r{next(n)}', created_at=created, vendor=vendor,
                               sub_id=sub, phone_tokens=[token])
    if consent_hours_before is not None:
        ConsentProof.objects.create(client=company, phone_token=token, kind='certificate', captured_at=created - timedelta(hours=consent_hours_before),
                                    source_system='trustedform', source_record_id=f'c{next(n)}')
    if status:
        c = ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id=f'v{next(n)}',
                                        source_grade='B', channel='call', direction='outbound', occurred_at=created + timedelta(hours=1))
        ConsentResult.objects.create(client=company, contact=c, variant='strict', status=status, codes=list(codes),
                                     evaluation_as_of=c.occurred_at, rulebook_version='3.0')
        if stop_after_days is not None:
            OptOutEvent.objects.create(client=company, phone_token=token, at=c.occurred_at + timedelta(days=stop_after_days), channel='text',
                                       method='keyword', source_system='twilio', source_record_id=f's{next(n)}')


def rows(company):
    return {(r['key'], r['subId']): r for r in vendor_rates(company, NOW)}


def test_sub_ids_are_read_and_never_taken_for_the_vendor():
    raw = json.dumps({'properties': {'lead_vendor': 'SolarLeads Inc', 'affiliate_sub_id': '7'}}).encode()
    assert (vendor_of('hubspot', raw), sub_of('hubspot', raw)) == ('SolarLeads Inc', '7')


def test_the_four_rates(company):
    lead(company, 'SolarLeads Inc', status='verified', consent_hours_before=2)
    lead(company, 'SolarLeads Inc', status='no_proof', consent_hours_before=30)  # problem, late
    lead(company, 'solarleads  inc', status='weak', codes=['WK_WORDING'], stop_after_days=5)  # gap, stopped (same vendor)
    lead(company, 'SolarLeads Inc')  # never called
    v = rows(company)[('solarleads inc', None)]
    assert v['name'] == 'SolarLeads Inc' and v['leads'] == 4
    assert v['rates'] == {'high_signals': None, 'name_match': None, 'consent_problems': round(1 / 3, 4), 'consent_gaps': round(1 / 3, 4),
                          'late_delivery': 0.5, 'stops': round(1 / 3, 4)}
    assert v['measured'] == 4


def test_sub_id_rows_and_vendor_totals(company):
    lead(company, 'Vendor E', sub='7', status='conflicting')
    lead(company, 'Vendor E', sub='7', status='verified')
    lead(company, 'Vendor E', status='verified')
    found = rows(company)
    assert found[('vendor e', None)]['leads'] == 3 and found[('vendor e', '7')]['leads'] == 2
    assert found[('vendor e', '7')]['rates']['consent_problems'] == 0.5


def test_unfinished_stop_windows_and_old_leads_are_left_out(company):
    lead(company, 'New Vendor', days_ago=10, status='verified')  # 30-day stop window not finished
    lead(company, 'New Vendor', days_ago=200, status='no_proof')  # outside the 90 days
    v = rows(company)[('new vendor', None)]
    assert v['leads'] == 1 and v['rates']['stops'] is None and v['rates']['late_delivery'] is None and v['measured'] == 2
