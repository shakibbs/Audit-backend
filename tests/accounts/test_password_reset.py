import re

import pytest
from django.core import mail

from tests.conftest import PASSWORD

NEW = 'a-brand-new-password-2'


def link_from(message) -> str:
    return re.search(r'reset=([\w\-]+\.[\w\-]+)', message.body).group(1)


@pytest.mark.django_db
def test_reset_answers_sent_for_any_email(api, admin_user):
    for email in (admin_user.email, 'nobody@nowhere.com'):
        assert api.call('post', '/api/session/reset', {'email': email}).json() == {'sent': True}
    assert len(mail.outbox) == 1  # only the real account got an email


@pytest.mark.django_db
def test_reset_link_sets_a_new_password_once(api, admin_user):
    api.call('post', '/api/session/reset', {'email': admin_user.email})
    link = link_from(mail.outbox[0])
    assert api.call('post', '/api/session/reset/confirm', {'link': link, 'password': NEW}).status_code == 200
    assert api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': NEW}).status_code == 200
    again = api.call('post', '/api/session/reset/confirm', {'link': link, 'password': 'another-password-3'})
    assert again.status_code == 400


@pytest.mark.django_db
def test_reset_refuses_a_weak_password(api, admin_user):
    api.call('post', '/api/session/reset', {'email': admin_user.email})
    response = api.call('post', '/api/session/reset/confirm', {'link': link_from(mail.outbox[0]), 'password': 'short'})
    assert response.status_code == 400
    admin_user.refresh_from_db()
    assert admin_user.check_password(PASSWORD)


@pytest.mark.django_db
def test_made_up_link_is_refused(api):
    assert api.call('post', '/api/session/reset/confirm', {'link': 'MQ.fake-token', 'password': NEW}).status_code == 400
