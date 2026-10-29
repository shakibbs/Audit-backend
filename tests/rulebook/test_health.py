"""Module 13 step 5: the Rulebook check (needs a decision, with clients affected; not confirmed by a lawyer), each
rule's history, and the dashboard tile."""
from datetime import date

import pytest
from django.utils import timezone

from apps.contacts.models import ContactEvent
from apps.regulatory.approve import approve
from apps.regulatory.models import RegChange, RuleUpdate
from apps.rulebook.health import check, history
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def test_needs_a_decision_counts_clients_that_contacted_where_it_applies(company, other_company):
    for c, state in ((company, 'FL'), (other_company, 'TX')):
        ContactEvent.objects.create(client=c, phone_token='p', phone_token_kid='k', source_system='vicidial', source_record_id=f'{state}1',
                                    source_grade='B', channel='call', direction='outbound', occurred_at=timezone.now(), recipient_state=state)
    data = check()
    pending = {(r['key'], r['place']): r for r in data['pending']}
    assert ('calling_hours', 'FL') in pending and pending[('calling_hours', 'FL')]['clients'] == 1
    assert pending[('autodialed_modes', 'Federal')]['clients'] == 2  # federal rules reach every client with contacts
    assert data['pending'][0]['clients'] >= data['pending'][-1]['clients']  # most affected first
    assert any(r['key'] == 'conv_review_accuracy_pass_mark' for r in data['unconfirmed'])
    assert data['counts']['tbd'] > 0 and data['counts']['set'] > 0


def test_history_shows_the_old_value_ending_the_day_before_the_new(company):
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    law = RegChange.objects.get(jurisdiction='Oregon')
    update = RuleUpdate.objects.create(reg_change=law, key='optout_deadline_business_days', jurisdiction='US', value=5, shown='5',
                                       status='proposed', effective_from=date(2027, 1, 1), proposed_by='team')
    approve(update, staff)
    rows = [r for r in history('optout_deadline_business_days') if r['place'] == 'Federal']
    assert [(r['shown'], r['to']) for r in rows][-2:] == [('10', date(2026, 12, 31)), ('5', None)]


def test_admin_pages_and_tile(client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    page = client.get('/civ-admin/rulebook/rulevalue/check/').content.decode()
    assert 'Needs a decision' in page and 'autodialed_modes' in page and 'Not confirmed by a lawyer' in page
    assert 'Every value this rule has had' in client.get('/civ-admin/rulebook/rulevalue/rule-history/calling_hours/').content.decode()
    assert 'Rules needing a decision' in client.get('/civ-admin/').content.decode()


def test_federal_and_state_rules_add_up_to_all_rules(client):
    """Owner, 2026-10-30: the dashboard said "149 rules in all" (federal only) while the Rulebook lists 158."""
    from apps.rulebook.models import RuleValue
    data = check()
    federal, states = sum(data['counts'].values()), sum(data['state_counts'].values())
    assert states > 0 and federal + states == RuleValue.objects.count()
    client.force_login(StaffUser.objects.create_superuser(email='boss@complyiv.com', name='Boss', password=PASSWORD))
    assert f'{federal + states} rules in all ({federal} federal, {states} state or court)' in client.get('/civ-admin/').content.decode()
    assert 'State and court values today' in client.get('/civ-admin/rulebook/rulevalue/check/').content.decode()
