"""Module 15 step 2: signed statements (Admins and lawyer) with conflicts from what CiV measured, never raising a
value; the monthly attestation snapshot (fields with source grades, worst cases, sha256, versions); a buyer reads a
company's attestation only while that company shares with it."""
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.buyers.attestation import build, save
from apps.buyers.models import AttestationSnapshot, BuyerLink, BuyerOrg, Statement
from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.tenancy.scope import buyer

pytestmark = pytest.mark.django_db
OCT = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def rules():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def after_stop(company):
    c = ContactEvent.objects.create(client=company, phone_token='p', phone_token_kid='k', source_system='twilio', source_record_id='m1',
                                    source_grade='C', channel='text', direction='outbound', occurred_at=timezone.now() - timedelta(days=2))
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', codes=['NP_AFTER_OPT_OUT'],
                                 evaluation_as_of=c.occurred_at, rulebook_version='3.0')


def test_statements_signed_with_conflicts_shown(company, admin_user, member_user, signed_in):
    after_stop(company)
    api = signed_in(admin_user)
    assert api.call('post', '/api/statements', {'topic': 'optouts_honored'}).status_code == 201
    assert api.call('post', '/api/statements', {'topic': 'other', 'text': 'All our calling runs through Five9.'}).status_code == 201
    assert signed_in(member_user).call('post', '/api/statements', {'topic': 'other', 'text': 'x'}).status_code == 403
    page = signed_in(admin_user).get('/api/insureds/own').json()
    assert page['conflicts'][0]['stated'] == 'We stop contacting people who opt out' and '1 contact after an opt-out' in page['conflicts'][0]['observed']
    assert page['statements'] == ['All our calling runs through Five9.'] and page['signedBy'] == admin_user.name
    rows = {r['topic']: r for r in page['statementRows']}
    assert rows['other']['note'] == 'Info only: CiV cannot check this'
    sid = rows['other']['id']
    assert api.call('post', f'/api/statements/{sid}/withdraw').json()['withdrawn']
    assert api.get('/api/insureds/own').json()['statements'] == []


def test_the_dnc_statement_conflicts_without_check_records(company, admin_user, signed_in):
    signed_in(admin_user).call('post', '/api/statements', {'topic': 'dnc_checked'})
    assert 'No DNC check records supplied' in build(company, OCT)['insuredStates']['conflicts'][0]['observed']


def test_the_snapshot_has_grades_and_is_kept_by_version(company):
    after_stop(company)
    first = save(company, OCT, now=datetime(2026, 10, 20, tzinfo=UTC))
    body = first.payload
    assert body['schema'] == 'civ.attestation.v1' and body['frequencyDrivers']['contactsAfterOptOut'] == {'value': 1, 'grade': 'C', 'worstCase': False}
    assert len(first.sha256) == 64 and 'phone' not in str(body).lower().replace('telephone', '')
    assert save(company, OCT, now=datetime(2026, 10, 21, tzinfo=UTC)) is None  # nothing changed
    Statement.objects.create(client=company, topic='other', text='We train every agent.', signed_by='Dana')
    assert save(company, OCT, now=datetime(2026, 10, 22, tzinfo=UTC)).version == 1  # open month: replaced
    locked = save(company, OCT, now=datetime(2026, 11, 7, tzinfo=UTC))
    assert locked is None and AttestationSnapshot.objects.get().locked
    Statement.objects.create(client=company, topic='other', text='We record every call.', signed_by='Dana')
    assert save(company, OCT, now=datetime(2026, 11, 8, tzinfo=UTC)).version == 2  # locked: a new version, the old kept
    assert AttestationSnapshot.objects.count() == 2


def test_a_buyer_reads_an_attestation_only_while_shared(company, other_company):
    save(company, OCT, now=datetime(2026, 10, 20, tzinfo=UTC))
    save(other_company, OCT, now=datetime(2026, 10, 20, tzinfo=UTC))
    falcon = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    link = BuyerLink.objects.create(org=falcon, client=company, granted_by='Dana')
    with buyer(falcon):
        assert [a.client_id for a in AttestationSnapshot.objects.all()] == [company.pk]
        assert Statement.objects.count() == 0  # the statements table itself stays the company's
    link.revoked_at = timezone.now()
    link.save()
    with buyer(falcon):
        assert not AttestationSnapshot.objects.exists()  # stopped sharing: gone at the next read
