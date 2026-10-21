from celery import shared_task

from apps.tenancy.scope import all_clients, tenant


@shared_task
def read_documents() -> int:
    """Every 15 minutes: queue new documents for each company, then read waiting ones if an AI is plugged in."""
    from apps.clients.models import Client

    from .read import queue, read_waiting
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            queue(client)
    with all_clients():
        return read_waiting()


@shared_task
def run_doc_exams() -> int:
    """Daily: re-run a feature's exam when the AI or its instructions changed, or 30 days passed; apply after a pass."""
    from . import ai, exam
    from .features import FEATURES
    from .read import apply_trusted
    reader = ai.active()
    if reader is None:
        return 0
    ran = 0
    with all_clients():
        for name in FEATURES:
            if exam.due(name, reader):
                if exam.run(name, reader).passed:
                    apply_trusted(name, reader)
                ran += 1
    return ran
