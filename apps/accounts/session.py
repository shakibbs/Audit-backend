"""Puts a client user into, or takes them out of, the browser session.

Uses its own session keys, so a CiV staff login in the same browser never counts here.
"""
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.accounts.models import ClientUser

USER_KEY = 'civ_client_user_id'
HASH_KEY = 'civ_client_auth_hash'


# Every portal key: a client user's and an insurer's (apps/buyers/session.py). Only one portal person per browser
# (owner, 2026-10-23); the CiV staff panel keeps its own login and is never touched here.
PORTAL_KEYS = (USER_KEY, HASH_KEY, 'civ_buyer_user_id', 'civ_buyer_auth_hash')


def clear_portal(request) -> None:
    """Empties every portal key, so nobody stays signed in behind the next person."""
    for key in PORTAL_KEYS:
        request.session.pop(key, None)


def sign_in(request, user: ClientUser) -> None:
    clear_portal(request)
    request.session.cycle_key()  # new session id at sign-in, against session fixation
    request.session[USER_KEY] = user.pk
    request.session[HASH_KEY] = user.get_session_auth_hash()
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])


def sign_out(request) -> None:
    clear_portal(request)
    request.session.cycle_key()


def current_user(request) -> ClientUser | None:
    """The signed-in client user, or None. A changed password ends old sessions."""
    user_id = request.session.get(USER_KEY)
    if user_id is None:
        return None
    user = ClientUser.objects.select_related('client').filter(pk=user_id, is_active=True, client__is_active=True).first()
    if user is None or not constant_time_compare(request.session.get(HASH_KEY, ''), user.get_session_auth_hash()):
        return None
    return user
