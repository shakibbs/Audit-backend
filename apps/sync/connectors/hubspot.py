"""HubSpot (CRM). Built from HubSpot's CRM v3 docs (objects search, properties, OAuth refresh); not yet tried on a
real portal.

- Reads contacts and logged calls changed since the bookmark through the search API, sorted by hs_lastmodifieddate
  (milliseconds), 100 per page, one TIME WINDOW at a time (QA 2026-10-23):
  - a window is read whole; when it took more than one page it is searched again from its start and anything new is
    added, because a record changed while CiV was paging moves and shifts the pages after it;
  - HubSpot's search stops at 10,000 results, so a window with more is halved until it fits.
  Bookmark per object "<ms>#0" = the window's end; older bookmarks with "#<n>" still work.
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
WINDOW_MS = 24 * 3600 * 1000  # one day per search, halved when it holds more than one search can give
SEARCH_CAP = 9_000  # HubSpot's search gives at most 10,000 results
CERT_WORDS = ('trustedform', 'leadid', 'jornaya', 'consent',  # certificate links and the client's own consent fields
              'vendor', 'provider', 'publisher', 'affiliate', 'supplier', 'lead_source', 'utm_source')  # who supplied the lead


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
             'hs_analytics_source', 'hs_latest_source', 'hs_email_optout',
             'hs_object_source', 'hs_created_by_user_id', 'hs_updated_by_user_id',  # how and by whom it was created or changed (uploads)
             'hs_lifecyclestage_customer_date'), ('phone', 'mobilephone')),  # became a customer (existing-customer proof)
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
    counts = ('crm_records', 'calls')
    token_url = f'{API}/oauth/v1/token'
    client_id_setting, client_secret_setting = 'HUBSPOT_CLIENT_ID', 'HUBSPOT_CLIENT_SECRET'

    def properties(self, obj: HObject) -> list[str]:
        names = [p['name'] for p in self.call(f'{API}/crm/v3/properties/{obj.path}').get('results', [])]
        extra = [n for n in names if any(word in n.lower() for word in CERT_WORDS)]
        return list(dict.fromkeys([*obj.standard, *extra]))

    def search(self, obj: HObject, props: list[str], start_ms: int, end_ms: int) -> tuple[list[dict], int, int]:
        """(rows modified in [start_ms, end_ms), HubSpot's total, pages read)."""
        rows, after, pages, total = [], None, 0, 0
        while True:
            body = {'filterGroups': [{'filters': [
                        {'propertyName': 'hs_lastmodifieddate', 'operator': 'GTE', 'value': str(start_ms)},
                        {'propertyName': 'hs_lastmodifieddate', 'operator': 'LT', 'value': str(end_ms)}]}],
                    'sorts': [{'propertyName': 'hs_lastmodifieddate', 'direction': 'ASCENDING'}],
                    'properties': props, 'limit': PAGE}
            if after:
                body['after'] = after
            answer = self.call(f'{API}/crm/v3/objects/{obj.path}/search', body)
            pages += 1
            total = int(answer.get('total') or total)
            if pages == 1 and total > SEARCH_CAP:
                return [], total, pages  # too many for one search: the caller halves the window
            rows.extend(answer.get('results', []))
            after = answer.get('paging', {}).get('next', {}).get('after')
            if not after:
                return rows, total, pages

    def window(self, obj: HObject, start_ms: int, until_ms: int) -> tuple[list[dict], int]:
        """Every row of the next window that fits one search, read whole (and read again when it was paged)."""
        props = self.properties(obj)
        end_ms = min(start_ms + WINDOW_MS, until_ms)
        while True:
            rows, total, pages = self.search(obj, props, start_ms, end_ms)
            if total <= SEARCH_CAP or end_ms - start_ms <= 1:
                break
            end_ms = start_ms + (end_ms - start_ms) // 2
        if pages > 1:  # rows changed while paging shift the pages after them: search the window once more
            again, _, _ = self.search(obj, props, start_ms, end_ms)
            known = {r['id'] for r in rows}
            rows += [r for r in again if r['id'] not in known]
        rows.sort(key=lambda r: (modified(r), r['id']))
        return rows, end_ms

    def count_between(self, measure: str, start: datetime, end: datetime) -> int:
        """HubSpot's own count (the search answer's total): contacts created, or calls made, in the range."""
        path, prop = ('contacts', 'createdate') if measure == 'crm_records' else ('calls', 'hs_timestamp')
        body = {'filterGroups': [{'filters': [{'propertyName': prop, 'operator': 'GTE', 'value': str(ms(start))},
                                              {'propertyName': prop, 'operator': 'LT', 'value': str(ms(end))}]}], 'limit': 1}
        return int(self.call(f'{API}/crm/v3/objects/{path}/search', body).get('total') or 0)

    def record(self, row: dict, obj: HObject) -> Record:
        props = row.get('properties', {})
        return Record(source_record_id=f"{obj.name}:{row['id']}", raw=json.dumps(row, sort_keys=True, separators=(',', ':')).encode(),
                      content_kind=obj.content_kind, changed_at=modified(row), phones=[props[p] for p in obj.phone_props if props.get(p)])

    def fetch_one(self, record_id: str) -> Record | None:
        import urllib.error
        import urllib.parse
        name, _, key = record_id.partition(':')
        obj = next((o for o in OBJECTS if o.name == name), None)
        if obj is None:
            raise NotImplementedError
        query = urllib.parse.urlencode({'properties': ','.join(self.properties(obj))})
        try:
            row = self.call(f'{API}/crm/v3/objects/{obj.path}/{urllib.parse.quote(key)}?{query}')
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        return self.record(row, obj)

    def changes_since(self, cursor: str, limit: int) -> Page:
        """One window per object; the bookmark moves to the window's end (records changed later fall in a later window)."""
        marks = json.loads(cursor) if cursor else {}
        first = ms(datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC))
        until = ms(datetime.now(UTC) - LAG)
        records, more = [], False
        for obj in OBJECTS:
            mark, _, _ = marks.get(obj.name, f'{first}#0').partition('#')
            start = int(mark)
            if start >= until:
                continue
            rows, end = self.window(obj, start, until)
            records += [self.record(r, obj) for r in rows]
            marks[obj.name] = f'{end}#0'
            more = more or end < until
        records.sort(key=lambda r: (r.changed_at, r.source_record_id))
        return Page(records, json.dumps(marks, sort_keys=True), more)


CONNECTORS['hubspot'] = HubSpot
