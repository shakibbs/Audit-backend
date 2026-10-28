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
def share(client, by: str, name: str, email: str, kind: str, ends_on, person: str = '') -> tuple[BuyerLink, bool, str]:
    """(the link, whether an invite was sent, what happened in plain words). Raises ValueError with a message for the
    client. An insurer CiV already knows (by the email's domain) keeps its name and kind: the answer says so instead of
    ignoring what was typed (QA 2026-10-23)."""
    email = email.lower().strip()
    if '@' not in email:
        raise ValueError("Enter the underwriter's email.")
    if ClientUser.objects.filter(email__iexact=email).exists():
        raise ValueError('That email belongs to a client user, not an insurer.')
    person_user = BuyerUser.objects.select_related('org').filter(email=email).first()
    org = person_user.org if person_user else BuyerOrg.objects.filter(domain=domain_of(email)).first()
    notes = []
    if org is not None:
        if org.kind != kind:
            raise ValueError(f'{org.name} is set up on CiV as {"an acquirer" if org.kind == BuyerOrg.Kind.ACQUIRER else "an insurer"}, '
                             f'not {"an acquirer" if kind == BuyerOrg.Kind.ACQUIRER else "an insurer"}. Choose "{org.get_kind_display()}".')
        typed = ' '.join(name.split())
        if typed and typed.lower() != org.name.lower():
            notes.append(f'That email belongs to {org.name} on CiV, so "{typed}" is not used.')
    if org is None:
        if not name.strip():
            raise ValueError("Enter the insurer's company name.")
        org = BuyerOrg.objects.create(name=' '.join(name.split())[:150], domain=domain_of(email), kind=kind)
    if not org.is_active or org.deleted_at:
        raise ValueError('CiV has blocked this insurer. Contact CiV.')
    if org.kind == BuyerOrg.Kind.ACQUIRER and ends_on is None:
        raise ValueError('Sharing with an acquirer needs an end date.')
    today = timezone.localdate()
    current = next((link for link in BuyerLink.objects.filter(client=client, org=org, revoked_at__isnull=True) if link.active(today)), None)
    if current is not None:
        link = current
        if ends_on and ends_on != link.ends_on:  # the end date typed is kept, never dropped
            link.ends_on = ends_on
            link.save(update_fields=['ends_on'])
            notes.append(f'Already sharing with {org.name}. End date changed to {ends_on:%-d %b %Y}.')
        else:
            notes.append(f'Already sharing with {org.name}.')
    else:
        link = BuyerLink.objects.create(org=org, client=client, granted_by=by, ends_on=ends_on)
        notes.append(f'Now sharing with {org.name} ({org.get_kind_display().lower()})' + (f' until {ends_on:%-d %b %Y}.' if ends_on else '.'))
        from .attestation import save
        save(client, today.replace(day=1))  # the insurer sees this month so far at once, not after the nightly run
    invited = False
    if person_user is None:
        token, token_hash = new_invite_token()
        old = BuyerInvite.objects.filter(email=email, used_at__isnull=True).first()
        keep_name = ' '.join(person.split())[:150] or (old.name if old else '')  # sharing again never wipes the name
        BuyerInvite.objects.filter(email=email, used_at__isnull=True).delete()  # a new invite replaces an old one
        invite = BuyerInvite.objects.create(org=org, client=client, email=email, name=keep_name, invited_by=by, token_hash=token_hash,
                                            expires_at=timezone.now() + INVITE_LIFETIME)
        send(invite, token)
        invited = True
        notes.append(f'An invite to choose a password was sent to {email}' + (' (the earlier invite no longer works).' if old else '.'))
    else:
        send_access_notice(person_user, client, link)  # already has a password: a confirmation instead of an invite
        notes.append(f'{person_user.name or email} already has an account and was told by email.')
    return link, invited, ' '.join(notes)

def open_invite(token: str) -> BuyerInvite | None:
    # The person opening the link is not signed in yet, so no scope is set and the locked invite table would show
    # nothing: look it up across companies (the secret token is the key; only its hash is stored).
    with all_clients():
        return BuyerInvite.objects.select_related('org', 'client').filter(token_hash=hash_invite_token(token), used_at__isnull=True,
                                                                          expires_at__gt=timezone.now(), org__is_active=True,
                                                                          org__deleted_at__isnull=True).first()

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
