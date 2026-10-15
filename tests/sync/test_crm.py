"""Salesforce and HubSpot adapters against pretend APIs that follow their docs; access-pass renewal; certificate
links in CRM fields reach the claim queue."""
import io
import json
import re
import urllib.error
import urllib.parse
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.sync import engine, handoff
from apps.sync.connectors import hubspot as hs
from apps.sync.connectors import oauth
from apps.sync.connectors import salesforce as sf
from apps.sync.models import SyncCursor

pytestmark = pytest.mark.django_db
DAY = datetime(2026, 10, 1, tzinfo=UTC)
CERT = 'c' * 40


def sf_stamp(at: datetime) -> str:
    return at.strftime('%Y-%m-%dT%H:%M:%S.000+0000')


class FakeSalesforce:
    """Answers CiV's SOQL: object, modified-after (with Id tie-break), until, limit, sorted by SystemModstamp, Id."""
    def __init__(self, rows):
        self.rows, self.soql = rows, []

    def __call__(self, adapter, url, body=None):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['q'][0]
        self.soql.append(q)
        obj = re.search(r'FROM (\w+)', q).group(1)
        since = datetime.strptime(re.search(r'SystemModstamp > (\S+)', q).group(1), '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=UTC)
        last_id = re.search(r"Id > '([^']*)'", q).group(1)
        until = datetime.strptime(re.search(r'SystemModstamp <= (\S+)', q).group(1), '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=UTC)
        limit = int(re.search(r'LIMIT (\d+)', q).group(1))
        pick = [r for r in self.rows if r['attributes']['type'] == obj]
        pick = [r for r in pick if (sf.sf_time(r['SystemModstamp']) > since or (sf.sf_time(r['SystemModstamp']) == since and r['Id'] > last_id))
                and sf.sf_time(r['SystemModstamp']) <= until]
        pick.sort(key=lambda r: (r['SystemModstamp'], r['Id']))
        return {'done': True, 'records': pick[:limit]}


def lead(n, at, **extra):
    return {'attributes': {'type': 'Lead'}, 'Id': f'00Q{n:012d}', 'SystemModstamp': sf_stamp(at), 'Phone': f'916555{n:04d}',
            'MobilePhone': None, 'DoNotCall': False, 'LeadSource': 'Vendor A', **extra}


def contact(n, at):
    return {'attributes': {'type': 'Contact'}, 'Id': f'003{n:012d}', 'SystemModstamp': sf_stamp(at), 'Phone': f'480555{n:04d}'}


def task(n, at):
    return {'attributes': {'type': 'Task'}, 'Id': f'00T{n:012d}', 'SystemModstamp': sf_stamp(at), 'TaskSubtype': 'Call', 'CallDisposition': 'DNC'}


@pytest.fixture
def received(monkeypatch):
    got = []
    monkeypatch.setattr(handoff, 'RECEIVERS', [*handoff.RECEIVERS, lambda client, conn, record, tokens: got.append(record.source_record_id)])
    return got


def connect(company, provider, creds):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider=provider, status=Status.CONNECTED)
    c.set_credentials(creds)
    c.save()
    return c


@pytest.fixture
def clock(monkeypatch):
    def at(moment):
        for module in (sf, hs):
            monkeypatch.setattr(module, 'datetime', type('D', (datetime,), {'now': staticmethod(lambda tz=None: moment),
                                                                              'fromisoformat': staticmethod(datetime.fromisoformat),
                                                                              'strptime': staticmethod(datetime.strptime),
                                                                              'combine': staticmethod(datetime.combine)}))
    return at


def drain(conn):
    turns = 0
    while engine.run(conn.pk, 'poll'):
        turns += 1
        assert turns < 500


SF_CREDS = {'instance_url': 'https://sunpath.my.salesforce.com', 'access_token': 'old', 'refresh_token': 'r1'}


def test_salesforce_reads_leads_contacts_and_calls_once_and_queues_certificates(company, received, monkeypatch, clock, settings):
    settings.SYNC_BATCH_SIZE = 6
    rows = [lead(n, DAY + timedelta(minutes=n)) for n in range(1, 6)] + [contact(1, DAY + timedelta(minutes=3)), task(1, DAY + timedelta(minutes=4))]
    rows[0]['TrustedForm_Cert_URL__c'] = f'https://cert.trustedform.com/{CERT}'
    api = FakeSalesforce(rows)
    monkeypatch.setattr(sf.Salesforce, 'call', lambda self, url, body=None: api(self, url, body))
    clock(DAY + timedelta(hours=1))
    conn = connect(company, 'salesforce', SF_CREDS)
    drain(conn)
    assert sorted(received) == sorted([f'leads:00Q{n:012d}' for n in range(1, 6)] + ['contacts:003000000000001', 'calls:00T000000000001'])
    assert all('FIELDS(ALL)' in q and int(re.search(r'LIMIT (\d+)', q).group(1)) <= 200 for q in api.soql)
    assert any("TaskSubtype = 'Call'" in q for q in api.soql)
    assert CertificateClaim.objects.get().cert_ref == CERT  # a custom CRM field reached the 72-hour queue


def test_salesforce_same_stamp_never_skips_or_doubles(company, received, monkeypatch, clock, settings):
    settings.SYNC_BATCH_SIZE = 3  # one row per object per turn
    api = FakeSalesforce([lead(n, DAY + timedelta(minutes=5)) for n in range(1, 8)])
    monkeypatch.setattr(sf.Salesforce, 'call', lambda self, url, body=None: api(self, url, body))
    clock(DAY + timedelta(hours=1))
    drain(connect(company, 'salesforce', SF_CREDS))
    assert len(received) == 7 and len(set(received)) == 7


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_expired_pass_is_renewed_once_and_saved_locked(company, monkeypatch, settings):
    settings.SALESFORCE_CLIENT_ID, settings.SALESFORCE_CLIENT_SECRET = 'civ-app', 'civ-secret'
    conn = connect(company, 'salesforce', SF_CREDS)
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        if request.full_url == sf.Salesforce.token_url:
            form = urllib.parse.parse_qs(request.data.decode())
            assert form['grant_type'] == ['refresh_token'] and form['client_secret'] == ['civ-secret'] and form['refresh_token'] == ['r1']
            return Reply(json.dumps({'access_token': 'new', 'instance_url': SF_CREDS['instance_url']}).encode())
        if request.headers['Authorization'] == 'Bearer old':
            raise urllib.error.HTTPError(request.full_url, 401, 'INVALID_SESSION_ID', {}, io.BytesIO(b'[]'))
        return Reply(json.dumps({'done': True, 'records': []}).encode())
    monkeypatch.setattr(oauth.urllib.request, 'urlopen', urlopen)
    assert sf.Salesforce(conn).query('SELECT Id FROM Lead') == []
    conn.refresh_from_db()
    assert conn.get_credentials()['access_token'] == 'new' and conn.get_credentials()['refresh_token'] == 'r1'
    assert 'new' not in conn.credentials  # stored locked
    assert len(seen) == 3  # refused, renewed, retried


def test_access_removed_by_the_client_shows_as_disconnected(company, monkeypatch, clock):
    conn = connect(company, 'salesforce', SF_CREDS)

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400 if 'token' in request.full_url else 401, 'x', {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(oauth.urllib.request, 'urlopen', urlopen)
    clock(DAY + timedelta(hours=1))
    assert engine.run(conn.pk, 'poll') is False
    assert SyncCursor.objects.get(connection=conn).last_error == 'Disconnected'


class FakeHubSpot:
    """Properties list and the search API: GTE/LTE on hs_lastmodifieddate, ascending, 100 a page with an 'after' cursor."""
    def __init__(self, contacts, calls):
        self.objects, self.bodies = {'contacts': contacts, 'calls': calls}, []

    def __call__(self, adapter, url, body=None):
        if '/properties/' in url:
            return {'results': [{'name': n} for n in ('phone', 'firstname', 'trustedform_certificate_url', 'jornaya_leadid')]}
        self.bodies.append(body)
        path = url.rsplit('/objects/', 1)[1].split('/')[0]
        lo, hi = (int(f['value']) for f in body['filterGroups'][0]['filters'])
        rows = sorted((r for r in self.objects[path] if lo <= hs.ms(hs.modified(r)) <= hi), key=lambda r: (hs.modified(r), r['id']))
        start = int(body.get('after', 0))
        page = rows[start:start + hs.PAGE]
        nxt = {'next': {'after': str(start + hs.PAGE)}} if start + hs.PAGE < len(rows) else {}
        return {'results': [{**r, 'properties': {k: v for k, v in r['properties'].items() if k in body['properties']}} for r in page], 'paging': nxt}


def hcontact(n, at, **props):
    return {'id': str(500 + n), 'properties': {'phone': f'916555{n:04d}', 'hs_lastmodifieddate': at.isoformat().replace('+00:00', 'Z'),
                                                'firstname': 'Not needed', **props}}


def hcall(n, at):
    return {'id': str(900 + n), 'properties': {'hs_lastmodifieddate': at.isoformat().replace('+00:00', 'Z'), 'hs_call_to_number': f'480555{n:04d}',
                                                'hs_call_disposition': 'DNC'}}


def test_hubspot_reads_contacts_and_calls_once_asks_for_certificate_fields(company, received, monkeypatch, clock, settings):
    settings.SYNC_BATCH_SIZE = 4
    same = DAY + timedelta(minutes=9)
    contacts = [hcontact(n, same) for n in range(1, 6)] + [hcontact(6, DAY + timedelta(minutes=12), trustedform_certificate_url=f'https://cert.trustedform.com/{CERT}')]
    api = FakeHubSpot(contacts, [hcall(1, DAY + timedelta(minutes=2))])
    monkeypatch.setattr(hs.HubSpot, 'call', lambda self, url, body=None: api(self, url, body))
    clock(DAY + timedelta(hours=1))
    drain(connect(company, 'hubspot', {'access_token': 'a', 'refresh_token': 'r'}))
    assert sorted(received) == sorted([f'contacts:{500 + n}' for n in range(1, 7)] + ['calls:901'])
    body = api.bodies[0]
    assert body['sorts'] == [{'propertyName': 'hs_lastmodifieddate', 'direction': 'ASCENDING'}]
    assert 'trustedform_certificate_url' in body['properties'] and 'jornaya_leadid' in body['properties'] and 'firstname' not in body['properties']
    assert CertificateClaim.objects.get().cert_ref == CERT
