"""HubSpot (CRM). Built from HubSpot's CRM v3 docs (objects search, properties, OAuth refresh); not yet tried on a
real portal.

- Reads contacts and logged calls changed since the bookmark through the search API, sorted by hs_lastmodifieddate
  (milliseconds), 100 per page. Bookmark per object "<ms>#<how many at exactly that ms are done>": a run asks for
  "on or after" the mark and skips the ones already done, so nothing is skipped or doubled.
- The search answer only has the properties asked for, so CiV asks for the standard ones it needs plus any property
  whose name mentions TrustedForm, LeadiD or Jornaya (certificate links go to the claim queue).
"""
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from ..connector import CONNECTORS, Connector, Page, Record
from .oauth import OAuthTool

API = 'https://api.hubapi.com'
PAGE = 100  # HubSpot's search page size
LAG = timedelta(minutes=2)
CERT_WORDS = ('trustedform', 'leadid', 'jornaya')


@dataclass(frozen=True)
class HObject:
    name: str
    path: str  # contacts / calls
    content_kind: str
    standard: tuple
    phone_props: tuple


OBJECTS = (
    HObject('contacts', 'contacts', 'crm_record',
            ('phone', 'mobilephone', 'hs_lastmodifieddate', 'createdate', 'lifecyclestage', 'hs_lead_status',
             'hs_analytics_source', 'hs_latest_source', 'hs_email_optout'), ('phone', 'mobilephone')),
    HObject('calls', 'calls', 'crm_record',
            ('hs_lastmodifieddate', 'hs_timestamp', 'hs_call_direction', 'hs_call_disposition', 'hs_call_status',
             'hs_call_to_number', 'hs_call_from_number', 'hs_call_duration'), ('hs_call_to_number', 'hs_call_from_number')),
)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def modified(row: dict) -> datetime:
    value = row.get('properties', {}).get('hs_lastmodifieddate') or row.get('updatedAt')
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


class HubSpot(OAuthTool, Connector):
    mode = 'poll'
    source_grade = 'C'
    token_url = f'{API}/oauth/v1/token'
    client_id_setting, client_secret_setting = 'HUBSPOT_CLIENT_ID', 'HUBSPOT_CLIENT_SECRET'

    def properties(self, obj: HObject) -> list[str]:
        names = [p['name'] for p in self.call(f'{API}/crm/v3/properties/{obj.path}').get('results', [])]
        extra = [n for n in names if any(word in n.lower() for word in CERT_WORDS)]
        return list(dict.fromkeys([*obj.standard, *extra]))

    def changed_from(self, obj: HObject, start_ms: int, until_ms: int, skip: int, want: int) -> list[dict]:
        """Rows modified at or after start_ms (oldest first), dropping the first `skip` at exactly start_ms."""
        props, rows, after = self.properties(obj), [], None
        while len(rows) < want + skip:
            body = {'filterGroups': [{'filters': [
                        {'propertyName': 'hs_lastmodifieddate', 'operator': 'GTE', 'value': str(start_ms)},
                        {'propertyName': 'hs_lastmodifieddate', 'operator': 'LTE', 'value': str(until_ms)}]}],
                    'sorts': [{'propertyName': 'hs_lastmodifieddate', 'direction': 'ASCENDING'}],
                    'properties': props, 'limit': PAGE}
            if after:
                body['after'] = after
            answer = self.call(f'{API}/crm/v3/objects/{obj.path}/search', body)
            rows.extend(answer.get('results', []))
            after = answer.get('paging', {}).get('next', {}).get('after')
            if not after:
                break
        rows.sort(key=lambda r: (modified(r), r['id']))
        at_start = [r for r in rows if ms(modified(r)) == start_ms]
        return (at_start[skip:] + [r for r in rows if ms(modified(r)) > start_ms])[:want]

    def record(self, row: dict, obj: HObject) -> Record:
        props = row.get('properties', {})
        return Record(source_record_id=f"{obj.name}:{row['id']}", raw=json.dumps(row, sort_keys=True, separators=(',', ':')).encode(),
                      content_kind=obj.content_kind, changed_at=modified(row), phones=[props[p] for p in obj.phone_props if props.get(p)])

    def changes_since(self, cursor: str, limit: int) -> Page:
        marks = json.loads(cursor) if cursor else {}
        first = ms(datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC))
        until = ms(datetime.now(UTC) - LAG)
        share = max(1, limit // len(OBJECTS))
        records, more = [], False
        for obj in OBJECTS:
            mark, _, done = marks.get(obj.name, f'{first}#0').partition('#')
            start, skip = int(mark), int(done)
            rows = self.changed_from(obj, start, until, skip, share)
            records += [self.record(r, obj) for r in rows]
            if rows:
                last = ms(modified(rows[-1]))
                same = sum(1 for r in rows if ms(modified(r)) == last) + (skip if last == start else 0)
                marks[obj.name] = f'{last}#{same}'
            more = more or len(rows) == share
        records.sort(key=lambda r: (r.changed_at, r.source_record_id))
        return Page(records, json.dumps(marks, sort_keys=True), more)


CONNECTORS['hubspot'] = HubSpot
