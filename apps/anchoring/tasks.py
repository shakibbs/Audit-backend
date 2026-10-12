from celery import shared_task

from apps.tenancy.scope import all_clients

from .models import MerkleAnchor
from .seal import seal_finished_days, stamp


@shared_task
def seal_nightly() -> int:
    return len(seal_finished_days())


@shared_task
def stamp_missing() -> None:
    """Retries outside stamps that failed (a service was down)."""
    with all_clients():
        for anchor in MerkleAnchor.objects.filter(tsa_response__isnull=True) | MerkleAnchor.objects.filter(ots_proof__isnull=True):
            stamp(anchor)
