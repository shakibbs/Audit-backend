"""Twilio: texts and calls. Built from Twilio's REST API docs (Messages and Calls resources, request validation);
not yet tried against a real account.

- Polling: GET /2010-04-01/Accounts/{sid}/Messages.json (by DateSent) and Calls.json (by StartTime), one window at
  a time, all pages, read oldest first. Each has its own bookmark "<time>#<how many with exactly that time are done>",
  so nothing is skipped or doubled.
- Live notices (off unless the door is opened): Twilio's webhook form fields, checked with X-Twilio-Signature
  (HMAC-SHA1 of the full URL plus the sorted fields, with the auth token).
"""
import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from email.utils import parsedate_to_datetime

from ..connector import CONNECTORS, AccessRemoved, BadSignature, Connector, Page, Record, raise_for_status

API = 'https://api.twilio.com'
WINDOW = timedelta(hours=1)  # one hour per request series, read whole: a busy day was re-read for every batch (QA 2026-10-23)
LAG = timedelta(minutes=2)  # the newest two minutes wait for the next run: records may still be landing
PAGE_SIZE = 1000  # Twilio's largest page
TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class Stream:
    name: str  # bookmark key
    resource: str  # Messages / Calls
    list_key: str  # where the rows are in the answer
    time_filter: str  # DateSent / StartTime
    time_field: str  # date_sent / start_time
    content_kind: str


TEXTS = Stream('texts', 'Messages', 'messages', 'DateSent', 'date_sent', 'text')
CALLS = Stream('calls', 'Calls', 'calls', 'StartTime', 'start_time', 'call')
STREAMS = (TEXTS, CALLS)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def happened_at(row: dict, stream: Stream = TEXTS) -> datetime:
    """Sent time (texts) or start time (calls); creation time while still queued. RFC 2822, as Twilio sends it."""
    return parsedate_to_datetime(row.get(stream.time_field) or row['date_created']).astimezone(UTC)


sent_at = happened_at  # texts


# A Twilio Account SID is "AC" and 32 letters or digits (owner, 2026-10-31): checked before it goes into an address.
SID = re.compile(r'AC[0-9a-fA-F]{32}')
BAD_SID = "This doesn't look like a Twilio Account SID. It starts with AC and is 34 characters long."


def account_sid(text: str) -> str | None:
    text = (text or '').strip()
    return text if SID.fullmatch(text) else None


