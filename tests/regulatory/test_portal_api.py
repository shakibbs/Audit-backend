"""Portal API for the Rulebook and Regulatory Changes pages: everyone reads; the company's lawyer reviews drafts and
suggests changes; each company sees only its own reviews, reads and suggestions."""
from datetime import date

import pytest
from django.test import Client as BrowserClient

from apps.accounts.models import ClientUser, Role
from apps.regulatory.approve import approve
from apps.regulatory.models import ClientSuggestion, RegChange, RuleUpdate, RuleUpdateReview
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.staff.models import StaffUser
from apps.tenancy.scope import _scope, tenant
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db  # also opens the "all clients" view for checks across companies


@pytest.fixture
def rulebook(db):
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


@pytest.fixture
def lawyer(company):
    return ClientUser.objects.create_user(client=company, email='okafor@sunpath.com', name='M. Okafor', password=PASSWORD, is_counsel=True)


@pytest.fixture
def other_lawyer(other_company):
    return ClientUser.objects.create_user(client=other_company, email='lee@ridgeline.com', name='J. Lee', password=PASSWORD,
                                          role=Role.ADMIN, is_counsel=True)


@pytest.fixture
def draft(rulebook):
    law = RegChange.objects.get(jurisdiction='Oregon')
    return RuleUpdate.objects.create(reg_change=law, key='calling_hours', jurisdiction='OR', value={'start': '08:00', 'end': '20:00'},
                                     shown='8am – 8pm', status='set', effective_from=date(2026, 1, 1), proposed_by='team@complyiv.com')


def browser_for(user):
    b = BrowserClient(enforce_csrf_checks=True)
    b.get('/api/session')
    token = b.cookies['csrftoken'].value
    b.call = lambda method, path, body=None: getattr(b, method)(path, body or {}, content_type='application/json', HTTP_X_CSRFTOKEN=token)
    assert b.call('post', '/api/session/sign-in', {'email': user.email, 'password': PASSWORD}).status_code == 200
    return b


def test_rulebook_page_counts_note_and_no_banned_names(rulebook, member_user):
    data = browser_for(member_user).get('/api/rulebook').json()
    assert (data['set'], data['proposed'], data['tbd']) == (70, 59, 20)
    assert data['versionStatus'] == 'provisional' and 'not yet confirmed by a lawyer' in data['note']
    keys = {s['key'] for s in data['settings']}
    assert 'direct_contact_cap_grade' in keys and not any('violation' in k for k in keys)
    fl = next(s for s in data['settings'] if s['key'] == 'calling_hours' and s['place'] == 'FL')
    assert fl['status'] == 'tbd' and fl['value'] == 'Not set yet'


def test_calendar_and_hours(rulebook, member_user):
    data = browser_for(member_user).get('/api/rulebook/calendar?year=2026').json()
    assert {'date': '2026-11-26', 'name': 'Thanksgiving Day', 'actual': '2026-11-26'} in data['holidays']
    assert {'date': '2026-07-03', 'name': 'Independence Day', 'actual': '2026-07-04'} in data['holidays']
    hours = {h['place']: h for h in data['callingHours']}
    assert hours['Federal']['value'] == '8am – 9pm' and hours['FL']['value'] == '8am – 8pm' and hours['FL']['status'] == 'tbd'
    assert hours['TX']['value'] == '8am – 9pm; Sunday from 12pm'
    limits = {h['place']: h for h in data['frequencyLimits']}
    assert limits['FL']['value'] == '3 per 24 hours per person, solicitations only' and limits['Federal']['value'] is None
    assert data['optOut']['deadlineDays']['value'] == 10 and data['optOut']['deadlineDays']['status'] == 'proposed'


def test_signed_out_sees_nothing(rulebook):
    assert BrowserClient().get('/api/rulebook').status_code in (401, 403)
    assert BrowserClient().get('/api/reg-changes').status_code in (401, 403)


