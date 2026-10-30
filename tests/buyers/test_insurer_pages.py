"""Module 15 step 3: a buyer's insurer pages come from the newest snapshot of each company sharing with it right now
(made at once when sharing starts); nothing measured is never filled with samples; opening a sheet shows in that
company's access log; stopping sharing hides it on the next request."""
import pytest
from django.test import Client as Browser
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.buyers.models import AttestationSnapshot, BuyerLink, BuyerOrg, BuyerUser
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def underwriter(org) -> Browser:
    person = BuyerUser(org=org, email=f'j.merchant@{org.domain}', name='J. Merchant')
    person.set_password(PASSWORD)
    person.save()
    b = Browser()
    assert b.post('/api/session/sign-in', {'email': person.email, 'password': PASSWORD}, content_type='application/json').status_code == 200
    return b


def test_sharing_makes_a_snapshot_at_once_and_the_insurer_sees_it(company, other_company, admin_user, signed_in):
    signed_in(admin_user).call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'a.lee@falconrisk.com'})
    assert AttestationSnapshot.objects.filter(client=company).count() == 1  # this month so far, before the nightly run
    b = underwriter(BuyerOrg.objects.get())
    page = b.get('/api/insureds')
    assert page['X-CiV-Viewer'] == 'buyer'
    rows = page.json()
    assert [r['name'] for r in rows] == [company.name]  # only the company that shares, never the other one
    one = b.get(f"/api/insureds/{rows[0]['id']}").json()
    assert one['name'] == company.name and one['optOutMedianHours'] is None and one['praStates'] is None  # not measured: empty, no sample
    assert len(one['sheetHash']) == 12 and one['exposure']['outside'] is None
    assert b.get(f'/api/insureds/c-{other_company.pk}').status_code == 404
    entry = AccessEntry.objects.get(action='attestation_viewed')
    assert entry.client_id == company.pk and entry.actor_label == 'J. Merchant (Falcon Risk)'
    b.get(f"/api/insureds/{rows[0]['id']}")
    assert AccessEntry.objects.filter(action='attestation_viewed').count() == 1  # once a day per person


def test_stopping_sharing_hides_the_company_at_the_next_request(company, admin_user, signed_in):
    signed_in(admin_user).call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'a.lee@falconrisk.com'})
    b = underwriter(BuyerOrg.objects.get())
    ref = b.get('/api/insureds').json()[0]['id']
    BuyerLink.objects.update(revoked_at=timezone.now())
    assert b.get('/api/insureds').json() == [] and b.get(f'/api/insureds/{ref}').status_code == 404


def test_the_insurer_reads_court_figures_but_no_client_page(company):
    b = underwriter(BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com'))
    assert b.get('/api/litigation')['X-CiV-Viewer'] == 'buyer'
    for path in ('/api/contacts', '/api/alerts', '/api/statements', '/api/access-log'):
        assert b.get(path).status_code in (401, 403), path


def test_the_whole_insurer_journey_without_test_access(company, admin_user, signed_in, monkeypatch):
    """Like a real browser: no all-companies view, only the scope each request sets for itself."""
    import re

    from django.core import mail

    from apps.tenancy.scope import _scope
    signed_in(admin_user).call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'a.lee@falconrisk.com'})
    token = re.search(r'invite=([\w-]+)', mail.outbox[-1].body).group(1)
    with _scope('', ''):
        b = Browser()
        b.post('/api/invites/accept', {'token': token, 'password': PASSWORD}, content_type='application/json')
        rows = b.get('/api/insureds').json()
        assert [r['name'] for r in rows] == [company.name]
        assert b.get(f"/api/insureds/{rows[0]['id']}").json()['name'] == company.name
        assert b.get('/api/litigation').status_code == 200
        assert b.get('/api/rating-engine').json()['url'] == ''
        assert b.get('/api/contacts').status_code in (401, 403)


def test_the_insurer_picks_a_month_but_only_from_when_sharing_began(company, admin_user, signed_in):
    """Owner, 2026-10-30 (option B): the insurer's own month picker; months before the company started sharing stay hidden."""
    from datetime import date, datetime, UTC
    signed_in(admin_user).call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'a.lee@falconrisk.com'})
    newest = AttestationSnapshot.objects.get(client=company)
    BuyerLink.objects.update(granted_at=datetime(2026, 9, 12, tzinfo=UTC))  # shared since 12 Sep
    for month in (date(2026, 8, 1), date(2026, 9, 1)):
        AttestationSnapshot.objects.create(client=company, period=month, payload={**newest.payload, 'company': company.name}, sha256=f'{month:%m}' * 32)
    b = underwriter(BuyerOrg.objects.get())
    months = [p['id'] for p in b.get('/api/session').json()['periods']]
    assert '2026-09' in months and '2026-08' not in months  # August was before sharing began
    assert [r['name'] for r in b.get('/api/insureds?period=2026-09').json()] == [company.name]
    assert b.get('/api/insureds?period=2026-08').json() == []
    assert b.get(f'/api/insureds/c-{company.pk}?period=2026-09').json()['sheetHash'] == '09' * 6
    assert b.get(f'/api/insureds/c-{company.pk}?period=2026-08').status_code == 404


def test_the_clients_shared_pages_follow_its_month(company, admin_user, signed_in):
    """The client's "Shared with your insurer" pages show the sheet of the month it picked."""
    from datetime import date
    api = signed_in(admin_user)
    api.call('post', '/api/buyer-links', {'name': 'Falcon Risk', 'email': 'a.lee@falconrisk.com'})
    newest = AttestationSnapshot.objects.get(client=company)
    AttestationSnapshot.objects.create(client=company, period=date(2026, 9, 1), payload=newest.payload, sha256='9' * 64)
    assert api.get('/api/insureds/own?period=2026-09').json()['sheetHash'] == '9' * 12
    assert api.get('/api/insureds/own?period=2026-07').status_code == 404
    assert api.get('/api/insureds/own').json()['sheetHash'] == newest.sha256[:12]
