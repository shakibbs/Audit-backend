"""One batch of records from one tool: fingerprint, phone codes, hand-off, then drop. Each record once only."""
import hashlib

from django.utils import timezone

from apps.keyring.tokens import Tokenizer
from apps.ledger.models import Fingerprint
from apps.ledger.record import LedgerJob

from .connector import Record
from . import handoff
from .handoff import deliver
from .models import SyncCursor, SyncGap


def process(job: LedgerJob, cursor: SyncCursor, records: list[Record], found_by: str, codes: Tokenizer) -> int:
    """Returns how many were new. A record already seen with the same content is skipped (no double counting).
    Found by the catch-up or full check on a live tool = a gap: the live feed missed it."""
    client, connection = cursor.client, cursor.connection
    if found_by == 'full_sweep':
        for receiver in handoff.SEEN:
            receiver(client, connection, [r.source_record_id for r in records])
    seen = set(Fingerprint.objects.filter(client=client, source_system=cursor.source_system,
                                          source_record_id__in=[r.source_record_id for r in records]).values_list('source_record_id', 'sha256'))
    # A gap is a record never seen at all: a live notice and the API may describe the same record in different bytes.
    seen_ids = {record_id for record_id, _ in seen}
    new = 0
    for record in records:
        if (record.source_record_id, hashlib.sha256(record.raw).hexdigest()) in seen:
            continue  # read again, unchanged: already processed
        fp = job.record(source_system=cursor.source_system, source_record_id=record.source_record_id, raw=record.raw,
                        content_kind=record.content_kind, source_grade=connection_grade(connection))
        seen.add((record.source_record_id, fp.sha256))
        was_seen = record.source_record_id in seen_ids
        seen_ids.add(record.source_record_id)
        deliver(client, connection, record, [t for t in map(codes.token, record.phones) if t])
        if found_by != 'live' and cursor.mode == SyncCursor.Mode.LIVE and not was_seen:
            SyncGap.objects.create(client=client, source_system=cursor.source_system, source_record_id=record.source_record_id,
                                   sha256=fp.sha256, found_by=found_by, changed_at=record.changed_at,
                                   delay_seconds=max(0, int((timezone.now() - record.changed_at).total_seconds())))
        new += 1
    cursor.records_delivered += new
    return new


def connection_grade(connection) -> str:
    from .connector import CONNECTORS
    cls = CONNECTORS.get(connection.provider)
    return cls.source_grade if cls else 'C'
