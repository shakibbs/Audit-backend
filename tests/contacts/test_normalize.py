"""Every tool's call or text becomes the same contact shape; records are built by the real adapters' own code."""
import json
from datetime import UTC, date, datetime
from email.utils import format_datetime
from zoneinfo import ZoneInfo

import pytest
from django.db import connection as db

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import normalize_record
from apps.sync.connector import Record
from apps.sync.connectors import convoso as cv
from apps.sync.connectors import five9 as f9
from apps.sync.connectors import hubspot as hs
from apps.sync.connectors import salesforce as sf
from apps.sync.connectors import twilio as tw
from apps.sync.connectors import vicidial as vd
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
AT = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)


def conn(company, provider, creds=None):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider=provider, status=Status.CONNECTED)
    c.set_credentials(creds or {'account': 'a', 'key': 'k', 'secret': 'America/New_York'})
    c.save()
    return c


def save(company, provider, record, creds=None):
    normalize_record(company, conn(company, provider, creds), record, [])
    return ContactEvent.objects.get(source_record_id=record.source_record_id)


def test_twilio_outbound_text_and_inbound_call(company):
    c = conn(company, 'twilio')
    adapter = tw.Twilio(c)
    text = {'sid': 'SM1', 'date_sent': format_datetime(AT), 'date_created': format_datetime(AT), 'to': '+19165550001',
            'from': '+14805550000', 'body': 'Hi, your solar quote', 'status': 'delivered', 'direction': 'outbound-api'}
    normalize_record(company, c, adapter.record(text, tw.TEXTS), [])
    call = {'sid': 'CA1', 'start_time': format_datetime(AT), 'end_time': format_datetime(AT.replace(minute=31)), 'date_created': format_datetime(AT),
            'to': '+14805550000', 'from': '+19165550002', 'status': 'completed', 'duration': '42', 'direction': 'inbound'}
    normalize_record(company, c, adapter.record(call, tw.CALLS), [])
    t, k = ContactEvent.objects.get(source_record_id='SM1'), ContactEvent.objects.get(source_record_id='CA1')
    assert (t.channel, t.direction, t.sms_status, t.occurred_at, t.source_grade) == ('text', 'outbound', 'delivered', AT, 'C')
    assert (k.channel, k.direction, k.length_seconds, k.answered) == ('call', 'inbound', 42, True)
    assert k.phone_token != t.phone_token and len(k.phone_token) == 64 and k.caller_id_token  # person vs caller ID, as codes


def test_convoso_call_in_los_angeles_time(company):
    c = conn(company, 'convoso', {'key': 'k', 'secret': 'America/Los_Angeles'})
    row = {'id': '9001', 'lead_id': '77', 'campaign': 'SP-Q3-Roof', 'phone_number': '9165550001', 'caller_id_displayed': '4805550000',
           'status': 'NI', 'call_length': '0', 'call_type': 'OUTBOUND', 'user_id': '12',
           'call_date': AT.astimezone(ZoneInfo('America/Los_Angeles')).strftime(cv.WHEN)}
    normalize_record(company, c, cv.Convoso(c).record(row), [])
    e = ContactEvent.objects.get()
    assert (e.occurred_at, e.direction, e.disposition, e.answered, e.campaign, e.agent_id, e.lead_id) == (AT, 'outbound', 'NI', False, 'SP-Q3-Roof', '12', '77')


def test_five9_call_in_new_york_time(company):
    c = conn(company, 'five9')
    row = {'CALL ID': '3001', 'TIMESTAMP': AT.astimezone(ZoneInfo('America/New_York')).strftime('%a, %d %b %Y %H:%M:%S'), 'CAMPAIGN': 'Roof',
           'CALL TYPE': 'Outbound', 'DISPOSITION': 'Not Interested', 'ANI': '4805550000', 'DNIS': '9165550001', 'LENGTH': '00:01:05', 'AGENT': 'ana'}
    normalize_record(company, c, f9.Five9(c).record(row), [])
    e = ContactEvent.objects.get()
    assert (e.occurred_at, e.length_seconds, e.answered, e.disposition, e.agent_id) == (AT, 65, True, 'Not Interested', 'ana')


