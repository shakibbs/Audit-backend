"""Five9 (dialer). Built from Five9's Configuration Web Services docs (SOAP: runReport, isReportRunning,
getReportResultCsv); not yet tried on a real account.

- Five9 gives call logs as reports: CiV asks it to run the "Call Log" report for a time range, waits until it is
  ready, then downloads it as CSV. Reports are slow and limited, so Five9 is read every 10 minutes (min_poll_minutes),
  one window per report, the whole window at once.
- Report times are in the account's time zone (saved with the connection); CiV turns them into UTC.
- Column names are matched loosely (CALL ID, TIMESTAMP or DATE + TIME, ANI, DNIS…), to confirm on a real account.
"""
import base64
import csv
import hashlib
import io
import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, time, timedelta
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..connector import CONNECTORS, Connector, Page, Record

API = 'https://api.five9.com/wsadmin/v12/AdminWebService'
NS = 'http://service.admin.ws.five9.com/'
REPORT_FOLDER, REPORT_NAME = 'Call Log Reports', 'Call Log'
WINDOW = timedelta(hours=1)
LAG = timedelta(minutes=5)  # Five9 reports fill in a little after the call
WAIT_SECONDS, WAIT_ROUNDS = 10, 12  # isReportRunning waits up to 10 s itself: about 2 minutes in all
TIMEOUT_SECONDS = 60
TIME_FORMATS = ('%a, %d %b %Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%m/%d/%Y %I:%M:%S %p')


class Five9Error(Exception):
    """A SOAP fault from Five9 (wrong password, no report rights, unknown report…)."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise Five9Error(f'Unknown report time zone "{name}"') from None


def column(row: dict, *names: str) -> str:
    """The first non-empty value among loosely matching column names (case and spaces ignored)."""
    wanted = [n.replace(' ', '').upper() for n in names]
    for key, value in row.items():
        if key and key.replace(' ', '').upper() in wanted and value:
            return value.strip()
    return ''


class Five9(Connector):
    mode = 'poll'
    source_grade = 'C'
    min_poll_minutes = 10

    def __init__(self, connection):
        super().__init__(connection)
        creds = connection.get_credentials()
        self.user, self.password = creds.get('account', ''), creds.get('key', '')
        self.tz = zone(creds.get('secret') or 'America/New_York')

    # --- SOAP ----------------------------------------------------------------------------------------------
    def soap(self, method: str, inner: str) -> ET.Element:
        envelope = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
                    f'xmlns:ser="{NS}"><soapenv:Body><ser:{method}>{inner}</ser:{method}></soapenv:Body></soapenv:Envelope>')
        auth = base64.b64encode(f'{self.user}:{self.password}'.encode()).decode()
        request = urllib.request.Request(API, data=envelope.encode(), headers={
            'Authorization': f'Basic {auth}', 'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': ''})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
                return self.answer(reply.read())
        except urllib.error.HTTPError as error:  # Five9 sends faults with status 500
            return self.answer(error.read())

    @staticmethod
    def answer(xml: bytes) -> ET.Element:
        root = ET.fromstring(xml)
        fault = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Fault')
        if fault is not None:
            raise Five9Error((fault.findtext('faultstring') or 'Five9 fault').strip())
        found = root.find('.//return')
        return found if found is not None else root

    def _when(self, moment: datetime) -> str:
        return moment.astimezone(self.tz).strftime('%Y-%m-%dT%H:%M:%S.000%z')

    def report_csv(self, start: datetime, end: datetime) -> str:
        """Runs the Call Log report for [start, end), waits for it, returns its CSV."""
        criteria = (f'<folderName>{escape(REPORT_FOLDER)}</folderName><reportName>{escape(REPORT_NAME)}</reportName>'
                    f'<criteria><time><end>{self._when(end - timedelta(seconds=1))}</end><start>{self._when(start)}</start></time></criteria>')
        report_id = (self.soap('runReport', criteria).text or '').strip()
        for _ in range(WAIT_ROUNDS):
            running = self.soap('isReportRunning', f'<identifier>{escape(report_id)}</identifier><timeout>{WAIT_SECONDS}</timeout>')
            if (running.text or '').strip().lower() == 'false':
                return self.soap('getReportResultCsv', f'<identifier>{escape(report_id)}</identifier>').text or ''
        raise TimeoutError('Five9 report still running; tried again next turn')

    # --- rows ------------------------------------------------------------------------------------------------
    def called_at(self, row: dict) -> datetime:
        text = column(row, 'TIMESTAMP', 'CALL TIMESTAMP') or f"{column(row, 'DATE')} {column(row, 'TIME')}".strip()
        for fmt in TIME_FORMATS:
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=self.tz).astimezone(UTC)
            except ValueError:
                continue
        raise Five9Error(f'Unreadable call time "{text}"')

    def record(self, row: dict) -> Record:
        raw = json.dumps(row, sort_keys=True, separators=(',', ':')).encode()
        call_id = column(row, 'CALL ID', 'CALLID', 'SESSION ID') or hashlib.sha256(raw).hexdigest()[:32]
        phones = [p for p in (column(row, 'DNIS'), column(row, 'ANI'), column(row, 'NUMBER', 'NUMBER1')) if p]
        return Record(source_record_id=call_id, raw=raw, content_kind='call', changed_at=self.called_at(row),
                      phones=list(dict.fromkeys(phones)))

    def changes_since(self, cursor: str, limit: int) -> Page:
        """One window per report, all of it at once: running the same report again for each small batch would be slow."""
        begin = datetime.fromisoformat(cursor) if cursor else datetime.combine(self.connection.client.start_date, time(0), tzinfo=UTC)
        safe_now = datetime.now(UTC) - LAG
        if begin >= safe_now:
            return Page([], cursor, False)
        end = min(begin + WINDOW, safe_now)
        rows = [r for r in csv.DictReader(io.StringIO(self.report_csv(begin, end))) if any((v or '').strip() for v in r.values())]
        records = sorted((self.record(r) for r in rows), key=lambda rec: (rec.changed_at, rec.source_record_id))
        return Page(records, end.isoformat(), end < safe_now)


CONNECTORS['five9'] = Five9
