"""Card coverage, batch 5: Setup & Readiness from what CiV really has; Settings plan and usage; billed numbers CSV."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing.models import Contract
from apps.connections.models import Connection, Status
from apps.consent.models import ConsentResult
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.onboarding.readiness import plan_for, readiness, usage
from apps.sync.models import SyncCursor
from apps.uploads.models import Source, UploadedFile
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
NOW = timezone.now()
n = iter(range(10**6))


def call(company, token, days_ago=1, **extra):
    at = NOW - timedelta(days=days_ago)
    return ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id=f'c{next(n)}',
                                       source_grade='C', channel='call', direction='outbound', occurred_at=at, masked_label=f'(916) •••-{token[-4:]}',
                                       epoch=epoch_for(company.pk, token, at), **extra)


def checks(company):
    return {c['name']: c for c in readiness(company)['checks']}


def test_nothing_connected_cannot_start(company):
    data = readiness(company)
    assert data['canStart'] is False and checks(company)['Dialer connection']['state'] == 'missing'
    assert checks(company)['Documents']['detail'] == 'DNC scrub records and reassigned-number query logs not supplied'


def test_a_live_dialer_and_calls_make_it_ready(company):
    conn = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    SyncCursor.objects.create(client=company, connection=conn, source_system='convoso', last_heartbeat_at=NOW, last_event_at=NOW)
    for i in range(5):
        call(company, f'p{i:04d}', dial_mode='' if i == 0 else 'manual', caller_id_token='cid1', campaign='SP-Roof', recipient_state='CA')
    data = readiness(company)
    rows = {c['name']: c for c in data['checks']}
    assert data['canStart'] and rows['Dialer connection']['state'] == 'partial' and '20%' in rows['Dialer connection']['detail']
    assert rows['Consent proof']['detail'] == '0 of 5 found' and data['numbersPerMonth'] == 5 and data['recommendedPlan'] == 'Starter'
    assert {s['id']: s['count'] for s in data['setup']} == {'caller-ids': '1 caller IDs', 'campaigns': '1 campaigns · all treated as marketing', 'states': '1 states'}


def test_documents_and_preview(company):
    UploadedFile.objects.create(client=company, source=Source.DNC_CHECKS, original_name='d.csv', sha256='0' * 64)
    c = call(company, 'p0001')
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='verified', evaluation_as_of=NOW, rulebook_version='3.0')
    data = readiness(company)
    assert {c['name']: c for c in data['checks']}['Documents']['detail'] == 'Reassigned-number query logs not supplied'
    assert data['preview'][0] == {'status': 'VERIFIED', 'count': 1}


def test_plans_by_numbers():
    assert [plan_for(x) for x in (9_000, 30_000, 120_000, 400_000)] == ['Starter', 'Growth', 'Scale', 'Enterprise']


def test_usage_counts_distinct_numbers_and_the_price(company, member_user):
    for i in range(3):
        call(company, f'p{i:04d}')
        call(company, f'p{i:04d}')  # the same number twice counts once
    Contract.objects.create(client=company, price=6500, billing_period='monthly')
    u = usage(company)
    assert (u['plan'], u['limit'], u['used'], u['monthlyPrice'], u['nextPlan']) == ('Growth', 50_000, 3, '$6,500', 'Scale')
    assert len(u['history']) == 4 and u['history'][-1]['used'] == 3
    csv = browser_for(member_user).get('/api/billed-numbers')
    lines = csv.content.decode().strip().splitlines()
    assert csv['Content-Type'] == 'text/csv' and len(lines) == 4 and '•••' in lines[1] and '555' not in csv.content.decode()


def test_readiness_api_is_own_company_only(company, other_admin):
    call(company, 'p0001')
    assert browser_for(other_admin).get('/api/readiness').json()['numbersPerMonth'] == 0
