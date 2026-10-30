"""Module 12 step 5: the Vendor Ledger from the real scorecards."""
from datetime import UTC, date, datetime

import pytest

from apps.imports.models import CrmCreation
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.vendors.models import VendorMonth
from apps.vendors.portal import vendors_page

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def month(company, period, key, score, sub='', rates=None, leads=150):
    VendorMonth.objects.create(client=company, period=period, key=key, sub_id=sub, name=key.title(), leads=leads, score=score,
                               grade='B' if score and score >= 80 else ('D' if score else ''), measured=4,
                               rates=rates or {'high_signals': None, 'name_match': None, 'consent_problems': 0.08, 'consent_gaps': 0.3,
                                               'late_delivery': 0.1, 'stops': 0.02})


def test_scores_trend_alerts_and_cards(company):
    month(company, date(2026, 9, 1), 'vendor e', 85.0, sub='7')
    month(company, date(2026, 10, 1), 'vendor e', 73.8, sub='7')
    month(company, date(2026, 10, 1), 'vendor e', 86.4)
    page = vendors_page(company, NOW)
    rows = {(v['name'], v['subId']): v for v in page['vendors']}
    sub = rows[('Vendor E', '7')]
    assert (sub['score'], sub['monthOnMonth'], sub['alert'], sub['highSignals']) == (73.8, -11.2, True, None)
    assert sub['history'][-2:] == [85.0, 73.8] and sub['ratesMeasured'] == 4 and sub['notMeasuredRates'] == ['High-risk signals', 'Name mismatch']
    assert {r['label'] for r in sub['rates']} == {'Consent problems', 'Consent gaps', 'Late delivery', 'Stops and complaints'}
    assert page['gradeMix'] == '1 B' and page['alerts'] == 1 and 'fell 10 points' in page['alertNote']


def test_before_the_first_nightly_save_it_is_worked_out_on_the_spot(company, member_user, signed_in):
    CrmCreation.objects.create(client=company, source_system='hubspot', record_id='r1', created_at=NOW, vendor='SolarLeads Inc', phone_tokens=['t'])
    page = signed_in(member_user).get('/api/vendors').json()
    assert page['vendors'][0]['name'] == 'SolarLeads Inc' and page['vendors'][0]['notEnoughData'] is True
    assert not VendorMonth.objects.exists()  # nothing saved by reading the page


def test_the_vendor_ledger_follows_the_month(company, member_user, signed_in):
    """Owner, 2026-10-30: the month picker — September's scores, compared with August."""
    month(company, date(2026, 8, 1), 'vendor e', 90.0)
    month(company, date(2026, 9, 1), 'vendor e', 78.0)
    month(company, date(2026, 10, 1), 'vendor e', 86.4)
    sep = vendors_page(company, NOW, period='2026-09')
    row = sep['vendors'][0]
    assert (row['score'], row['monthOnMonth'], row['alert']) == (78.0, -12.0, True)
    assert sep['alertNote'] == '1 vendor fell 10 points or more in Sep 2026'
    assert vendors_page(company, NOW)['vendors'][0]['score'] == 86.4  # no month: this month, as before
    assert signed_in(member_user).get('/api/vendors?period=2026-09').json()['vendors'][0]['score'] == 78.0