class Twilio(Connector):
    mode = 'poll'
    source_grade = 'C'

    def __init__(self, connection):
        super().__init__(connection)
        creds = connection.get_credentials()
        self.sid, self.token = account_sid(creds.get('account', '')), creds.get('key', '')

    # --- reading -------------------------------------------------------------------------------------------
    def _get(self, path_or_url: str, params: dict | None = None) -> dict:
        if self.sid is None:  # a bad Account SID never goes into an address: staff must fix the connection
            raise AccessRemoved(BAD_SID)
        url = path_or_url if path_or_url.startswith('http') else API + path_or_url
        if params:
            url += '?' + urllib.parse.urlencode(params)
        auth = base64.b64encode(f'{self.sid}:{self.token}'.encode()).decode()
        request = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
                return json.loads(reply.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise  # one record gone (fetch_one answers None)
            raise_for_status(error)

    def rows_between(self, stream: Stream, start: datetime, end: datetime) -> list[dict]:
        """Every row from start up to (not including) end, oldest first. Twilio lists newest first."""
        params = {f'{stream.time_filter}>': _iso(start), f'{stream.time_filter}<': _iso(end - timedelta(seconds=1)), 'PageSize': PAGE_SIZE}
        page = self._get(f'/2010-04-01/Accounts/{self.sid}/{stream.resource}.json', params)
        found = list(page.get(stream.list_key, []))
        while page.get('next_page_uri'):
            page = self._get(page['next_page_uri'])
            found.extend(page.get(stream.list_key, []))
        return sorted((r for r in found if start <= happened_at(r, stream) < end), key=lambda r: (happened_at(r, stream), r['sid']))

    def record(self, row: dict, stream: Stream = TEXTS) -> Record:
        return Record(source_record_id=row['sid'], raw=json.dumps(row, sort_keys=True, separators=(',', ':')).encode(),
                      content_kind=stream.content_kind, changed_at=happened_at(row, stream),
                      phones=[n for n in (row.get('to'), row.get('from')) if n and n.startswith('+')])

    def fetch_one(self, record_id: str) -> Record | None:
        stream = CALLS if record_id.startswith('CA') else TEXTS
        try:
            row = self._get(f'/2010-04-01/Accounts/{self.sid}/{stream.resource}/{urllib.parse.quote(record_id, safe="")}.json')
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        return self.record(row, stream)

    def start(self) -> datetime:
        return datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC)

    def read_stream(self, stream: Stream, cursor: str, limit: int) -> Page:
        mark, _, done = (cursor or '').partition('#')
        begin = datetime.fromisoformat(mark) if mark else self.start()
        skip = int(done or 0)
        safe_now = datetime.now(UTC) - LAG
        if begin >= safe_now or limit <= 0:
            return Page([], cursor, begin < safe_now)
        end = min(begin + WINDOW, safe_now)
        rows = self.rows_between(stream, begin, end)
        # The whole hour at once: its pages are read one after another with Twilio's next-page link, never again.
        # Rows at exactly the bookmark time come first; `skip` of them were done in an older-style batch.
        rest = [r for r in rows if happened_at(r, stream) == begin][skip:] + [r for r in rows if happened_at(r, stream) > begin]
        return Page([self.record(r, stream) for r in rest], f'{end.isoformat()}#0', end < safe_now)

    def recent(self, since: datetime) -> list[Record]:
        """Texts and calls of the last hours again: a call read while it was ringing now has its final status and length."""
        safe_now = datetime.now(UTC) - LAG
        out = []
        for stream in STREAMS:
            start = since
            while start < safe_now:
                end = min(start + WINDOW, safe_now)
                out += [self.record(r, stream) for r in self.rows_between(stream, start, end)]
                start = end
        return out

    def changes_since(self, cursor: str, limit: int) -> Page:
        """Texts and calls, each with its own bookmark, sharing the batch. Bookmark = JSON of both."""
        marks = json.loads(cursor) if cursor.startswith('{') else {'texts': cursor} if cursor else {}
        records, more = [], False
        for stream in STREAMS:
            # Each stream reads its own next hour in every batch: a backlog of one never holds up the other.
            page = self.read_stream(stream, marks.get(stream.name, ''), limit)
            records += page.records
            marks[stream.name] = page.next_cursor
            more = more or page.more
        return Page(records, json.dumps(marks, sort_keys=True), more)

    # --- live notices (off unless the door is opened) ------------------------------------------------------
    def parse_event(self, body: bytes, headers: dict) -> list[Record]:
        fields = urllib.parse.parse_qsl(body.decode(), keep_blank_values=True)
        url = headers.get('_url', '')
        signed = url + ''.join(f'{k}{v}' for k, v in sorted(fields))
        expected = base64.b64encode(hmac.new(self.token.encode(), signed.encode(), hashlib.sha1).digest()).decode()
        if not self.token or not hmac.compare_digest(expected, headers.get('X-Twilio-Signature', '')):
            raise BadSignature
        data = dict(fields)
        is_text = 'MessageSid' in data or 'SmsSid' in data
        sid = data.get('MessageSid') or data.get('SmsSid') if is_text else data.get('CallSid')
        if not sid:
            return []
        return [Record(source_record_id=sid, raw=body, content_kind='text' if is_text else 'call', changed_at=datetime.now(UTC),
                       phones=[n for n in (data.get('To'), data.get('From')) if n])]


CONNECTORS['twilio'] = Twilio
