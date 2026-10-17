"""Each tool's own total for records completeness, asked in one request (pretend tools, from the vendors' docs)."""
from datetime import UTC, datetime

import pytest

from apps.connections.models import Connection, Status
from apps.sync.connectors import convoso as cv
from apps.sync.connectors import five9 as f9
from apps.sync.connectors import hubspot as hs
from apps.sync.connectors import salesforce as sf
from apps.sync.connectors import vicidial as vd

pytestmark = pytest.mark.django_db
START, END = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)


def connect(company, provider, creds):
    c = Connection(client=company, provider=provider, status=Status.CONNECTED)
    c.set_credentials(creds)
    c.save()
    return c


def test_convoso_total_found(company, monkeypatch):
    asked = []
    monkeypatch.setattr(cv.Convoso, '_get', lambda self, path, params: asked.append((path, params)) or {'total_found': '5000', 'results': [{}]})
    tool = cv.Convoso(connect(company, 'convoso', {'key': 't', 'secret': 'America/New_York'}))
    assert tool.count_between('calls', START, END) == 5000
    path, params = asked[0]
    assert path == 'log/retrieve' and params['limit'] == 1 and params['start_time'] == '2026-08-31 20:00:00'  # account time zone


def test_vicidial_counts_both_call_tables(company, monkeypatch):
    sent = []
    monkeypatch.setattr(vd.Vicidial, 'query', lambda self, sql, params: sent.append(sql) or [{'n': 300 if 'closer' in sql else 4700}])
    tool = vd.Vicidial(connect(company, 'vicidial', {'account': 'db.example:3306/asterisk', 'key': 'r', 'secret': 'p'}))
    assert tool.count_between('calls', START, END) == 5000
    assert all(s.startswith('SELECT COUNT(*)') for s in sent) and len(sent) == 2


def test_five9_counts_the_report_rows(company, monkeypatch):
    monkeypatch.setattr(f9.Five9, 'report_csv', lambda self, start, end: 'CALL ID,TIMESTAMP\n1,x\n2,y\n,\n3,z\n')
    tool = f9.Five9(connect(company, 'five9', {'account': 'u', 'key': 'p', 'secret': 'America/New_York'}))
    assert tool.count_between('calls', START, END) == 3


def test_salesforce_counts_leads_and_contacts_created(company, monkeypatch):
    asked = []
    monkeypatch.setattr(sf.Salesforce, 'call', lambda self, url, body=None: asked.append(url) or {'totalSize': 200 if 'Lead' in url else 110})
    tool = sf.Salesforce(connect(company, 'salesforce', {'access_token': 'a', 'refresh_token': 'r', 'instance_url': 'https://x.my.salesforce.com'}))
    assert tool.count_between('crm_records', START, END) == 310
    assert all('SELECT+COUNT%28%29' in url and 'CreatedDate' in url for url in asked)


def test_hubspot_counts_contacts_and_calls(company, monkeypatch):
    asked = []
    monkeypatch.setattr(hs.HubSpot, 'call', lambda self, url, body=None: asked.append((url, body)) or {'total': 42, 'results': []})
    tool = hs.HubSpot(connect(company, 'hubspot', {'access_token': 'a', 'refresh_token': 'r'}))
    assert tool.count_between('crm_records', START, END) == 42 and tool.count_between('calls', START, END) == 42
    (contacts_url, contacts_body), (calls_url, calls_body) = asked
    assert contacts_url.endswith('/contacts/search') and contacts_body['filterGroups'][0]['filters'][0]['propertyName'] == 'createdate'
    assert calls_url.endswith('/calls/search') and calls_body['filterGroups'][0]['filters'][0]['propertyName'] == 'hs_timestamp'
