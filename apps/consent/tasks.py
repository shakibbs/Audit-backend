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


@shared_task
def keep_results_up_to_date() -> int:
    """Every minute: queued rechecks, then pending results whose certificate was read."""
    from .keeping import recheck_pending, run_rechecks
    with all_clients():
        return run_rechecks() + recheck_pending()


@shared_task
def recheck_time_passed() -> int:
    from .keeping import recheck_time_passed as nightly
    with all_clients():
        return nightly()
