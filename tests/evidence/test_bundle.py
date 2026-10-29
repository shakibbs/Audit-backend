"""Module 14 step 3: bulk export (up to 25 numbers, one ZIP, numbers never stored) and the certification pack."""
import datetime
import io
import json
import uuid
import zipfile

import pytest
from django.utils import timezone

from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.evidence import bundle
from apps.ledger.models import Fingerprint
from apps.reports.words import banned_words
from apps.rulebook.loader import RULEBOOK_DIR, load

pytestmark = pytest.mark.django_db
WHEN = timezone.now() - datetime.timedelta(days=1)
PHONE = '+19165550142'


@pytest.fixture(autouse=True)
def number(company):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    token = codes_for(company).token(PHONE)
    ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='vicidial', source_record_id='call-1',
                                source_grade='B', channel='call', direction='outbound', occurred_at=WHEN, masked_label='(916) •••-0142')
    Fingerprint.objects.create(client=company, job_id=uuid.uuid4(), source_system='vicidial', source_record_id='call-1', content_kind='call',
                               source_grade='B', sha256='e' * 64, fetched_at=WHEN)


def post(api, body):
    return api.call('post', '/api/evidence-bundle', body)


def test_one_zip_with_each_file_and_the_numbers_not_found(company, admin_user, signed_in):
    reply = post(signed_in(admin_user), {'numbers': [PHONE, '+14805550923']})
    assert reply.status_code == 200 and reply['Content-Type'] == 'application/zip' and reply['X-Not-Found'] == '1'
    z = zipfile.ZipFile(io.BytesIO(reply.content))
    names = z.namelist()
    assert sum(n.endswith('.pdf') for n in names) == 1 and sum(n.endswith('.json') for n in names) == 1
    assert '0923' in z.read('not-found.txt').decode() and not any(n.startswith('certification/') for n in names)
    assert PHONE not in json.dumps([z.read(n).decode('utf-8', 'ignore') for n in names if n.endswith('.json')])


def test_the_certification_pack(company, admin_user, signed_in):
    z = zipfile.ZipFile(io.BytesIO(post(signed_in(admin_user), {'numbers': [PHONE], 'pack': True}).content))
    rows = z.read('certification/fingerprint-list.csv').decode().splitlines()
    assert rows[0].startswith('company,number,record,tool,record_id') and company.name in rows[1] and 'e' * 64 in rows[1] and '(916) •••-0142' in rows[1]
    assert z.read('certification/custodian-declaration-DRAFT.txt').decode().startswith('DRAFT · for counsel to review')
    assert 'Merkle tree' in z.read('certification/how-civ-captures-records.txt').decode()


def test_the_pack_texts_pass_the_banned_word_check():
    assert banned_words(bundle.HOW_CIV_CAPTURES + bundle.HOW_TO_CHECK + bundle.CUSTODIAN_TEMPLATE) == []


def test_every_pack_text_names_the_client(company, admin_user, signed_in):
    """Owner, 2026-10-30: formal wording, and the client's name in every file of the pack."""
    z = zipfile.ZipFile(io.BytesIO(post(signed_in(admin_user), {'numbers': [PHONE, '+14805550923'], 'pack': True}).content))
    for name in z.namelist():
        if name.endswith(('.txt', '.csv')):
            got = z.read(name).decode()
            assert company.name in got and '{company}' not in got, name


def test_limits_and_who_can(company, admin_user, member_user, signed_in):
    assert post(signed_in(member_user), {'numbers': [PHONE]}).status_code == 403
    api = signed_in(admin_user)
    assert post(api, {'numbers': []}).status_code == 400
    assert post(api, {'numbers': [f'+1916555{i:04d}' for i in range(26)]}).status_code == 400