def test_vicidial_inbound_call_from_epoch(company):
    c = conn(company, 'vicidial', {'account': 'db/asterisk', 'key': 'u', 'secret': 'p'})
    row = {'closecallid': 5, 'uniqueid': 'x', 'lead_id': 9, 'campaign_id': 'INBOUND', 'start_epoch': int(AT.timestamp()),
           'end_epoch': int(AT.timestamp()) + 30, 'length_in_sec': 30, 'status': 'SALE', 'phone_code': '1', 'phone_number': '9165550001', 'user': 'agent7'}
    normalize_record(company, c, vd.Vicidial(c).record(row, vd.INBOUND), [])
    e = ContactEvent.objects.get()
    assert (e.direction, e.occurred_at, e.ended_at.second, e.length_seconds, e.disposition) == ('inbound', AT, 30, 30, 'SALE')


def test_crm_calls_count_crm_people_do_not(company):
    c = conn(company, 'hubspot', {'access_token': 'a'})
    call = {'id': '901', 'properties': {'hs_lastmodifieddate': AT.isoformat(), 'hs_call_direction': 'OUTBOUND', 'hs_call_to_number': '9165550001',
                                        'hs_call_from_number': '4805550000', 'hs_call_duration': '65000', 'hs_call_disposition': 'f240bbac'}}
    person = {'id': '501', 'properties': {'hs_lastmodifieddate': AT.isoformat(), 'phone': '9165550001'}}
    adapter = hs.HubSpot(c)
    normalize_record(company, c, adapter.record(call, hs.OBJECTS[1]), [])
    normalize_record(company, c, adapter.record(person, hs.OBJECTS[0]), [])
    s = conn(company, 'salesforce', {'access_token': 'a'})
    normalize_record(company, s, sf.Salesforce(s).record({'Id': '00Q1', 'SystemModstamp': AT.strftime('%Y-%m-%dT%H:%M:%S.000+0000'), 'Phone': '9165550001'}, sf.OBJECTS[0]), [])
    assert list(ContactEvent.objects.values_list('source_record_id', 'length_seconds')) == [('calls:901', 65)]


def test_a_changed_record_updates_its_contact_not_a_second_row(company):
    c = conn(company, 'convoso', {'key': 'k', 'secret': 'America/New_York'})
    row = {'id': '9001', 'phone_number': '9165550001', 'status': 'NI', 'call_length': '20', 'call_date': '2026-10-01 11:30:00'}
    normalize_record(company, c, cv.Convoso(c).record(row), [])
    normalize_record(company, c, cv.Convoso(c).record({**row, 'status': 'DNC'}), [])
    assert list(ContactEvent.objects.values_list('disposition', flat=True)) == ['DNC']


def test_unknown_stays_unknown(company):
    c = conn(company, 'convoso', {'key': 'k', 'secret': 'America/New_York'})
    normalize_record(company, c, cv.Convoso(c).record({'id': '1', 'phone_number': '9165550001', 'call_date': '2026-10-01 11:30:00'}), [])
    e = ContactEvent.objects.get()
    assert e.answered is None and e.length_seconds is None and e.prerecorded_or_ai is None and e.dial_mode == ''


def test_not_a_phone_number_or_unreadable_is_skipped(company):
    c = conn(company, 'convoso', {'key': 'k', 'secret': 'America/New_York'})
    normalize_record(company, c, Record('1', json.dumps({'id': '1', 'phone_number': '12'}).encode(), 'call', AT), [])
    normalize_record(company, c, Record('2', b'not json', 'call', AT), [])
    assert ContactEvent.objects.count() == 0


def test_no_number_or_message_text_is_stored(company):
    c = conn(company, 'twilio')
    text = {'sid': 'SM9', 'date_sent': format_datetime(AT), 'date_created': format_datetime(AT), 'to': '+19165550001',
            'from': '+14805550000', 'body': 'Please stop texting me', 'status': 'received', 'direction': 'inbound'}
    normalize_record(company, c, tw.Twilio(c).record(text, tw.TEXTS), [])
    with db.cursor() as cur:
        cur.execute('SELECT * FROM contact_event')
        dump = repr(cur.fetchall())
    assert '9165550001' not in dump and '4805550000' not in dump and 'stop texting' not in dump


def test_contacts_are_locked_per_client(company, other_company):
    for client in (company, other_company):
        c = conn(client, 'convoso', {'key': 'k', 'secret': 'America/New_York'})
        normalize_record(client, c, cv.Convoso(c).record({'id': '1', 'phone_number': '9165550001', 'call_date': '2026-10-01 11:30:00'}), [])
    with _scope('client', str(company.pk)):
        assert list(ContactEvent.objects.values_list('client_id', flat=True)) == [company.pk]


def test_every_synced_record_reaches_the_normalizer():
    from apps.sync import handoff
    assert normalize_record in handoff.RECEIVERS
