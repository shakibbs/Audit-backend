import re

import pytest
from django.core import mail

from tests.conftest import PASSWORD

NEW = 'a-brand-new-password-2'


def link_from(message) -> str:
    return re.search(r'reset=([\w\-]+\.[\w\-]+)', message.body).group(1)


def staff_link(user):
    """The link CiV staff send with "Send password link" (the only way since "Forgot password" was removed)."""
    from apps.accounts.emails import send_reset
    from apps.accounts.tokens import encode_uid, reset_tokens
    send_reset(user, encode_uid(user.pk), reset_tokens.make_token(user))


@pytest.mark.django_db
def test_the_old_forgot_password_address_is_gone(api, admin_user):
    """Owner, 2026-10-23: nobody can ask the server for a reset email any more."""
    assert api.call('post', '/api/session/reset', {'email': admin_user.email}).status_code == 404
    assert not mail.outbox


@pytest.mark.django_db
def test_reset_link_sets_a_new_password_once(api, admin_user):
    staff_link(admin_user)
    link = link_from(mail.outbox[0])
    assert api.call('post', '/api/session/reset/confirm', {'link': link, 'password': NEW}).status_code == 200
    assert api.call('post', '/api/session/sign-in', {'email': admin_user.email, 'password': NEW}).status_code == 200
    again = api.call('post', '/api/session/reset/confirm', {'link': link, 'password': 'another-password-3'})
    assert again.status_code == 400


@pytest.mark.django_db
def test_reset_refuses_a_weak_password(api, admin_user):
    staff_link(admin_user)
    response = api.call('post', '/api/session/reset/confirm', {'link': link_from(mail.outbox[0]), 'password': 'short'})
    assert response.status_code == 400
    admin_user.refresh_from_db()
    assert admin_user.check_password(PASSWORD)


@pytest.mark.django_db
def test_made_up_link_is_refused(api):
    assert api.call('post', '/api/session/reset/confirm', {'link': 'MQ.fake-token', 'password': NEW}).status_code == 400
