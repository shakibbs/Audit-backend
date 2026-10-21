"""Salesforce (CRM). Built from the Salesforce REST API docs (SOQL query, OAuth refresh); not yet tried on a real org.

- Reads Leads, Contacts and logged calls (Tasks of subtype Call) changed since the bookmark, oldest first by
  SystemModstamp then Id, with every field (FIELDS(ALL), which Salesforce allows 200 rows at a time), so custom fields
  such as a TrustedForm certificate link reach the certificate queue.
- Each object keeps its own bookmark "<SystemModstamp>|<Id>"; the newest 2 minutes wait.
- Uses the client's access pass from "Allow" (instance_url, access_token, refresh_token), renewed when it expires.
"""
import json
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from ..connector import CONNECTORS, Connector, Page, Record
from .oauth import OAuthTool

API_VERSION = 'v62.0'
MAX_ROWS = 200  # Salesforce's limit for FIELDS(ALL)
LAG = timedelta(minutes=2)


@dataclass(frozen=True)
class SObject:
    name: str  # bookmark key
    sobject: str
    where: str  # extra filter
    content_kind: str
    phone_fields: tuple


OBJECTS = (
    SObject('leads', 'Lead', '', 'lead', ('Phone', 'MobilePhone')),
    SObject('contacts', 'Contact', '', 'crm_record', ('Phone', 'MobilePhone', 'HomePhone', 'OtherPhone')),
    SObject('calls', 'Task', "TaskSubtype = 'Call' AND ", 'crm_record', ()),
)


def soql_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def sf_time(value: str) -> datetime:
    """'2026-10-01T15:02:11.000+0000' → aware UTC."""
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(UTC)


class Salesforce(OAuthTool, Connector):
    mode = 'poll'
    source_grade = 'C'
    counts = ('crm_records',)
    token_url = 'https://login.salesforce.com/services/oauth2/token'
    client_id_setting, client_secret_setting = 'SALESFORCE_CLIENT_ID', 'SALESFORCE_CLIENT_SECRET'

    def query(self, soql: str) -> list[dict]:
        instance = self._creds().get('instance_url', '').rstrip('/')
        answer = self.call(f'{instance}/services/data/{API_VERSION}/query?' + urllib.parse.urlencode({'q': soql}))
        rows = list(answer.get('records', []))
        while not answer.get('done', True) and answer.get('nextRecordsUrl'):
            answer = self.call(instance + answer['nextRecordsUrl'])
            rows.extend(answer.get('records', []))
        return rows

    def count_between(self, measure: str, start: datetime, end: datetime) -> int:
        """Salesforce's own count of leads and contacts created in the range (SOQL COUNT())."""
        instance = self._creds().get('instance_url', '').rstrip('/')
        total = 0
        for sobject in ('Lead', 'Contact'):
            soql = f'SELECT COUNT() FROM {sobject} WHERE CreatedDate >= {soql_time(start)} AND CreatedDate < {soql_time(end)}'
            total += int(self.call(f'{instance}/services/data/{API_VERSION}/query?' + urllib.parse.urlencode({'q': soql})).get('totalSize') or 0)
        return total

    def changed_after(self, obj: SObject, after: datetime, last_id: str, until: datetime, limit: int) -> list[dict]:
        since, stop = soql_time(after), soql_time(until)
        soql = (f'SELECT FIELDS(ALL) FROM {obj.sobject} WHERE {obj.where}'
                f"(SystemModstamp > {since} OR (SystemModstamp = {since} AND Id > '{last_id}')) AND SystemModstamp <= {stop} "
                f'ORDER BY SystemModstamp, Id LIMIT {min(limit, MAX_ROWS)}')
        return self.query(soql)

    def record(self, row: dict, obj: SObject) -> Record:
        clean = {k: v for k, v in row.items() if k != 'attributes'}
        return Record(source_record_id=f"{obj.name}:{row['Id']}", raw=json.dumps(clean, sort_keys=True, separators=(',', ':')).encode(),
                      content_kind=obj.content_kind, changed_at=sf_time(row['SystemModstamp']),
                      phones=[row[f] for f in obj.phone_fields if row.get(f)])

    def fetch_one(self, record_id: str) -> Record | None:
        import re
        name, _, key = record_id.partition(':')
        obj = next((o for o in OBJECTS if o.name == name), None)
        if obj is None or not re.fullmatch(r'[A-Za-z0-9]{15,18}', key):
            raise NotImplementedError
        rows = self.query(f"SELECT FIELDS(ALL) FROM {obj.sobject} WHERE Id = '{key}' LIMIT 1")
        return self.record(rows[0], obj) if rows else None

    def changes_since(self, cursor: str, limit: int) -> Page:
        marks = json.loads(cursor) if cursor else {}
        start = datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC) - timedelta(seconds=1)
        until = datetime.now(UTC) - LAG
        share = max(1, limit // len(OBJECTS))
        records, more = [], False
        for obj in OBJECTS:
            stamp, _, last_id = marks.get(obj.name, f'{start.isoformat()}|').partition('|')
            rows = self.changed_after(obj, datetime.fromisoformat(stamp), last_id, until, share)
            records += [self.record(r, obj) for r in rows]
            if rows:
                marks[obj.name] = f"{sf_time(rows[-1]['SystemModstamp']).isoformat()}|{rows[-1]['Id']}"
            more = more or len(rows) == min(share, MAX_ROWS)
        records.sort(key=lambda r: (r.changed_at, r.source_record_id))
        return Page(records, json.dumps(marks, sort_keys=True), more)


CONNECTORS['salesforce'] = Salesforce
