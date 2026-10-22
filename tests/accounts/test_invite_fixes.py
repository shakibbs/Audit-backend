"""Owner, 2026-10-23: expired invites stay listed with Resend; a waiting invite is never replaced silently (portal and
staff panel); the email says "as a Member and the company's lawyer"."""
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import Invite

pytestmark = pytest.mark.django_db


def invite(api, **more):
    return api.call('post', '/api/users', {'name': 'Sam Lee', 'email': 'sam@sunpath.com', 'role': 'member', 'isCounsel': False, **more})


def test_a_waiting_invite_is_not_replaced_silently(company, admin_user, signed_in, api):
    signed_in(admin_user)
    assert invite(api, isCounsel=True).status_code == 201
    again = invite(api)
    assert again.status_code == 400 and 'already has an invite' in again.json()['detail']
    assert Invite.objects.get().is_counsel  # the lawyer tick is kept
    assert len(mail.outbox) == 1


def test_expired_invites_stay_listed_and_can_be_resent(company, admin_user, signed_in, api):
    signed_in(admin_user)
    invite(api)
    Invite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    row = next(u for u in api.call('get', '/api/users').json() if u['email'] == 'sam@sunpath.com')
    assert row['status'] == 'expired'
    old = Invite.objects.get().token_hash
    sent = api.call('post', f"/api/users/{row['id']}/resend")
    assert sent.status_code == 200 and sent.json()['status'] == 'invited'
    assert Invite.objects.get().token_hash != old and len(mail.outbox) == 2
    assert invite(api).status_code == 400  # now waiting again: still not replaced


def test_an_expired_invite_can_be_replaced_by_a_new_one(company, admin_user, signed_in, api):
    signed_in(admin_user)
    invite(api)
    Invite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert invite(api, isCounsel=True).status_code == 201 and Invite.objects.get().is_counsel


def test_the_email_wording(company, admin_user, signed_in, api):
    signed_in(admin_user)
    invite(api, isCounsel=True)
    assert "as a Member and the company's lawyer" in mail.outbox[0].body


def test_only_the_admin_resends(company, admin_user, member_user, signed_in, api):
    signed_in(admin_user)
    invite(api)
    row = next(u for u in api.call('get', '/api/users').json() if u['email'] == 'sam@sunpath.com')
    signed_in(member_user)
    assert api.call('post', f"/api/users/{row['id']}/resend").status_code == 403
