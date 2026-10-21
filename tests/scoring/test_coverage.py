"""Module 14 step 5: M36 evidence coverage (tools 1 · uploads 0.7 · missing 0, by score weight) and the coverage cap."""
from datetime import UTC, date, datetime

import pytest

from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.coverage import cap, coverage
from apps.scoring.models import SnapshotRun
from apps.scoring.portal import score_page

pytestmark = pytest.mark.django_db


def m(code, score, worst=False):
    return {'code': code, 'score': score, 'value': 0, **({'worstCase': True} if worst else {})}


def test_all_from_tools_is_full_coverage():
    assert coverage([m('M16', 100), m('M10', 50)])['value'] == 1.0


def test_uploads_count_seventy_and_missing_data_nothing():
    # F2 (0.20): M12 upload 0.7 · F4 (0.16): M16 tools 1 · F6 (0.08): M11 worst case 0
    result = coverage([m('M12', 100), m('M16', 100), m('M11', 0, worst=True)])
    assert result['value'] == round((0.20 * 0.7 + 0.16 * 1 + 0.08 * 0) / 0.44, 4)
    assert result['mix'] == {'C': round(0.16 / 0.44, 4), 'D': round(0.20 / 0.44, 4), 'N': round(0.08 / 0.44, 4)}


def test_nothing_scored_is_not_measured():
    assert coverage([m('M38', None)])['value'] is None


def test_the_cap_holds_below_sixty_percent():
    load(RULEBOOK_DIR / 'v3.0.yaml')
    assert cap(0.59, date(2026, 10, 1))['state'] == 'held' and cap(0.61, date(2026, 10, 1))['state'] == 'clear'
    assert cap(None, date(2026, 10, 1))['state'] == 'not_measured'


def test_the_score_card_shows_coverage_and_holds_the_grade(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    from apps.scoring.models import MetricSnapshot
    run = SnapshotRun.objects.create(client=company, period=date(2026, 9, 1), ran_at=datetime(2026, 9, 20, tzinfo=UTC), fingerprint='x',
                                     score={'factors': [], 'coverage': {'value': 0.4},
                                            'exposure': {'caps': {'hard': {'state': 'rule_pending'},
                                                                  'coverage': {'state': 'held', 'value': 0.4, 'floor': 0.6, 'grade': 'C'}}}})
    MetricSnapshot.objects.create(client=company, run=run, code='M15', state='measured', value=0, score=100, display='0')
    page = score_page(company, '2026-09')
    assert page['evidenceCoverage'] == 0.4 and page['rawGrade'] == 'A' and page['grade'] == 'C'
    covered = next(c for c in page['caps'] if c['name'] == 'Coverage cap')
    assert covered['held'] and 'below the 60% floor' in covered['detail']
