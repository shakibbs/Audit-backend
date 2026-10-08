import pytest

from apps.access_log.models import AccessEntry
from tests.conftest import PASSWORD


@pytest.mark.django_db
def test_not_signed_in_session(api):
    assert api.get('/api/session').json() == {'signedIn': False}


@pytest.mark.django_db
def test_sign_in_returns_user_and_company(api, admin_user):
    response = api.call('post', '/api/session/sign-in', {'email': 'DANA@sunpath.com', 'password': PASSWORD})
    assert response.status_code == 200
    body = api.get('/api/session').json()
    assert body['signedIn'] is True
    assert body['name'] == 'Dana Reyes' and body['initials'] == 'DR'
    assert body['role'] == 'admin'
    assert body['clientName'] == 'SunPath Residential Solar'
    assert body['engagementMode'] == 'counsel_directed'
    assert AccessEntry.objects.filter(action='sign_in', actor_id=admin_user.pk).exists()


@pytest.mark.django_db
def test_wrong_password_and_unknown_email_get_the_same_answer(api, admin_user):
    wrong = api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': 'not-the-password'})
    unknown = api.call('post', '/api/session/sign-in', {'email': 'nobody@nowhere.com', 'password': 'whatever-1234'})
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json()
    assert AccessEntry.objects.filter(action='sign_in_failed').count() == 2


@pytest.mark.django_db
def test_turned_off_user_or_company_cannot_sign_in(api, admin_user):
    admin_user.client.is_active = False
    admin_user.client.save()
    response = api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': PASSWORD})
    assert response.status_code == 400


@pytest.mark.django_db
def test_sign_in_without_csrf_token_is_refused(admin_user):
    from django.test import Client as BrowserClient
    browser = BrowserClient(enforce_csrf_checks=True)
    response = browser.post('/api/session/sign-in', {'email': admin_user.email, 'password': PASSWORD}, content_type='application/json')
    assert response.status_code == 403


@pytest.mark.django_db
def test_sign_out(signed_in, admin_user):
    api = signed_in(admin_user)
    assert api.call('post', '/api/session/sign-out').status_code == 200
    assert api.get('/api/session').json() == {'signedIn': False}
    assert AccessEntry.objects.filter(action='sign_out').exists()


@pytest.mark.django_db
def test_changing_password_ends_old_sessions(signed_in, admin_user):
    api = signed_in(admin_user)
    admin_user.set_password('a-brand-new-password-2')
    admin_user.save()
    assert api.get('/api/session').json() == {'signedIn': False}
