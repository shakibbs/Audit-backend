"""Failed sign-in counter: 5 failures for one email within 15 minutes locks it for 15 minutes."""
from datetime import timedelta

from django.utils import timezone

from apps.access_log.models import AccessEntry

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)


def is_locked(email: str) -> bool:
    since = timezone.now() - WINDOW
    return AccessEntry.objects.filter(action='sign_in_failed', object=email, at__gte=since).count() >= MAX_FAILURES
