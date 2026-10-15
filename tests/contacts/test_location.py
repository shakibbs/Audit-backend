"""Where the person probably is: state, possible time zones, country, confidence, local time."""
from datetime import UTC, date, datetime

import pytest

from apps.connections.models import Connection, Status
from apps.contacts.location import locate, state_code
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import normalize_record
from apps.sync.connectors import convoso as cv


@pytest.mark.parametrize('number, state, zones, confidence, non_us', [
    ('+19165550001', 'CA', ['America/Los_Angeles'], 'medium', False),  # Sacramento
    ('+13055550001', 'FL', ['America/New_York'], 'medium', False),  # Miami
    ('+18505550001', 'FL', ['America/Chicago', 'America/New_York'], 'low', False),  # panhandle: two zones
    ('+12195550001', 'IN', ['America/Chicago'], 'medium', False),  # Gary, corrected to Central
    ('+12085550001', 'ID', ['America/Boise', 'America/Los_Angeles'], 'low', False),
    ('+19155550001', 'TX', ['America/Denver'], 'medium', False),  # El Paso is Mountain
    ('+18765550001', '', ['America/Jamaica'], 'medium', True),
    ('+14165550001', '', ['America/Toronto'], 'medium', True),
    ('+17875550001', '', ['America/Puerto_Rico'], 'medium', False),  # US territory: not "outside the US"
])
def test_area_code_location(number, state, zones, confidence, non_us):
    found = locate(number)
    assert (found['recipient_state'], found['time_zones'], found['location_confidence'], found['is_non_us']) == (state, zones, confidence, non_us)
    assert found['location_source'] == 'area_code'


def test_states_and_unknowns():
    assert state_code('New York, NY') == 'NY' and state_code('California') == 'CA' and state_code('Ontario') == ''
    assert locate('not a number')['time_zones'] == [] and locate('not a number')['location_confidence'] == 'low'


@pytest.mark.django_db
def test_contacts_get_their_location_and_local_time(company):
    company.start_date = date(2026, 10, 1)
    company.save()
    c = Connection(client=company, provider='convoso', status=Status.CONNECTED)
    c.set_credentials({'key': 'k', 'secret': 'America/New_York'})
    c.save()
    # 8:30pm in New York, to a Sacramento number and to a Florida panhandle number.
    for n, number in ((1, '9165550001'), (2, '8505550002')):
        normalize_record(company, c, cv.Convoso(c).record({'id': str(n), 'phone_number': number, 'call_date': '2026-10-01 20:30:00'}), [])
    ca, fl = ContactEvent.objects.get(source_record_id='1'), ContactEvent.objects.get(source_record_id='2')
    assert ca.occurred_at == datetime(2026, 10, 2, 0, 30, tzinfo=UTC)
    assert [t.strftime('%H:%M') for t in ca.local_times()] == ['17:30']  # 5:30pm for the person in California
    assert [t.strftime('%H:%M') for t in fl.local_times()] == ['19:30', '20:30']  # 7:30pm Central or 8:30pm Eastern: unsure
    assert (ca.recipient_state, ca.location_confidence, fl.location_confidence) == ('CA', 'medium', 'low')
