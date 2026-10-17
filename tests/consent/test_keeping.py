"""Keeping results up to date: rechecks when something new arrives, the nightly time check, freezing, the history."""
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.certificates.models import CertificateClaim
from apps.connections.models import Connection, Status
from apps.consent.checks import check_contact
from apps.consent.keeping import recheck_pending, recheck_time_passed, run_rechecks, sweep_done, records_seen
from apps.consent.models import ConsentProof, ConsentResult, Recheck, ResultChange
from apps.consent.needs import work_out
from apps.consent.proofs import proofs_seen
from apps.contacts.epochs import epoch_for, split
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connector import Record

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
FAR = T0 + timedelta(days=1000)
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rulebook():
    return load(RULEBOOK_DIR / 'v3.0.yaml')[0]


def contact(client, at=T0, person='p1', rid=None):
    c = ContactEvent.objects.create(client=client, phone_token=person, phone_token_kid='k1', source_system='convoso',
                                    source_record_id=rid or f'r{next(n)}', source_grade='C', channel='call', direction='outbound',
                                    occurred_at=at, dial_mode='manual', recipient_state='CA', time_zones=['America/Los_Angeles'],
                                    epoch=epoch_for(client.pk, person, at))
    work_out(c)
    check_contact(c, as_of=T0)
    return c


def cert(client, created=T0 - timedelta(days=2), state='claimed', expires=FAR, person='p1', record='leads:1'):
    claim = CertificateClaim.objects.create(client=client, provider='trustedform', cert_ref=f'{next(n):040d}', state=state,
                                            deadline_at=created + timedelta(hours=72), cert_created_at=created if state == 'claimed' else None,
                                            cert_expires_at=expires if state == 'claimed' else None)
    return ConsentProof.objects.create(client=client, phone_token=person, epoch=epoch_for(client.pk, person, created), kind='certificate',
                                       proof_type='web_cert', certificate=claim, captured_at=created, date_known=state == 'claimed',
                                       source_system='salesforce', source_record_id=record)


def status(c, variant='strict'):
    return ConsentResult.objects.get(contact=c, variant=variant)


def test_a_certificate_read_later_turns_pending_into_verified_with_the_reason(company):
    proof = cert(company, state='waiting')
    c = contact(company)
    assert status(c).status == 'pending'
    CertificateClaim.objects.filter(pk=proof.certificate_id).update(state='claimed', cert_created_at=T0 - timedelta(days=2), cert_expires_at=FAR)
    assert recheck_pending() == 1
    r = status(c)
    assert (r.status, r.reeval_reason) == ('verified', 'certificate_read')
    change = ResultChange.objects.get(contact=c, variant='strict')
    assert (change.old_status, change.new_status, change.reason) == ('pending', 'verified', 'certificate_read')


def test_a_late_stop_makes_later_calls_no_proof(company):
    cert(company)
    before, after = contact(company, at=T0), contact(company, at=T0 + timedelta(days=2))
    assert status(after).status == 'verified'
    OptOutEvent.objects.create(client=company, phone_token='p1', at=T0 + timedelta(days=1), channel='text', method='keyword',
                               source_system='twilio', source_record_id='SM1')  # synced late
    assert Recheck.objects.filter(reason='late_opt_out').exists()
    run_rechecks()
    assert status(after).primary_code == 'NP_AFTER_OPT_OUT' and status(before).status == 'verified'
    assert not Recheck.objects.exists()


def test_a_new_owner_rechecks_calls_after_the_change(company):
    cert(company)
    old, new = contact(company, at=T0), contact(company, at=T0 + timedelta(days=5))
    split(company.pk, 'p1', T0 + timedelta(days=3), PhoneEpoch.Reason.WRONG_NUMBER)
    run_rechecks()
    assert status(old).status == 'verified'
    assert (status(new).primary_code, status(new).reeval_reason) == ('NP_NONE', 'owner_changed')


