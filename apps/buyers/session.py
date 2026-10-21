"""Puts a buyer user into, or takes them out of, the browser session (its own keys: never a client or staff login)."""
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from .models import BuyerUser

USER_KEY = 'civ_buyer_user_id'
HASH_KEY = 'civ_buyer_auth_hash'


def sign_in(request, user: BuyerUser) -> None:
    request.session.cycle_key()
    request.session[USER_KEY] = user.pk
    request.session[HASH_KEY] = user.get_session_auth_hash()
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])


def sign_out(request) -> None:
    request.session.pop(USER_KEY, None)
    request.session.pop(HASH_KEY, None)


def current_buyer(request) -> BuyerUser | None:
    user_id = request.session.get(USER_KEY)
    if user_id is None:
        return None
    user = BuyerUser.objects.select_related('org').filter(pk=user_id, is_active=True, org__is_active=True).first()
    if user is None or not constant_time_compare(request.session.get(HASH_KEY, ''), user.get_session_auth_hash()):
        return None
    return user


def session_data(user: BuyerUser) -> dict:
    """What the portal learns about a signed-in buyer: it always opens the underwriter view."""
    initials = ''.join(p[0] for p in user.name.split()[:2]).upper()
    return {'signedIn': True, 'userId': f'b-{user.pk}', 'name': user.name, 'initials': initials, 'email': user.email,
            'role': 'member', 'isCounsel': False, 'view': 'underwriter', 'orgKind': user.org.kind, 'orgName': user.org.name,
            'clientId': '', 'clientName': user.org.name, 'vertical': user.org.get_kind_display(), 'sampleData': False}
