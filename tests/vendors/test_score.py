"""Module 12 step 2: vendor score from the measured rates (weights re-normalised), grades, not enough data, monthly
saves with a trend, the drop alert and M29."""
from datetime import UTC, date, datetime

import pytest

from apps.alerts.models import Alert
from apps.alerts.raise_ import refresh
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.vendors.models import VendorMonth
from apps.vendors.score import grade_mix, grade_of, history, save_month, score_of

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 10, 20, tzinfo=UTC)


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def test_spec_example_with_all_six_rates():
    rates = {'high_signals': 0.10, 'consent_problems': 0.08, 'consent_gaps': 0.30, 'name_match': 0.04, 'late_delivery': 0.10, 'stops': 0.02}
    assert score_of(rates, NOW.date()) == 88.6 and grade_of(88.6, NOW.date()) == 'B'


def test_rates_not_measured_are_left_out_and_the_weights_spread():
    rates = {'high_signals': None, 'consent_problems': 0.08, 'consent_gaps': 0.30, 'name_match': None, 'late_delivery': 0.10, 'stops': 0.02}
    # (0.30·0.08 + 0.15·0.30 + 0.05·0.10 + 0.05·0.02) / 0.55 = 0.1364 → 86.4
    assert score_of(rates, NOW.date()) == 86.4
    assert score_of({k: None for k in rates}, NOW.date()) is None


def month(company, period, key, score, sub='', leads=150):
    return VendorMonth.objects.create(client=company, period=period, key=key, sub_id=sub, name=key.title(), leads=leads,
                                      score=score, grade=grade_of(score, period) if score is not None else '')


def test_save_month_marks_small_vendors_not_enough_data(company):
    from apps.imports.models import CrmCreation
    for i in range(3):
        CrmCreation.objects.create(client=company, source_system='hubspot', record_id=f'r{i}', created_at=NOW, vendor='Tiny Leads', phone_tokens=[f't{i}'])
    assert save_month(company, NOW) == 1
    v = VendorMonth.objects.get()
    assert (v.period, v.leads, v.score, v.grade, v.measured) == (date(2026, 10, 1), 3, None, '', 0)
    save_month(company, NOW)  # the current month is replaced, not added again
    assert VendorMonth.objects.count() == 1


def test_trend_drop_alert_and_grade_mix(company):
    month(company, date(2026, 9, 1), 'vendor e', 85.0, sub='7')
    month(company, date(2026, 10, 1), 'vendor e', 73.8, sub='7')
    month(company, date(2026, 10, 1), 'vendor e', 88.0)
    month(company, date(2026, 10, 1), 'solar leads', 95.0)
    month(company, date(2026, 10, 1), 'tiny', None, leads=3)
    assert history(company, 'vendor e', '7', date(2026, 10, 1)) == [None, None, None, None, 85.0, 73.8]
    refresh(company, NOW)
    alert = Alert.objects.get(kind='Vendor score drop')
    assert alert.title == 'Vendor E, sub-ID 7 fell 11.2 points' and alert.severity == 'Medium'
    m29 = grade_mix(company, NOW)
    assert m29['display'] == '1 A · 1 B' and m29['note'] == 'Lowest: Vendor E (88.0) · 1 with not enough data'
