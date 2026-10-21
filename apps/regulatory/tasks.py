from celery import shared_task

from .watcher import refresh


@shared_task
def watch_laws() -> int:
    """Daily: new calling-law items from the Federal Register (shown to CiV staff in the admin panel)."""
    return refresh()