def test_read_mark_is_per_company(rulebook, member_user, other_admin):
    mine, theirs = browser_for(member_user), browser_for(other_admin)
    first = mine.get('/api/reg-changes').json()[0]['id']
    assert mine.call('post', f'/api/reg-changes/{first}/confirm').status_code == 200
    assert next(c for c in mine.get('/api/reg-changes').json() if c['id'] == first)['confirmed'] is True
    assert next(c for c in theirs.get('/api/reg-changes').json() if c['id'] == first)['confirmed'] is False


def test_only_the_lawyer_reviews_and_each_company_sees_only_its_own(draft, member_user, lawyer, other_lawyer):
    path = f'/api/rule-updates/ru-{draft.pk}/review'
    assert browser_for(member_user).call('post', path, {'verdict': 'agree'}).status_code == 403
    mine = browser_for(lawyer)
    assert mine.call('post', path, {'verdict': 'disagree', 'comment': 'Texts are covered too.'}).status_code == 200
    assert mine.call('post', path, {'verdict': 'agree'}).status_code == 200  # can change until CiV decides
    browser_for(other_lawyer).call('post', path, {'verdict': 'disagree'})
    oregon = next(c for c in mine.get('/api/reg-changes').json() if c['jurisdiction'] == 'Oregon')
    update = oregon['updates'][0]
    assert update['state'] == 'draft' and update['myReview']['verdict'] == 'agree' and update['myReview']['by'] == 'M. Okafor'
    assert RuleUpdateReview.objects.count() == 2
    with tenant(lawyer.client_id), _scope('client', str(lawyer.client_id)):
        assert RuleUpdateReview.objects.count() == 1  # the database itself hides the other company's review


def test_reviews_show_in_the_admin_and_close_when_civ_decides(client, draft, lawyer, other_lawyer):
    browser_for(lawyer).call('post', f'/api/rule-updates/ru-{draft.pk}/review', {'verdict': 'agree'})
    browser_for(other_lawyer).call('post', f'/api/rule-updates/ru-{draft.pk}/review', {'verdict': 'disagree', 'comment': 'Too strict'})
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(staff)
    page = client.get(f'/civ-admin/regulatory/regchange/{draft.reg_change_id}/change/').content.decode()
    assert '1 agree · 1 disagree' in page and 'Too strict' in page
    approve(draft, staff)
    assert browser_for(lawyer).call('post', f'/api/rule-updates/ru-{draft.pk}/review', {'verdict': 'disagree'}).status_code == 400


def test_suggestions_go_only_to_civ(client, rulebook, member_user, lawyer, other_admin):
    body = {'title': 'Florida ends calls at 7pm', 'jurisdiction': 'Florida', 'summary': 'New bill.', 'source': 'FL HB 9'}
    assert browser_for(member_user).call('post', '/api/reg-changes/suggest', body).status_code == 403
    assert browser_for(lawyer).call('post', '/api/reg-changes/suggest', body).status_code == 201
    assert not any(c['title'] == body['title'] for c in browser_for(other_admin).get('/api/reg-changes').json())
    assert ClientSuggestion.objects.get().client_id == lawyer.client_id
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    client.force_login(staff)
    assert 'Florida ends calls at 7pm' in client.get('/civ-admin/regulatory/clientsuggestion/').content.decode()


def test_vendor_clauses_draft_is_reviewed_by_lawyers_and_approved_by_civ(rulebook, lawyer):
    """Module 12: CiV's draft of the vendor contract clauses, as a rule update the clients' lawyers review."""
    from apps.rulebook.lookup import RuleSet
    mine = browser_for(lawyer)
    change = next(c for c in mine.get('/api/reg-changes').json() if c['title'] == 'CiV draft: clauses each vendor contract must contain')
    update = change['updates'][0]
    assert update['state'] == 'draft' and change['jurisdiction'] == 'CiV draft'
    assert mine.call('post', f"/api/rule-updates/{update['id']}/review", {'verdict': 'agree', 'comment': 'Looks right.'}).status_code == 200
    staff = StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD)
    approve(RuleUpdate.objects.get(key='vendor_required_clauses'), staff)
    rule = RuleSet('internal').get('vendor_required_clauses', on=date(2026, 10, 22))
    assert rule.status == 'set' and len(rule.value) == 12
