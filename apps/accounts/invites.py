"""One way to invite a person to a client company: used by the client's Admin in the portal (Users & Access) and by
CiV staff in the admin panel (a new client's Admin, or anyone on the client's Invites tab). The person gets a link
(7 days, one use) and chooses their own password; only a hash of the link is kept."""
from django.db import transaction
from django.utils import timezone

from apps.accounts.emails import send_invite
from apps.accounts.models import ClientUser, Invite
from apps.accounts.tokens import INVITE_LIFETIME, new_invite_token


def taken(email: str) -> bool:
    from apps.buyers.models import BuyerUser
    email = email.strip().lower()
    return ClientUser.objects.filter(email__iexact=email).exists() or BuyerUser.objects.filter(email=email).exists()


def invite(client, *, email: str, name: str = '', role: str, is_counsel: bool = False, by: ClientUser | None = None) -> Invite:
    """Raises ValueError when the email already has an account. A new invite replaces an older open one."""
    email = email.strip().lower()
    if taken(email):
        raise ValueError('That email already has an account.')
    waiting = client.invites.filter(email=email, used_at__isnull=True, expires_at__gt=timezone.now()).first()
    if waiting:  # never replace a waiting invite silently (owner, 2026-10-23)
        raise ValueError(f'{email} already has an invite (sent {waiting.sent_at:%-d %b}). Use Resend, or Cancel it and invite again.')
    token, token_hash = new_invite_token()
    with transaction.atomic():
        client.invites.filter(email=email, used_at__isnull=True).delete()
        made = Invite.objects.create(client=client, email=email, name=name.strip(), role=role, is_counsel=is_counsel, invited_by=by,
                                     token_hash=token_hash, expires_at=timezone.now() + INVITE_LIFETIME)
    send_invite(made, token)
    return made


def resend(old: Invite) -> Invite:
    """A fresh link for 7 more days; the old link stops working."""
    if old.used_at:
        raise ValueError('This person has already joined.')
    token, token_hash = new_invite_token()
    now = timezone.now()
    Invite.objects.filter(pk=old.pk).update(token_hash=token_hash, sent_at=now, expires_at=now + INVITE_LIFETIME)
    old.refresh_from_db()
    send_invite(old, token)
    return old


def state(i: Invite) -> str:
    return 'Joined' if i.used_at else 'Expired' if i.expires_at <= timezone.now() else 'Sent'
