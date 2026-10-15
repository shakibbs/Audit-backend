from celery import shared_task

from .claim import claim_due


@shared_task
def claim_certificates() -> int:
    return claim_due()
