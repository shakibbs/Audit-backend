from celery import shared_task

from apps.tenancy.scope import all_clients

from .proofs import refresh_certificate_dates


@shared_task
def refresh_proof_dates() -> int:
    with all_clients():
        return refresh_certificate_dates()


@shared_task
def work_out_needs() -> int:
    from .needs import work_out_new
    with all_clients():
        return work_out_new()
