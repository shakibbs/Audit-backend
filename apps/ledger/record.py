"""ledger_job(): the one way a job writes fingerprints. Hash the exact bytes read; on failure, remove everything it wrote."""
import hashlib
import uuid
from contextlib import contextmanager

from django.utils import timezone

from apps.tenancy.scope import tenant

from .models import Fingerprint, PurgeLog


class LedgerJob:
    def __init__(self, client, name: str):
        self.client = client
        self.name = name
        self.id = uuid.uuid4()

    def record(self, *, source_system: str, source_record_id: str, raw: bytes, content_kind: str, source_grade: str) -> Fingerprint:
        """Fingerprint one record as it arrived. `raw` is the response bytes, never a re-built copy; it is not kept."""
        if not isinstance(raw, bytes):
            raise TypeError('Fingerprint the raw bytes as received, not a re-built copy.')
        return Fingerprint.objects.create(
            client=self.client, job_id=self.id, source_system=source_system, source_record_id=str(source_record_id),
            content_kind=content_kind, source_grade=source_grade,
            sha256=hashlib.sha256(raw).hexdigest(), fetched_at=timezone.now(),
        )


@contextmanager
def ledger_job(client, name: str):
    """with ledger_job(client, 'twilio sync') as job: job.record(...). A failed job leaves no rows, and one purge log line."""
    job = LedgerJob(client, name)
    with tenant(client):  # the job sees and writes this client's rows only
        try:
            yield job
        except BaseException as error:
            removed, _ = Fingerprint.objects.filter(job_id=job.id).delete()
            PurgeLog.objects.create(client=client, job_id=job.id, job_name=name, rows_removed=removed, reason=type(error).__name__)
            raise
