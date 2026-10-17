"""What every tool adapter answers. A real tool (Twilio, a dialer, a CRM…) is one small class; the engine does the rest."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Record:
    source_record_id: str  # the record's ID in the tool, to find the original again
    raw: bytes  # exactly as received; fingerprinted, never kept
    content_kind: str  # apps.ledger.models.ContentKind
    changed_at: datetime  # when the tool says it changed
    phones: list[str] = field(default_factory=list)  # numbers in the record; turned into phone codes, never kept


@dataclass
class Page:
    records: list[Record]
    next_cursor: str  # the bookmark to continue from
    more: bool  # True when the tool has more right now


class Connector:
    """One tool. `mode` 'live' = the tool notifies CiV (catch-up then only finds what it missed);
    'poll' = CiV asks every few minutes."""
    mode = 'poll'
    source_grade = 'C'  # from the client's systems by API (spec §4)
    min_poll_minutes = 0  # a tool that dislikes frequent reads (e.g. Five9 reports) is polled no more often than this
    counts: tuple = ()  # what the tool can total by itself for records completeness: calls, texts, crm_records

    def __init__(self, connection):
        self.connection = connection

    def changes_since(self, cursor: str, limit: int) -> Page:
        """Records changed after the bookmark, oldest first."""
        raise NotImplementedError

    def list_all(self, cursor: str, limit: int) -> Page:
        """Every record, for the weekly full check, continuing from its own bookmark ('' = from the beginning).
        Defaults to reading all changes from the beginning."""
        return self.changes_since(cursor, limit)

    def count_between(self, measure: str, start: datetime, end: datetime) -> int:
        """The tool's own total of `measure` from start up to (not including) end, asked in one request."""
        raise NotImplementedError

    def parse_event(self, body: bytes, headers: dict) -> list[Record]:
        """A live notice from the tool. Must check the tool's signature and raise BadSignature if wrong."""
        raise NotImplementedError


class BadSignature(Exception):
    pass


# provider code → Connector class. Real tools are added in the next steps; until then nothing syncs.
CONNECTORS: dict[str, type[Connector]] = {}


def connector_for(connection) -> Connector | None:
    cls = CONNECTORS.get(connection.provider)
    return cls(connection) if cls else None
