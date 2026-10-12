from celery import shared_task
from django.utils import timezone

from .models import Heartbeat


@shared_task
def heartbeat() -> None:
    """Runs every minute on a worker: proves the clock and the workers are both alive."""
    Heartbeat.objects.update_or_create(name='workers', defaults={'seen_at': timezone.now()})
