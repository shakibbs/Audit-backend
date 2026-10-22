"""Owner decision 2026-10-22: each client user switches their OWN view (saved per person); nobody else's screen
changes; not signed in and insurers cannot switch; the Underwriter view shows only the
user's own company with real data, as their insurer sees it."""
import pytest
from django.test import Client as Browser

from apps.buyers.models import BuyerOrg, BuyerUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def browser(email) -> Browser:
    b = Browser()
    assert b.post('/api/session/sign-in', {'email': email, 'password': PASSWORD}, content_type='application/json').status_code == 200
    return b


def switch(b, view):
    return b.post('/api/session/view-as', {'view': view}, content_type='application/json')


def test_each_person_has_their_own_view(company, admin_user, member_user):
    me, other = browser(admin_user.email), browser(member_user.email)
    assert switch(me, 'underwriter').json()['view'] == 'underwriter'
    assert me.get('/api/session').json()['view'] == 'underwriter'
    assert other.get('/api/session').json()['view'] == 'owner'  # nobody else's screen changes
    assert browser(admin_user.email).get('/api/session').json()['view'] == 'underwriter'  # remembered next sign-in
    assert switch(me, 'owner').json()['view'] == 'owner'
    assert switch(me, 'boss').status_code == 400


def test_not_signed_in_and_insurers_cannot_switch():
    assert switch(Browser(), 'underwriter').status_code in (401, 403)
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    person = BuyerUser(org=org, email='j@falconrisk.com', name='J')
    person.set_password(PASSWORD)
    person.save()
    b = browser(person.email)
    assert switch(b, 'owner').status_code == 403 and b.get('/api/session').json()['view'] == 'underwriter'


def test_members_and_lawyers_can_switch(company, member_user):
    member = browser(member_user.email)
    assert member.get('/api/session').json()['canSwitchView'] is True and switch(member, 'underwriter').status_code == 200
    member_user.is_counsel = True
    member_user.save()
    assert switch(browser(member_user.email), 'owner').status_code == 200


def test_the_underwriter_view_shows_only_your_own_company_with_real_data(company, other_company, admin_user):
    b = browser(admin_user.email)
    assert b.get('/api/insureds').status_code == 403  # owner view: no portfolio
    switch(b, 'underwriter')
    rows = b.get('/api/insureds')
    assert rows['X-CiV-Viewer'] == 'buyer' and [r['name'] for r in rows.json()] == [company.name]
    one = b.get(f"/api/insureds/{rows.json()[0]['id']}")
    assert one['X-CiV-Viewer'] == 'buyer' and one.json()['name'] == company.name and one.json()['praStates'] is None
    assert b.get(f'/api/insureds/c-{other_company.pk}').json()['name'] == company.name  # never another company
