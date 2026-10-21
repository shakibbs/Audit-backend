"""Module 14 step 2: the re-fetch check — the tool is asked for the record again (a pretend tool here) and its new
fingerprint compared with the sealed ones: matches · changed · gone · cannot; on demand and weekly; changed → alert."""
import datetime
import hashlib
import uuid

import pytest
from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.raise_ import refresh
from apps.connections.models import Connection, Status
from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent
from apps.evidence.file import build
from apps.evidence.models import RefetchCheck
from apps.evidence.refetch import check_records, weekly_sample
from apps.ledger.models import Fingerprint
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync import connector as connector_module
from apps.sync.connector import Connector, Record

pytestmark = pytest.mark.django_db
WHEN = timezone.now() - datetime.timedelta(days=1)
SOURCE = {}  # pretend tool: record ID → raw bytes now (missing = deleted)


class Pretend(Connector):
    def fetch_one(self, record_id):
        if record_id == 'no-single-read':
            raise NotImplementedError
        raw = SOURCE.get(record_id)
        return Record(record_id, raw, 'call', WHEN) if raw is not None else None


@pytest.fixture(autouse=True)
def tool(company, monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    SOURCE.clear()
    monkeypatch.setitem(connector_module.CONNECTORS, 'vicidial', Pretend)
    Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED)


def seen(company, record_id, raw: bytes, kind='call'):
    SOURCE[record_id] = raw
    Fingerprint.objects.create(client=company, job_id=uuid.uuid4(), source_system='vicidial', source_record_id=record_id, content_kind=kind,
                               source_grade='B', sha256=hashlib.sha256(raw).hexdigest(), fetched_at=WHEN)


def test_matches_changed_gone_and_cannot(company):
    seen(company, 'a', b'same')
    seen(company, 'b', b'before')
    SOURCE['b'] = b'after'  # edited at the source
    seen(company, 'c', b'x')
    del SOURCE['c']  # deleted at the source
    seen(company, 'no-single-read', b'y')
    results = {c.source_record_id: c.result for c in check_records(company, [('vicidial', r) for r in ('a', 'b', 'c', 'no-single-read')])}
    assert results == {'a': 'matches', 'b': 'changed', 'c': 'gone', 'no-single-read': 'cannot'}
    assert RefetchCheck.objects.get(source_record_id='a').matched is not None
    assert check_records(company, [('five9', 'z')])[0].result == 'cannot'  # no connection for that tool


def test_on_demand_for_a_number_and_it_shows_in_the_evidence_file(company, admin_user, member_user, signed_in):
    c = ContactEvent.objects.create(client=company, phone_token='cd' * 32, phone_token_kid='k1', source_system='vicidial', source_record_id='call-9',
                                    source_grade='B', channel='call', direction='outbound', occurred_at=WHEN, masked_label='(916) •••-0142')
    seen(company, 'call-9', b'the call')
    ref = number_ref(c.phone_token)
    assert signed_in(member_user).call('post', f'/api/evidence-file/{ref}/refetch').status_code == 403
    answer = signed_in(admin_user).call('post', f'/api/evidence-file/{ref}/refetch').json()
    assert answer == {'checked': 1, 'results': {'Matches what CiV saw': 1}}
    assert build(company, ref)['fingerprints'][0]['atSource']['result'] == 'Matches what CiV saw'


def test_weekly_sample_and_the_changed_alert(company):
    for i in range(3):
        seen(company, f'w{i}', f'r{i}'.encode())
    Fingerprint.objects.update(anchor=None)
    from apps.anchoring import stamps
    from apps.anchoring.seal import seal_day
    stamps.tsa_stamp = lambda root: ('https://tsa.test', b'signed', WHEN)
    stamps.ots_stamp = lambda root: ('https://ots.test', b'pending')
    seal_day(company, WHEN.date())
    SOURCE['w1'] = b'edited'
    assert weekly_sample(company, size=50) == 3
    refresh(company)
    alert = Alert.objects.get(kind='Records changed at the source')
    assert alert.title == '1 record changed in vicidial after CiV saw it' and alert.severity == 'Medium'
