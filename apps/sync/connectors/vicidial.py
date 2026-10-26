"""Vicidial (dialer). Each call center runs its own Vicidial; CiV reads its call log tables through a READ-ONLY
database account on the client's server (CiV connects out; nothing opens on CiV's side). Built from Vicidial's
table layout (vicidial_log = outbound, vicidial_closer_log = inbound); not yet tried on a real server.

- Polled every 2 minutes. Each table is read oldest first by start_epoch (a universal timestamp, so no time-zone
  setting is needed), then by its row ID: "after this time and ID" bookmarks never skip or double a call.
- Only SELECT statements are ever sent.
- QA 2026-10-23: the connection is always encrypted (TLS, the server's certificate checked), and the address must be
  a real public server: blank, local or private addresses and ports that are not numbers are refused before connecting.
- Every hour the catch-up reads the last 3 hours again (`recent`): a call row finished after it was first read is
  found with its final length and status.
"""
import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, time

import pymysql

from ..connector import CONNECTORS, AccessRemoved, Connector, Page, Record

LAG_SECONDS = 120  # calls still being written wait for the next run
TIMEOUT_SECONDS = 20
RECENT_MAX = 50_000  # rows per table read again by the hourly catch-up


@dataclass(frozen=True)
class Table:
    name: str  # bookmark key
    table: str
    id_column: str
    columns: str  # read only what the audit needs


OUTBOUND = Table('outbound', 'vicidial_log', 'uniqueid',
                 'uniqueid, lead_id, list_id, campaign_id, call_date, start_epoch, end_epoch, length_in_sec, status, '
                 'phone_code, phone_number, user, term_reason, alt_dial')
INBOUND = Table('inbound', 'vicidial_closer_log', 'closecallid',
                'closecallid, lead_id, list_id, campaign_id, call_date, start_epoch, end_epoch, length_in_sec, status, '
                'phone_code, phone_number, user, term_reason, uniqueid')
TABLES = (OUTBOUND, INBOUND)


class BadAddress(ValueError):
    """The Vicidial server address cannot be used (blank, local or private, or a bad port)."""


def server(address: str) -> dict:
    """'db.callcenter.com:3306/asterisk' → host, port, database (Vicidial's database is usually 'asterisk').
    Refuses a blank, local or private host and a port that is not 1–65535, before any connection is made."""
    host_port, _, database = address.strip().partition('/')
    host, _, port = host_port.partition(':')
    if not host:
        raise BadAddress('Enter the Vicidial database server, e.g. db.callcenter.com:3306/asterisk.')
    if port and not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
        raise BadAddress('The port must be a number, e.g. 3306.')
    try:
        found = {a[4][0] for a in socket.getaddrinfo(host, int(port or 3306), proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        raise BadAddress('That server address could not be found.') from None
    if any(not ipaddress.ip_address(a.split('%')[0]).is_global for a in found):
        raise BadAddress('That address is not a public server.')
    return {'host': host, 'port': int(port or 3306), 'database': database or 'asterisk'}


class Vicidial(Connector):
    mode = 'poll'
    source_grade = 'C'
    counts = ('calls',)

    def __init__(self, connection):
        super().__init__(connection)
        creds = connection.get_credentials()
        self.address, self.user, self.password = creds.get('account', ''), creds.get('key', ''), creds.get('secret', '')

    def query(self, sql: str, params: tuple) -> list[dict]:
        """One read-only query. A fresh connection each time: simple and safe across worker processes."""
        try:
            # Always encrypted, with the server's certificate checked: the password and numbers never cross the
            # internet in plain text.
            db = pymysql.connect(**server(self.address), user=self.user, password=self.password, connect_timeout=TIMEOUT_SECONDS,
                                 read_timeout=TIMEOUT_SECONDS, cursorclass=pymysql.cursors.DictCursor, charset='utf8mb4',
                                 ssl_verify_cert=True, ssl_verify_identity=True)
        except pymysql.err.OperationalError as error:
            if error.args and error.args[0] == 1045:
                raise AccessRemoved('database user or password refused') from None
            raise
        try:
            with db.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        finally:
            db.close()

    def rows_after(self, table: Table, epoch: int, last_id: str, until: int, limit: int) -> list[dict]:
        sql = (f'SELECT {table.columns} FROM {table.table} '
               f'WHERE (start_epoch > %s OR (start_epoch = %s AND {table.id_column} > %s)) AND start_epoch <= %s '
               f'ORDER BY start_epoch, {table.id_column} LIMIT %s')
        return self.query(sql, (epoch, epoch, last_id, until, limit))

    def count_between(self, measure: str, start: datetime, end: datetime) -> int:
        """Vicidial's own count: rows in both call log tables in the range."""
        return sum(int(self.query(f'SELECT COUNT(*) AS n FROM {t.table} WHERE start_epoch >= %s AND start_epoch < %s',
                                  (int(start.timestamp()), int(end.timestamp())))[0]['n']) for t in TABLES)

    def record(self, row: dict, table: Table) -> Record:
        clean = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in row.items()}
        number = f"{row.get('phone_code') or ''}{row.get('phone_number') or ''}"
        return Record(source_record_id=f'{table.name}:{row[table.id_column]}',
                      raw=json.dumps(clean, sort_keys=True, separators=(',', ':'), default=str).encode(),
                      content_kind='call', changed_at=datetime.fromtimestamp(int(row['start_epoch']), UTC),
                      phones=[number] if row.get('phone_number') else [])

    def fetch_one(self, record_id: str) -> Record | None:
        name, _, key = record_id.partition(':')
        table = next((t for t in TABLES if t.name == name), None)
        if table is None:
            raise NotImplementedError
        rows = self.query(f'SELECT {table.columns} FROM {table.table} WHERE {table.id_column} = %s LIMIT 1', (key,))
        return self.record(rows[0], table) if rows else None

    def recent(self, since: datetime) -> list[Record]:
        until = int(datetime.now(UTC).timestamp()) - LAG_SECONDS
        out = []
        for table in TABLES:
            rows = self.query(f'SELECT {table.columns} FROM {table.table} WHERE start_epoch >= %s AND start_epoch <= %s '
                              f'ORDER BY start_epoch, {table.id_column} LIMIT %s', (int(since.timestamp()), until, RECENT_MAX))
            out += [self.record(r, table) for r in rows]
        return out

    def start_epoch(self) -> int:
        return int(datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC).timestamp())

    def changes_since(self, cursor: str, limit: int) -> Page:
        """Both tables, half a batch each; each keeps its own bookmark "<epoch>|<last id>"."""
        marks = json.loads(cursor) if cursor else {}
        until = int(datetime.now(UTC).timestamp()) - LAG_SECONDS
        records, more = [], False
        for table in TABLES:
            epoch, _, last_id = marks.get(table.name, f'{self.start_epoch() - 1}|').partition('|')
            share = max(1, limit // len(TABLES))
            rows = self.rows_after(table, int(epoch), last_id, until, share)
            records += [self.record(r, table) for r in rows]
            if rows:
                marks[table.name] = f"{int(rows[-1]['start_epoch'])}|{rows[-1][table.id_column]}"
            more = more or len(rows) == share
        records.sort(key=lambda r: (r.changed_at, r.source_record_id))
        return Page(records, json.dumps(marks, sort_keys=True), more)


CONNECTORS['vicidial'] = Vicidial
