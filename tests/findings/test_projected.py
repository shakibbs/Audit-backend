"""Module 11 step 4: the projected score (top 5 open findings fixed, an estimate) and each finding's score impact."""
from datetime import UTC, date, datetime

import pytest

from apps.findings.build import refresh
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.models import MetricSnapshot, SnapshotRun
from apps.scoring.portal import score_page

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 20, tzinfo=UTC)


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def saved(company, metrics, hard=None):
    run = SnapshotRun.objects.create(client=company, period=date(2026, 9, 1), ran_at=NOW, fingerprint='x',
                                     score={'factors': [], 'exposure': {'caps': {'hard': hard or {'state': 'rule_pending'}}}})
    for code, state, value, score in metrics:
        MetricSnapshot.objects.create(client=company, run=run, code=code, state=state, value=value, score=score, display='')
    refresh(company, NOW)


def test_projection_fixes_the_top_findings(company):
    saved(company, [('M15', 'measured', 0, 100.0), ('M12', 'worst_case', None, 0.0), ('M11', 'worst_case', None, 0.0)])
    page = score_page(company, None)
    assert page['score'] == round(100 / 3, 1)  # XBD 100, IDN 0, RND 0
    assert page['projected'] == {'score': 100.0, 'grade': 'A', 'actions': 2, 'clearsCap': False}
    assert page['cap'] is None


def test_each_finding_shows_its_own_score_impact(company, admin_user, signed_in):
    saved(company, [('M15', 'measured', 0, 100.0), ('M12', 'worst_case', None, 0.0), ('M11', 'worst_case', None, 0.0)])
    rows = signed_in(admin_user).get('/api/actions').json()
    assert {r['impact'] for r in rows} == {'+33.4'}  # each lifts one of three domains from 0 to 100 (66.7 − 33.3)


def test_a_held_hard_cap_keeps_the_projection_at_c_unless_consent_is_fixed(company):
    saved(company, [('M15', 'measured', 0, 100.0), ('M16', 'measured', 3, 50.0)], hard={'state': 'held', 'share': 0.2})
    page = score_page(company, None)
    assert page['projected']['grade'] == 'C' and page['cap'] == {'share': 20.0, 'limit': None}
    assert page['projected']['clearsCap'] is False


def test_no_open_findings_sends_no_projection(company):
    saved(company, [('M15', 'measured', 0, 100.0)])
    assert 'projected' not in score_page(company, None)