def test_a_new_proof_rechecks_that_number(company):
    c = contact(company)
    assert status(c).status == 'no_proof'
    conn = Connection.objects.create(client=company, provider='salesforce', status=Status.CONNECTED)
    claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref='a' * 40, state='claimed',
                                            deadline_at=T0, cert_created_at=T0 - timedelta(days=3), cert_expires_at=FAR)
    raw = json.dumps({'Id': '00Q1', 'TrustedForm_URL__c': 'https://cert.trustedform.com/' + 'a' * 40}).encode()
    proofs_seen(company, conn, Record('leads:00Q1', raw, 'lead', T0 - timedelta(days=3)), ['p1'])
    run_rechecks()
    assert (status(c).status, status(c).reeval_reason) == ('verified', 'new_proof') and claim.proofs.count() == 1


def test_a_rule_change_rechecks_only_from_its_date(company, rulebook):
    from apps.rulebook.signals import rules_changed
    cert(company)
    early, late = contact(company, at=T0), contact(company, at=T0 + timedelta(days=30))
    rules_changed.send(sender=None, from_date=date(2026, 10, 20))
    run_rechecks()
    assert status(late).reeval_reason == 'rule_changed' and status(early).reeval_reason == ''


def test_a_certificate_close_to_expiring_becomes_weak_in_the_nightly_run(company):
    cert(company, expires=timezone.now() + timedelta(days=10))
    c = contact(company)
    ConsentResult.objects.filter(contact=c).update(status='verified', primary_code='VF_OK')  # it was fine when first checked
    assert recheck_time_passed() == 1
    assert (status(c).primary_code, status(c).reeval_reason) == ('WK_RETENTION', 'time_passed')


def test_a_changed_call_record_freezes_its_result_and_it_is_never_recomputed(company):
    cert(company)
    c = contact(company, rid='call-9')
    conn = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    ContactEvent.objects.filter(pk=c.pk).update(occurred_at=T0 - timedelta(days=5))  # the tool rewrote the call's time
    from apps.consent.keeping import contact_seen
    contact_seen(company, conn, Record('call-9', b'{}', 'call', T0), ['p1'])
    r = status(c)
    assert r.frozen and r.frozen_reason == 'FZ_INPUTS_CHANGED' and r.status == 'verified'
    OptOutEvent.objects.create(client=company, phone_token='p1', at=T0 - timedelta(days=10), channel='text', method='keyword',
                               source_system='twilio', source_record_id='SM2')
    run_rechecks()
    assert status(c).status == 'verified'  # frozen: never recomputed
    assert ResultChange.objects.filter(contact=c, reason='frozen').count() == 2  # strict and lenient


def test_a_record_the_weekly_check_did_not_find_freezes_as_deleted(company):
    cert(company, record='leads:gone')
    kept, gone = contact(company, rid='call-1'), contact(company, rid='call-2')
    conn = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    started = timezone.now()
    records_seen(company, conn, ['call-1'])
    sweep_done(conn, started)
    assert not status(kept).frozen
    assert status(gone).frozen and status(gone).frozen_reason == 'FZ_SOURCE_DELETED'


def test_a_deleted_proof_record_withdraws_the_proof_and_freezes_what_used_it(company):
    proof = cert(company, record='leads:gone')
    c = contact(company)
    sf = Connection.objects.create(client=company, provider='salesforce', status=Status.CONNECTED)
    sweep_done(sf, timezone.now())
    proof.refresh_from_db()
    assert proof.withdrawn_at is not None and status(c).frozen and status(c).frozen_reason == 'FZ_SOURCE_DELETED'
    later = contact(company, at=T0 + timedelta(days=1))
    assert status(later).primary_code == 'NP_NONE'  # a withdrawn proof is never used again


def test_no_conclusion_from_a_full_check_with_no_start_time(company):
    c = contact(company)
    conn = Connection.objects.create(client=company, provider='convoso', status=Status.CONNECTED)
    sweep_done(conn, None)
    assert not status(c).frozen
