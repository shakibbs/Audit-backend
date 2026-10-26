"""Super test 2026-10-23 (owner: one portal person per browser): signing in empties every portal key, so a client
signing in after an insurer (or the other way round) never leaves the first person signed in behind them, and
signing out always leaves nobody."""
import pytest

from apps.tenancy.scope import _scope
from tests.buyers.test_security import insurer
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def post(b, path, body=None):
    return b.post(path, body or {}, content_type='application/json')


def test_insurer_then_client_then_sign_out_leaves_nobody(company, admin_user, member_user, signed_in):
    b = insurer(company, admin_user, signed_in)
    with _scope('', ''):
        assert b.get('/api/session').json()['view'] == 'underwriter'
        assert post(b, '/api/session/sign-in', {'email': member_user.email, 'password': PASSWORD}).json()['email'] == member_user.email
        assert b.get('/api/session').json()['email'] == member_user.email  # the insurer is gone
        assert post(b, '/api/session/sign-out').json() == {'signedIn': False}
        assert b.get('/api/session').json() == {'signedIn': False}
        assert b.get('/api/insureds').status_code in (401, 403)


def test_client_then_insurer_acts_as_the_insurer_only(company, admin_user, member_user, signed_in):
    b = insurer(company, admin_user, signed_in)  # makes the insurer's account
    with _scope('', ''):
        post(b, '/api/session/sign-out')
        post(b, '/api/session/sign-in', {'email': member_user.email, 'password': PASSWORD})
        reply = post(b, '/api/session/sign-in', {'email': 'a.lee@falconrisk.com', 'password': PASSWORD})
        assert reply.json()['view'] == 'underwriter'
        assert b.get('/api/contacts').status_code in (401, 403)  # the member's key went with the new sign-in
        assert post(b, '/api/session/sign-out').json() == {'signedIn': False}
        assert b.get('/api/session').json() == {'signedIn': False}
