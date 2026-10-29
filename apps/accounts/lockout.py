"""Failed sign-in counter (owner, 2026-10-30): 5 failures for one email from one computer (internet address) within 15
minutes lock that email on that computer only, so a stranger cannot lock the real person out; 50 failures for one
email from all computers together lock it everywhere (an attack) and the person gets one warning email. Locks last 15
minutes. The portal counts "sign_in_failed" and "wrong_current_password"; the staff panel "staff_sign_in_failed"."""
import logging
from datetime import timedelta

from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.access_log.recorder import client_ip, record

MAX_FAILURES = 5  # from one computer
MAX_EVERYWHERE = 50  # from all computers together
WINDOW = timedelta(minutes=15)
EVERYWHERE = 'account_locked_everywhere'

PORTAL_FAILURES = ('sign_in_failed', 'wrong_current_password')  # My account's wrong current password counts too


def is_locked(email: str, action: str | tuple = PORTAL_FAILURES, request=None) -> bool:
    since = timezone.now() - WINDOW
    actions = (action,) if isinstance(action, str) else action
    failures = AccessEntry.objects.filter(action__in=actions, object=email, at__gte=since)
    if failures.count() >= MAX_EVERYWHERE:
        warn_once(email, staff='staff_sign_in_failed' in actions, request=request)
        return True
    ip = client_ip(request)
    return failures.filter(ip_address=ip).count() >= MAX_FAILURES if ip else failures.count() >= MAX_FAILURES


def locked_emails(actions=PORTAL_FAILURES, now=None) -> set[str]:
    """Emails locked right now on at least one computer (the staff dashboard's count)."""
    failures = AccessEntry.objects.filter(action__in=actions, at__gte=(now or timezone.now()) - WINDOW)
    found = set()
    for email in failures.values_list('object', flat=True).distinct():
        mine = failures.filter(object=email)
        if mine.count() >= MAX_EVERYWHERE or any(mine.filter(ip_address=ip).count() >= MAX_FAILURES
                                                  for ip in mine.values_list('ip_address', flat=True).distinct()):
            found.add(email)
    return found


def warn_once(email: str, *, staff: bool, request=None) -> None:
    """One log line and one email per attack (not again within the 15 minutes)."""
    if AccessEntry.objects.filter(action=EVERYWHERE, object=email, at__gte=timezone.now() - WINDOW).exists():
        return
    person, client_id = owner_of(email, staff)
    record(EVERYWHERE, request=request, actor_kind='anonymous', object=email, client_id=client_id)
    if person is None:
        return  # nobody has this email: nothing to warn
    from apps.accounts.mailer import send
    try:
        send(email, 'Someone tried to sign in to your CiV account', name=person.name or email, heading='Your account is locked for 15 minutes',
             lines=[f'Someone tried {MAX_EVERYWHERE} or more wrong passwords on your CiV {"staff panel" if staff else "portal"} account '
                    'from different computers in the last 15 minutes.',
                    'To protect you, the account is locked for 15 minutes. Your password was not shown or changed. After 15 '
                    'minutes you can sign in as usual.',
                    'If you think someone knows your password, change it once you are signed in.'],
             button='Open CiV', link=sign_in_link(staff),
             note='Nobody at CiV will ever ask you for your password.')
    except Exception:  # a mail problem never stops the lock
        logging.getLogger(__name__).exception('Lock warning email failed for %s', email)


def owner_of(email: str, staff: bool):
    """(the person with this email, their company id) — a CiV staff member, or a client or insurer person."""
    if staff:
        from apps.staff.models import StaffUser
        return StaffUser.objects.filter(email=email, is_active=True).first(), None
    from apps.accounts.models import ClientUser
    from apps.buyers.models import BuyerUser
    user = ClientUser.objects.filter(email=email, is_active=True).first()
    if user is not None:
        return user, user.client_id
    return BuyerUser.objects.filter(email=email, is_active=True).first(), None


def sign_in_link(staff: bool) -> str:
    from django.conf import settings
    return f'{settings.ADMIN_URL}/civ-admin/login/' if staff else f'{settings.PORTAL_URL}/sign-in'
