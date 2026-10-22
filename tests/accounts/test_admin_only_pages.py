"""Owner decision 2026-10-23: Users & Access and Settings are for the company's Admin only. Members and lawyers are
refused by the server (not just hidden); they still get people's names to assign a finding to someone."""
import pytest

pytestmark = pytest.mark.django_db
ADMIN_ONLY = ('/api/access-log', '/api/settings', '/api/buyer-links')


def test_a_member_and_a_lawyer_are_refused(company, member_user, signed_in, api):
    for lawyer in (False, True):
        member_user.is_counsel = lawyer
        member_user.save()
        signed_in(member_user)
        for path in ADMIN_ONLY:
            assert api.call('get', path).status_code == 403, path
        people = api.call('get', '/api/users').json()
        assert people and all(set(p) == {'id', 'name', 'role', 'isCounsel', 'status'} for p in people)  # names only, no emails


def test_the_admin_sees_everything(company, admin_user, signed_in, api):
    signed_in(admin_user)
    for path in ADMIN_ONLY:
        assert api.call('get', path).status_code == 200, path
    assert 'email' in api.call('get', '/api/users').json()[0]
