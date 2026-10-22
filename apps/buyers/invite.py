"""Module 15 step 1: a client invites its insurer or acquirer (owner decision 2026-10-22). The buyer is found by the
email's domain (created the first time), the company starts sharing with it at once, and a person with no account yet
gets an invite link (7 days) to set a password. Emails are not delivered yet (console), like client invites."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import ClientUser
from apps.accounts.tokens import INVITE_LIFETIME, hash_invite_token, new_invite_token

from apps.tenancy.scope import all_clients

from .models import BuyerInvite, BuyerLink, BuyerOrg, BuyerUser

FREE_MAIL = {'gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com', 'aol.com', 'icloud.com', 'me.com',
             'proton.me', 'protonmail.com', 'gmx.com', 'mail.com', 'yandex.com', 'zoho.com'}

def domain_of(email: str) -> str:
    """One buyer per company email domain; a free-mail address is its own buyer."""
    email = email.lower().strip()
    domain = email.rpartition('@')[2]
    return email if domain in FREE_MAIL else domain

def send(invite: BuyerInvite, token: str) -> None:
    from apps.accounts.mailer import send as mail
    mail(invite.email, f'{invite.client.name} shares its CiV risk attestation with you', name=invite.name or invite.email,
         heading=f'{invite.client.name} shares its risk attestation',
         lines=[f'{invite.client.name} has shared its Comply iV risk attestation with {invite.org.name}.',
                'Click the button to choose your password and open the insurer view. The link works once, for 7 days.'],
         button='Choose your password', link=f'{settings.PORTAL_URL}/sign-in?invite={token}')


def send_access_notice(user: BuyerUser, client, link: BuyerLink) -> None:
    """An insurer or acquirer who already has an account is told that one more company now shares with them."""
    from apps.accounts.mailer import send as mail
    until = f' until {link.ends_on:%-d %b %Y}' if link.ends_on else ''
    mail(user.email, f'{client.name} now shares its CiV risk attestation with you', name=user.name,
         heading=f'{client.name} now shares with {user.org.name}',
         lines=[f'{client.name} has given {user.org.name} access to its Comply iV risk attestation{until}.',
                'It is in your Portfolio now. Sign in with your email and password to see it.'],
         button='Sign in to see it', link=f'{settings.PORTAL_URL}/sign-in',
         note='If you did not expect this, you can ignore this email; the company can stop sharing at any time.')


@transaction.atomic
def share(client, by: str, name: str, email: str, kind: str, ends_on, person: str = '') -> tuple[BuyerLink, bool]:
    """(the link, whether an invite was sent). Raises ValueError with a message for the client."""
    email = email.lower().strip()
    if '@' not in email:
        raise ValueError("Enter the underwriter's email.")
    if ClientUser.objects.filter(email__iexact=email).exists():
        raise ValueError('That email belongs to a client user, not an insurer.')
    person_user = BuyerUser.objects.select_related('org').filter(email=email).first()
    org = person_user.org if person_user else BuyerOrg.objects.filter(domain=domain_of(email)).first()
    if org is None:
        if not name.strip():
            raise ValueError("Enter the insurer's company name.")
        org = BuyerOrg.objects.create(name=' '.join(name.split())[:150], domain=domain_of(email), kind=kind)
    if not org.is_active:
        raise ValueError('CiV has blocked this insurer. Contact CiV.')
    if org.kind == BuyerOrg.Kind.ACQUIRER and ends_on is None:
        raise ValueError('Sharing with an acquirer needs an end date.')
    today = timezone.localdate()
    if any(link.active(today) for link in BuyerLink.objects.filter(client=client, org=org)):
        link = BuyerLink.objects.filter(client=client, org=org, revoked_at__isnull=True).first()
    else:
        link = BuyerLink.objects.create(org=org, client=client, granted_by=by, ends_on=ends_on)
        from .attestation import save
        save(client, today.replace(day=1))  # the insurer sees this month so far at once, not after the nightly run
    invited = False
    if person_user is None:
        token, token_hash = new_invite_token()
        BuyerInvite.objects.filter(email=email, used_at__isnull=True).delete()  # a new invite replaces an old one
        invite = BuyerInvite.objects.create(org=org, client=client, email=email, name=person[:150], invited_by=by, token_hash=token_hash,
                                            expires_at=timezone.now() + INVITE_LIFETIME)
        send(invite, token)
        invited = True
    else:
        send_access_notice(person_user, client, link)  # already has a password: a confirmation instead of an invite
    return link, invited

def open_invite(token: str) -> BuyerInvite | None:
    # The person opening the link is not signed in yet, so no scope is set and the locked invite table would show
    # nothing: look it up across companies (the secret token is the key; only its hash is stored).
    with all_clients():
        return BuyerInvite.objects.select_related('org', 'client').filter(token_hash=hash_invite_token(token), used_at__isnull=True,
                                                                          expires_at__gt=timezone.now(), org__is_active=True).first()

def accept(invite: BuyerInvite, password: str) -> BuyerUser:
    with all_clients(), transaction.atomic():
        user = BuyerUser.objects.create_user(org=invite.org, email=invite.email, name=invite.name or invite.email, password=password)
        invite.used_at = timezone.now()
        invite.save(update_fields=['used_at'])
    return user



def send_password_link(user: BuyerUser) -> None:
    """CiV staff send an insurer or acquirer person a link (1 hour) to choose a new password. The link starts with "b-"
    so the portal's new-password page knows it is a buyer account."""
    from apps.accounts.mailer import send as mail
    from apps.accounts.tokens import buyer_reset_tokens, encode_uid
    link = f'{settings.PORTAL_URL}/sign-in?reset=b-{encode_uid(user.pk)}.{buyer_reset_tokens.make_token(user)}'
    mail(user.email, 'Choose a new CiV password', name=user.name, heading='Choose a new password',
         lines=['CiV sent you this link to choose a new password for the insurer view. It works for 1 hour.'],
         button='Choose a new password', link=link, note='If you did not ask for this, you can ignore this email; your password stays the same.')


def resend(invite: BuyerInvite) -> BuyerInvite:
    """A fresh 7-day link for an insurer person who has not joined yet; the old link stops working."""
    token, token_hash = new_invite_token()
    now = timezone.now()
    BuyerInvite.objects.filter(pk=invite.pk).update(token_hash=token_hash, sent_at=now, expires_at=now + INVITE_LIFETIME)
    invite.refresh_from_db()
    send(invite, token)
    return invite
