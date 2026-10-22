"""Failed sign-in counter: 5 failures for one email within 15 minutes locks it for 15 minutes. The portal counts
"sign_in_failed"; the staff panel counts "staff_sign_in_failed" (owner, 2026-10-23)."""
from datetime import timedelta

from django.utils import timezone

from apps.access_log.models import AccessEntry

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)


def is_locked(email: str, action: str = 'sign_in_failed') -> bool:
    since = timezone.now() - WINDOW
    return AccessEntry.objects.filter(action=action, object=email, at__gte=since).count() >= MAX_FAILURES
