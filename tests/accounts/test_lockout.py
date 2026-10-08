import pytest

from tests.conftest import PASSWORD


@pytest.mark.django_db
def test_five_wrong_tries_lock_the_email(api, admin_user):
    for _ in range(5):
        assert api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': 'wrong-wrong-1'}).status_code == 400
    locked = api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': PASSWORD})
    assert locked.status_code == 429
    assert 'Wait 15 minutes' in locked.json()['detail']
