"""Module 14 step 1: a number's evidence file — what the number page shows plus every record's fingerprint, source,
fetch time, seal and seal check; PDF or JSON; Admins and the lawyer only; the banned-word check; masked number only."""
import datetime
import uuid

import pytest
from django.utils import timezone

from apps.access_log.models import AccessEntry
from apps.anchoring import stamps
from apps.anchoring.seal import seal_day
from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent
from apps.evidence.file import build
from apps.ledger.models import Fingerprint
from apps.rulebook.loader import RULEBOOK_DIR, load

pytestmark = pytest.mark.django_db
YESTERDAY = timezone.now() - datetime.timedelta(days=1)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    monkeypatch.setattr(stamps, 'tsa_stamp', lambda root: ('https://tsa.test', b'signed', YESTERDAY))
    monkeypatch.setattr(stamps, 'ots_stamp', lambda root: ('https://ots.test', b'pending'))


@pytest.fixture
def number(company):
    c = ContactEvent.objects.create(client=company, phone_token='ab' * 32, phone_token_kid='k1', source_system='vicidial', source_record_id='outbound:77',
                                    source_grade='B', channel='call', direction='outbound', occurred_at=YESTERDAY, masked_label='(916) •••-0142')
    Fingerprint.objects.create(client=company, job_id=uuid.uuid4(), source_system='vicidial', source_record_id='outbound:77', content_kind='call',
                               source_grade='B', sha256='f' * 64, fetched_at=YESTERDAY)
    seal_day(company, YESTERDAY.date())
    return number_ref(c.phone_token)


def test_the_file_holds_the_page_and_every_fingerprint_with_its_seal(company, number):
    data = build(company, number)
    assert data['number'] == '(916) •••-0142' and 'not held by CiV' in data['note'] and len(data['contacts']) == 1
    fp = data['fingerprints'][0]
    assert (fp['tool'], fp['record'], fp['sha256'], fp['check']) == ('vicidial', 'outbound:77', 'f' * 64, 'Matches its seal')
    assert fp['seal']['root'] and fp['seal']['path'] is not None and fp['seal']['timestamp']
    assert build(company, 'p-' + '0' * 24) is None


def test_admins_download_pdf_or_json_and_it_is_logged(company, number, admin_user, signed_in):
    api = signed_in(admin_user)
    pdf = api.get(f'/api/evidence-file/{number}')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF') and 'no-store' in pdf['Cache-Control']
    js = api.get(f'/api/evidence-file/{number}?format=json')
    assert js['Content-Type'] == 'application/json' and b'Matches its seal' in js.content
    assert AccessEntry.objects.filter(action='evidence_file_downloaded').count() == 2


def test_members_cannot_and_the_lawyer_can(company, number, member_user, signed_in, api):
    assert signed_in(member_user).get(f'/api/evidence-file/{number}').status_code == 403
    member_user.is_counsel = True
    member_user.save()
    assert api.get(f'/api/evidence-file/{number}').status_code == 200


def test_a_banned_word_holds_the_file_back(company, number, admin_user, signed_in, monkeypatch):
    monkeypatch.setattr('apps.evidence.file.DISCLAIMER', 'This file is court-ready.')
    assert signed_in(admin_user).get(f'/api/evidence-file/{number}').status_code == 409
    assert AccessEntry.objects.filter(action='evidence_file_blocked').exists()
