import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import ClientUser, Invite

NEW = 'a-brand-new-password-2'


def token_from(message) -> str:
    return re.search(r'invite=([\w\-]+)', message.body).group(1)


@pytest.mark.django_db
def test_admin_invites_and_person_accepts(signed_in, admin_user, client):
    api = signed_in(admin_user)
    sent = api.call('post', '/api/users', {'email': 'New@SunPath.com', 'name': 'Nia New', 'role': 'member', 'isCounsel': True})
    assert sent.status_code == 201 and sent.json()['status'] == 'invited'
    token = token_from(mail.outbox[0])
    assert Invite.objects.get().token_hash != token  # only the hash is stored

    assert client.get(f'/api/invites/check?token={token}').json()['clientName'] == 'SunPath Residential Solar'
    accepted = client.post('/api/invites/accept', {'token': token, 'password': NEW}, content_type='application/json')
    assert accepted.status_code == 200 and accepted.json()['name'] == 'Nia New'
    user = ClientUser.objects.get(email='new@sunpath.com')
    assert user.client == admin_user.client and user.is_counsel and user.role == 'member'
    again = client.post('/api/invites/accept', {'token': token, 'password': NEW}, content_type='application/json')
    assert again.status_code == 400


@pytest.mark.django_db
def test_expired_invite_is_refused(signed_in, admin_user, client):
    signed_in(admin_user).call('post', '/api/users', {'email': 'late@sunpath.com'})
    Invite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    response = client.post('/api/invites/accept', {'token': token_from(mail.outbox[0]), 'password': NEW}, content_type='application/json')
    assert response.status_code == 400


@pytest.mark.django_db
def test_member_cannot_invite(signed_in, member_user):
    assert signed_in(member_user).call('post', '/api/users', {'email': 'x@sunpath.com'}).status_code == 403


@pytest.mark.django_db
def test_cannot_invite_an_existing_account(signed_in, admin_user, other_admin):
    assert signed_in(admin_user).call('post', '/api/users', {'email': other_admin.email}).status_code == 400
