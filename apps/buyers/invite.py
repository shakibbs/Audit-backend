"""Module 15 step 1: a client invites its insurer or acquirer (owner decision 2026-10-22). The buyer is found by the
email's domain (created the first time), the company starts sharing with it at once, and a person with no account yet
gets an invite link (7 days) to set a password. Emails are not delivered yet (console), like client invites."""
from django.conf import settings
from django.core.mail import send_mail
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
    link = f'{settings.PORTAL_URL}/sign-in?invite={token}'
    send_mail(f'{invite.client.name} shares its CiV risk attestation with you',
              f'Hello {invite.name or ""},\n\n{invite.client.name} has shared its Comply iV risk attestation with {invite.org.name}.\n'
              f'Use this link within 7 days to choose your password:\n{link}', None, [invite.email])

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

