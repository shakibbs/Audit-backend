"""Where a read record goes next. Module 4 (the normalizer) plugs in here; until then records are only counted.
Whatever receives them gets the record in memory and must not keep its content."""
from apps.sync.connector import Record

RECEIVERS: list = []  # callables (client, connection, record, phone_tokens) → None
SEEN: list = []  # weekly full check: callables (client, connection, record_ids) for every record it read, changed or not
SWEEP_DONE: list = []  # weekly full check finished: callables (connection, started_at); records not seen since were deleted


def deliver(client, connection, record: Record, phone_tokens: list[str]) -> None:
    for receiver in RECEIVERS:
        receiver(client, connection, record, phone_tokens)
