"""Module 15 step 1: the client invites its insurer or acquirer (one buyer per email domain), the person sets a
password from the invite and signs in to the underwriter view; the database shows a buyer only its own links and no
client data; stopping sharing works at once; CiV staff can block a buyer."""
import re

import pytest
from django.core import mail
from django.db import connection

from apps.buyers.models import BuyerInvite, BuyerLink, BuyerOrg, BuyerUser
from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.tenancy.scope import buyer
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def share(api, email='j.merchant@falconrisk.com', name='Falcon Risk', **more):
    return api.call('post', '/api/buyer-links', {'name': name, 'email': email, 'person': 'J. Merchant', **more})


def token_from_mail() -> str:
    return re.search(r'invite=([\w-]+)', mail.outbox[-1].body).group(1)


def test_a_client_admin_shares_and_the_underwriter_signs_up(company, admin_user, signed_in, client):
    made = share(signed_in(admin_user)).json()
    assert made['org'] == 'Falcon Risk' and made['active'] and made['invited']
    org = BuyerOrg.objects.get()
    assert (org.domain, org.kind) == ('falconrisk.com', 'insurer')
    from django.test import Client as Browser  # a fresh browser: the invited person
    b = Browser(enforce_csrf_checks=True)
    b.get('/api/session')
    csrf = b.cookies['csrftoken'].value
    token = token_from_mail()
    assert b.get(f'/api/invites/check?token={token}').json()['clientName'] == 'Falcon Risk'
    session = b.post('/api/invites/accept', {'token': token, 'password': PASSWORD}, content_type='application/json', HTTP_X_CSRFTOKEN=csrf).json()
    assert session['view'] == 'underwriter' and session['orgKind'] == 'insurer' and BuyerUser.objects.filter(email='j.merchant@falconrisk.com').exists()
    assert b.get('/api/contacts').status_code in (401, 403)  # no client page for a buyer


def test_one_buyer_per_domain_and_no_one_joins_another_insurer(company, other_company, admin_user, other_admin, signed_in):
    share(signed_in(admin_user))
    share(signed_in(other_admin), email='a.lee@falconrisk.com', name='Some Other Name')
    assert BuyerOrg.objects.count() == 1 and BuyerLink.objects.count() == 2  # same insurer, two companies sharing
    share(signed_in(other_admin), email='fake.falcon@gmail.com', name='Falcon Risk')
    assert BuyerOrg.objects.filter(domain='fake.falcon@gmail.com').exists()  # a free-mail address is its own buyer


def test_rules(company, admin_user, member_user, signed_in):
    assert share(signed_in(member_user)).status_code == 403
    api = signed_in(admin_user)
    assert share(api, email='deal@buyerco.com', name='BuyerCo', kind='acquirer').status_code == 400  # needs an end date
    assert share(api, email=admin_user.email).status_code == 400  # a client user is not an insurer
    assert share(api, email='deal@buyerco.com', name='BuyerCo', kind='acquirer', endsOn='2099-12-31').status_code == 201


def test_the_database_shows_a_buyer_only_its_links_and_no_client_rows(company, other_company, admin_user, other_admin, signed_in):
    share(signed_in(admin_user))
    share(signed_in(other_admin), email='x@otherinsurer.com', name='Other Insurer')
    ContactEvent.objects.create(client=company, phone_token='p', phone_token_kid='k', source_system='t', source_record_id='r',
                                source_grade='B', channel='call', direction='outbound', occurred_at='2026-10-01T00:00:00Z')
    falcon = BuyerOrg.objects.get(domain='falconrisk.com')
    with buyer(falcon):
        assert [link.client_id for link in BuyerLink.objects.all()] == [company.pk]
        assert ContactEvent.objects.count() == 0 and ConsentResult.objects.count() == 0 and BuyerInvite.objects.count() == 0
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM contact_event')
            assert c.fetchone()[0] == 0


def test_stop_sharing_and_blocking(company, admin_user, signed_in):
    api = signed_in(admin_user)
    link = share(api).json()
    stopped = api.call('post', f"/api/buyer-links/{link['id']}/revoke").json()
    assert stopped['active'] is False and stopped['stoppedOn']
    org = BuyerOrg.objects.get()
    org.is_active = False
    org.save()
    assert share(api).status_code == 400  # blocked by CiV


def test_the_invite_link_opens_for_someone_not_signed_in(company, admin_user, signed_in):
    """The tests normally see every company; a real visitor with the link has no scope at all."""
    from django.test import Client as Browser

    from apps.tenancy.scope import _scope
    share(signed_in(admin_user))
    token = token_from_mail()
    with _scope('', ''):
        b = Browser()
        assert b.get(f'/api/invites/check?token={token}').json()['clientName'] == 'Falcon Risk'
        assert b.post('/api/invites/accept', {'token': token, 'password': PASSWORD}, content_type='application/json').json()['view'] == 'underwriter'


def test_an_insurer_with_an_account_gets_a_confirmation_email(company, other_company, admin_user, other_admin, signed_in):
    """Owner decision 2026-10-22: no second invitation, but an email that one more company now shares with them."""
    from django.test import Client as Browser
    share(signed_in(admin_user))
    token = token_from_mail()
    Browser().post('/api/invites/accept', {'token': token, 'password': PASSWORD}, content_type='application/json')
    mail.outbox.clear()
    made = share(signed_in(other_admin), email='j.merchant@falconrisk.com').json()
    assert made['invited'] is False and len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ['j.merchant@falconrisk.com'] and other_company.name in sent.subject and 'invite=' not in sent.body
    assert '/sign-in' in sent.body and 'Portfolio' in sent.body
