"""Module 10 step 5: the portal's Audit Score, domain cards and factor map, all from the same saved metric scores."""
from datetime import UTC, date, datetime

import pytest

from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.scoring.models import MetricSnapshot, SnapshotRun
from apps.scoring.portal import domains_page, exposure_reading, score_page

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def saved(company, period, scores: dict, values: dict | None = None, factors=None, exposure=None):
    run = SnapshotRun.objects.create(client=company, period=period, ran_at=datetime(2026, 10, 1, tzinfo=UTC), fingerprint='x',
                                     score={'factors': factors or [{'key': f'F{i}', 'value': None, 'pending': True} for i in range(1, 7)],
                                            'defect': None, 'partial': True, 'exposure': exposure or {}})
    for code, s in scores.items():
        MetricSnapshot.objects.create(client=company, run=run, code=code, value=(values or {}).get(code, 0), display='', state='measured', score=s)
    return run


def test_domain_is_the_mean_of_its_metric_scores_and_the_score_the_mean_of_domains(company):
    saved(company, date(2026, 9, 1), {'M16': 100, 'M17': 50, 'M18': None, 'M15': 100, 'M13': 0})
    domains = {d['code']: d for d in domains_page(company, '2026-09')}
    assert domains['CTF']['score'] == 75.0 and (domains['CTF']['run'], domains['CTF']['notRun']) == (2, 1)
    assert (domains['CTF']['pass'], domains['CTF']['warn'], domains['CTF']['fail']) == (1, 0, 1)
    score = score_page(company, '2026-09')
    # CTF 75, SMS 100 (M16), XBD 100; NDN / SDN (M13) are shown but never counted
    assert score['score'] == round((75 + 100 + 100) / 3, 1) and score['grade'] == 'A' and score['domainsMeasured'] == 3
    assert 'NDN' in domains and score['draftBands'] is True and score['partial'] == {'factorsMeasured': 0, 'factors': 6}


def test_contact_after_a_stop_holds_rev_at_d(company):
    saved(company, date(2026, 9, 1), {'M08': 100, 'M09': 100, 'M10': 50}, values={'M10': 2},
          exposure={'caps': {'hard': {'state': 'rule_pending'}, 'coverage': {'state': 'not_measured'}}})
    rev = {d['code']: d for d in domains_page(company, '2026-09')}['REV']
    assert rev['score'] == 69.9 and rev['held']
    caps = {c['name']: c for c in score_page(company, '2026-09')['caps']}
    assert caps['Contact-after-stop cap']['held'] and 'REV' in caps['Contact-after-stop cap']['detail']
    assert caps['Hard cap']['detail'].startswith('Rule pending') and not caps['Coverage cap']['held']


def test_history_and_previous_from_saved_months(company):
    saved(company, date(2026, 8, 1), {'M15': 50})
    saved(company, date(2026, 9, 1), {'M15': 100})
    score = score_page(company, '2026-09')
    assert [h['score'] for h in score['history']] == [50.0, 100.0] and score['previous'] == 50.0


def test_nothing_saved_sends_nothing(company):
    assert score_page(company, None) == {} and domains_page(company, None) == []


def test_factor_map_reading_with_pending_factors(company):
    factors = [{'key': 'F1', 'value': 20.0, 'pending': False}] + [{'key': f'F{i}', 'value': None, 'pending': True} for i in range(2, 7)]
    saved(company, date(2026, 9, 1), {'M01': 80}, factors=factors, exposure={'venue': {'value': 1.2}, 'targeting': {'value': 1.0}, 'volume': {'value': 0.9}})
    reading = exposure_reading(company)
    assert reading['factors'] == [20.0, None, None, None, None, None] and (reading['venue'], reading['volume']) == (1.2, 0.9)
    assert reading['source'].endswith('partial · draft bands')


def test_api(company, member_user, signed_in):
    saved(company, date(2026, 9, 1), {'M15': 100})
    api = signed_in(member_user)
    assert api.get('/api/score?period=2026-09').json()['score'] == 100.0
    assert api.get('/api/domains').json()[0]['code'] == 'XBD'
    assert api.get('/api/insureds/sunpath').json()['exposure']['inside']['factors'] == [None] * 6
