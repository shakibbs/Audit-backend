"""Vicidial (dialer). Each call center runs its own Vicidial; CiV reads its call log tables through a READ-ONLY
database account on the client's server (CiV connects out; nothing opens on CiV's side). Built from Vicidial's
table layout (vicidial_log = outbound, vicidial_closer_log = inbound); not yet tried on a real server.

- Polled every 2 minutes. Each table is read oldest first by start_epoch (a universal timestamp, so no time-zone
  setting is needed), then by its row ID: "after this time and ID" bookmarks never skip or double a call.
- Only SELECT statements are ever sent.
"""
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time

import pymysql

from ..connector import CONNECTORS, Connector, Page, Record

LAG_SECONDS = 120  # calls still being written wait for the next run
TIMEOUT_SECONDS = 20


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


def server(address: str) -> dict:
    """'db.callcenter.com:3306/asterisk' → host, port, database (Vicidial's database is usually 'asterisk')."""
    host_port, _, database = address.strip().partition('/')
    host, _, port = host_port.partition(':')
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
        db = pymysql.connect(**server(self.address), user=self.user, password=self.password, connect_timeout=TIMEOUT_SECONDS,
                             read_timeout=TIMEOUT_SECONDS, cursorclass=pymysql.cursors.DictCursor, charset='utf8mb4')
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
