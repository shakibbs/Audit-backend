"""Card coverage, batch 2: the Upload centre works. Files are kept write-once and fingerprinted, rows are read into
their tables (numbers as phone codes only), and the lists change what the consent engine and the number page say."""
import hashlib
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection as db
from django.utils import timezone

from apps.consent.needs import profile
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import RuleSet
from apps.uploads.effects import purge_old
from apps.uploads.models import Complaint, DncCheck, InternalListEntry, RndQuery, TrainingRecord, UploadedFile
from apps.uploads.read import to_date
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db
TODAY = timezone.now().date()


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    load(RULEBOOK_DIR / 'v3.0.yaml')


def send(user, source, name, body: str):
    api = browser_for(user)
    return api, api.post('/api/uploads', {'source': source, 'file': SimpleUploadedFile(name, body.encode())},
                         HTTP_X_CSRFTOKEN=api.cookies['csrftoken'].value)


def test_an_internal_list_is_kept_fingerprinted_and_read(company, admin_user):
    body = 'Phone Number,Date Added\n(916) 555-0001,2026-09-01\n916-555-0002,\nnot a phone,2026-09-01\n'
    api, reply = send(admin_user, 'Internal do-not-contact list', 'internal-dnc.csv', body)
    data = reply.json()
    assert reply.status_code == 200 and (data['rowsRead'], data['rowsRejected']) == (2, 1)
    assert data['sha256'] == hashlib.sha256(body.encode()).hexdigest() and data['source'] == 'Internal do-not-contact list'
    upload = UploadedFile.objects.get()
    assert upload.file and InternalListEntry.objects.count() == 2
    assert InternalListEntry.objects.get(phone_token=codes_for(company).token('+19165550002')).added_on == TODAY  # no date: the upload day
    assert api.get('/api/uploads').json()[0]['fileName'] == 'internal-dnc.csv'
    source = next(s for s in api.get('/api/sources').json() if s['name'] == 'Internal do-not-contact list')
    assert source['status'] == 'current' and source['feeds'] == ['IDN']
    with db.cursor() as cur:
        cur.execute('SELECT * FROM internal_list_entry')
        assert '5550001' not in repr(cur.fetchall())


def test_dnc_rnd_complaints_and_training_are_read(company, admin_user):
    send(admin_user, 'DNC check records', 'dnc.csv', 'phone,scrub date,result,list\n9165550001,10/01/2026,Listed,National\n9165550002,2026-10-01,clean,\n')
    send(admin_user, 'Reassigned-number query logs', 'rnd.csv', 'TN,Query Date,Response\n9165550001,2026-09-30,No\n9165550003,2026-09-30,No data\n')
    send(admin_user, 'Complaint log', 'complaints.csv', 'date received,resolved,channel,phone\n2026-09-02,2026-09-05,email,9165550004\n2026-09-10,,phone,\n')
    send(admin_user, 'Policies, training, contracts', 'training.csv', 'Agent ID,Completed\nA-17,2026-08-01\nA-18,2026-08-03\n')
    assert sorted(DncCheck.objects.values_list('listed', 'list_name')) == [(False, 'national'), (True, 'National')]
    assert sorted(RndQuery.objects.values_list('result', flat=True)) == ['no', 'no_data']
    assert Complaint.objects.count() == 2 and Complaint.objects.filter(resolved_on__isnull=True).count() == 1
    assert TrainingRecord.objects.count() == 2 and 'A-17' not in TrainingRecord.objects.first().agent_ref


def test_a_policy_document_is_kept_without_rows(company, admin_user):
    _, reply = send(admin_user, 'Policies, training, contracts', 'tcpa-policy.pdf', '%PDF-1.7 policy')
    assert reply.status_code == 200 and (reply.json()['rowsRead'], reply.json()['rowsRejected']) == (0, 0)


def test_only_admins_and_the_lawyer_upload_and_bad_files_are_refused(company, member_user, admin_user):
    assert send(member_user, 'Complaint log', 'c.csv', 'date\n2026-09-01\n')[1].status_code == 403
    assert send(admin_user, 'Complaint log', 'c.exe', 'x')[1].status_code == 400
    assert send(admin_user, 'Nothing like this', 'c.csv', 'x')[1].status_code == 400


def contact(company, number, days_ago=1):
    token = codes_for(company).token(number)
    at = timezone.now() - timedelta(days=days_ago)
    return ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='convoso', source_record_id=f'c{number}',
                                       source_grade='C', channel='call', direction='outbound', occurred_at=at, dial_mode='manual',
                                       masked_label='(916) •••-0001', epoch=epoch_for(company.pk, token, at))


def bases(c):
    return [b['basis'] for b in profile(c, RuleSet(), 'strict')['bases']]


def test_the_lists_decide_the_do_not_call_need(company, admin_user):
    listed, clean, unknown = contact(company, '+19165550001'), contact(company, '+19165550002'), contact(company, '+19165550009')
    send(admin_user, 'DNC check records', 'dnc.csv', f'phone,checked,listed\n9165550001,{TODAY - timedelta(days=5)},yes\n9165550002,{TODAY - timedelta(days=5)},no\n')
    assert 'dnc_listed' in bases(listed)
    assert 'dnc_listed' not in bases(clean) and 'dnc_unknown' not in bases(clean)  # checked within 31 days, not listed
    assert 'dnc_unknown' in bases(unknown)  # no check covers it
    send(admin_user, 'Internal do-not-contact list', 'internal.csv', f'phone,added\n9165550009,{TODAY - timedelta(days=10)}\n')
    assert 'dnc_listed' in bases(unknown)


def test_the_number_page_shows_both_list_checks(company, admin_user, member_user):
    c = contact(company, '+19165550001')
    send(admin_user, 'DNC check records', 'dnc.csv', f'phone,checked,listed\n9165550001,{TODAY},yes\n')
    send(admin_user, 'Internal do-not-contact list', 'internal.csv', f'phone,added\n9165550001,{TODAY - timedelta(days=3)}\n')
    api = browser_for(member_user)
    ref = api.get('/api/contacts').json()[0]['phoneE164']
    checks = {x['list']: x for x in api.get(f'/api/evidence/{ref}').json()['listChecks']}
    assert checks['Internal do-not-contact list']['onList'] is True and checks['DNC scrub records']['onList'] is True and c


def test_dates_in_common_shapes():
    assert to_date('2026-10-01') == to_date('10/01/2026') == to_date('2026-10-01T09:00:00Z') == to_date('20261001')
    assert to_date('soon') is None


def test_files_go_after_four_years(company, admin_user):
    send(admin_user, 'Complaint log', 'c.csv', 'date\n2026-09-01\n')
    UploadedFile.objects.update(received_at=timezone.now() - timedelta(days=365 * 4 + 2))
    assert purge_old() == 1 and not UploadedFile.objects.get().file and Complaint.objects.count() == 1
