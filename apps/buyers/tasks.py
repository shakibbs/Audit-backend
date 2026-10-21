from celery import shared_task

from apps.tenancy.scope import all_clients


@shared_task
def monthly_rating_sends() -> int:
    """The 6th: each insurer with "send every month" gets last month's locked sheets (Module 15)."""
    from .rating import send_monthly
    with all_clients():
        return send_monthly()
