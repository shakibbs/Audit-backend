"""Shared test data: two client companies, each with an admin and a member."""
import datetime

import pytest

from apps.accounts.models import ClientUser, Role
from apps.clients.models import Client

PASSWORD = 'a-long-test-password-1'


@pytest.fixture
def company():
    return Client.objects.create(name='SunPath Residential Solar', start_date=datetime.date(2026, 6, 1))


@pytest.fixture
def other_company():
    return Client.objects.create(name='Ridgeline HVAC', start_date=datetime.date(2026, 6, 1))


@pytest.fixture
def admin_user(company):
    return ClientUser.objects.create_user(client=company, email='dana@sunpath.com', name='Dana Reyes', password=PASSWORD, role=Role.ADMIN)


@pytest.fixture
def member_user(company):
    return ClientUser.objects.create_user(client=company, email='sam@sunpath.com', name='Sam Lee', password=PASSWORD)


@pytest.fixture
def other_admin(other_company):
    return ClientUser.objects.create_user(client=other_company, email='kim@ridgeline.com', name='Kim Park', password=PASSWORD, role=Role.ADMIN)


@pytest.fixture
def api():
    """A browser-like client that must send the CSRF token, like the real portal."""
    from django.test import Client as BrowserClient

    browser = BrowserClient(enforce_csrf_checks=True)

    def call(method, path, body=None):
        if 'csrftoken' not in browser.cookies:
            browser.get('/api/session')
        token = browser.cookies['csrftoken'].value
        return getattr(browser, method)(path, body or {}, content_type='application/json', HTTP_X_CSRFTOKEN=token)

    browser.call = call
    return browser


@pytest.fixture
def signed_in(api):
    """Returns a function that signs a user into the api client."""
    def sign_in(user):
        response = api.call('post', '/api/session/sign-in', {'email': user.email, 'password': PASSWORD})
        assert response.status_code == 200, response.json()
        return api
    return sign_in
