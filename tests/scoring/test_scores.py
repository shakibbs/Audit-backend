"""Module 10 step 2: every metric becomes a 0–100 score (100 = best) with the Rulebook's draft bands; not yet measured
is left out, worst case is 0."""
from datetime import UTC, date, datetime

import pytest

from apps.contacts.models import ContactEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.models import MetricSnapshot
from apps.scoring.scores import DRAFT_BANDS, bands, score
from apps.scoring.snapshots import snapshot

pytestmark = pytest.mark.django_db
T = DRAFT_BANDS


def m(code, value=None, **more):
    return {'code': code, 'value': value, **more}


@pytest.mark.parametrize('metric,contacts,expected', [
    (m('M01', 91.5), 0, 91.5),  # a share: the share itself
    (m('M10', 0), 20_000, 100.0),  # no problems
    (m('M10', 6), 20_000, 50.0),  # 3 per 10,000
    (m('M10', 20), 20_000, 0.0),  # 10 per 10,000
    (m('M10', 0), 0, 100.0),  # nothing sent, nothing wrong
    (m('M08', 6.0, display='6.0 h'), 0, 100.0),
    (m('M08', 48.0, display='48.0 h'), 0, 50.0),
    (m('M08', None, display='NEVER'), 0, 0.0),
    (m('M09', None, pastDeadline=20, notHonored=1), 0, 50.0),  # 5 % not honored
    (m('M09', None, pastDeadline=20, notHonored=0), 0, 100.0),
    (m('M31', 2.4), 0, 50.0),
    (m('M31', 4.0), 0, 0.0),
    (m('M99', 3), 100, None),  # not a scored metric
])
def test_bands(metric, contacts, expected):
    assert score(metric, 'measured', contacts, T) == expected


def test_not_measured_is_left_out_and_worst_case_is_zero():
    assert score(m('M10', None), 'not_measured', 100, T) is None
    assert score(m('M17', None), 'rule_pending', 100, T) is None
    assert score(m('M12', None), 'worst_case', 100, T) == 0.0


def test_bands_come_from_the_rulebook():
    load(RULEBOOK_DIR / 'v3.0.yaml')
    assert bands(date(2026, 9, 1))['M08'] == [[24, 100], [72, 50]]


def test_saved_months_carry_their_scores(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    for i in range(3):  # three calls in hours, none after a stop
        ContactEvent.objects.create(client=company, phone_token=f'p{i}', phone_token_kid='k1', source_system='vicidial', source_record_id=f'c{i}',
                                    source_grade='B', channel='call', direction='outbound', occurred_at=datetime(2026, 9, 3, 16, tzinfo=UTC),
                                    time_zones=['America/New_York'])
    run = snapshot(company, date(2026, 9, 1), now=datetime(2026, 9, 20, tzinfo=UTC))
    assert run.contacts == 3
    saved = {s.code: s for s in MetricSnapshot.objects.filter(run=run)}
    assert saved['M16'].score == 100.0 and saved['M16'].data['score'] == 100.0
    assert saved['M38'].score is None  # not measured: left out
