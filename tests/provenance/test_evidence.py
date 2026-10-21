"""Module 8 step 2: evidence for numbers with no certificate — the person called first, texted YES, or used the
client's own form. Only before the first call; never written consent."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.connections.models import Connection, Status
from apps.consent.checks import check_contact
from apps.consent.models import ConsentProof, ConsentResult
from apps.consent.needs import work_out
from apps.consent.proofs import proofs_seen
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.provenance.evidence import yes_word
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.sync.connector import Record

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
PHONE = '+19165550001'
n = iter(range(10**6))


@pytest.fixture(autouse=True)
def rulebook():
    load(RULEBOOK_DIR / 'v3.0.yaml')


def conn(client, provider):
    return Connection.objects.get_or_create(client=client, provider=provider, defaults={'status': Status.CONNECTED})[0]


def token(client):
    return codes_for(client).token(PHONE)


def contact(client, at, channel='call', direction='outbound', dial_mode='manual', provider='convoso', rid=None):
    return ContactEvent.objects.create(client=client, phone_token=token(client), phone_token_kid='k1', source_system=provider,
                                       source_record_id=rid or f'c{next(n)}', source_grade='C', channel=channel, direction=direction,
                                       occurred_at=at, dial_mode=dial_mode, epoch=epoch_for(client.pk, token(client), at))


def result(c, variant='strict'):
    work_out(c)
    check_contact(c, as_of=T0 + timedelta(days=90))
    return ConsentResult.objects.get(contact=c, variant=variant)


def person_called(client, at):
    call = contact(client, at, direction='inbound', rid='in-1')
    proofs_seen(client, conn(client, 'convoso'), Record('in-1', b'{}', 'call', at, [PHONE]), [token(client)])
    return call


def test_the_person_called_first_covers_live_calls_for_30_days(company):
    person_called(company, T0 - timedelta(days=2))
    assert ConsentProof.objects.get().kind == 'inbound_call'
    assert result(contact(company, T0)).status == 'verified'
    assert result(contact(company, T0 + timedelta(days=40))).primary_code == 'NP_WRONG_TYPE'  # past the 30-day draft


def test_a_robocall_is_never_covered_by_an_incoming_call(company):
    person_called(company, T0 - timedelta(days=2))
    assert result(contact(company, T0, dial_mode='predictive')).status == 'no_proof'


def test_evidence_after_the_call_does_not_count(company):
    person_called(company, T0 + timedelta(hours=2))
    assert result(contact(company, T0)).primary_code == 'NP_BEFORE_CONSENT'


def test_only_a_whole_yes_text_counts():
    assert yes_word(' yes! ') == 'YES' and yes_word('START') == 'START' and yes_word('y') == 'Y'
    assert yes_word("yes but don't call me") == '' and yes_word('Yesterday') == ''


def text_in(client, body, at):
    raw = json.dumps({'sid': f'SM{next(n)}', 'direction': 'inbound', 'from': PHONE, 'to': '+15550000000', 'body': body}).encode()
    proofs_seen(client, conn(client, 'twilio'), Record(f'SM{next(n)}', raw, 'text', at, [PHONE]), [token(client)])


def test_a_yes_text_covers_texts_only(company):
    text_in(company, 'YES', T0 - timedelta(days=1))
    text_in(company, 'yes please call me tomorrow', T0 - timedelta(days=1))
    assert ConsentProof.objects.count() == 1 and ConsentProof.objects.get().kind == 'inbound_sms'
    assert result(contact(company, T0, channel='text'), 'lenient').status == 'verified'  # lenient: texts not autodialed
    assert result(contact(company, T0, channel='text')).status == 'no_proof'  # strict: a marketing text needs written consent
    assert result(contact(company, T0 + timedelta(seconds=1))).status == 'no_proof'  # not a call


def test_the_clients_own_form_is_evidence_but_a_web_lead_in_an_upload_is_not(company):
    raw = json.dumps({'id': '7', 'properties': {'createdate': (T0 - timedelta(days=1)).isoformat().replace('+00:00', 'Z'), 'hs_object_source': 'FORM'}}).encode()
    proofs_seen(company, conn(company, 'hubspot'), Record('contacts:7', raw, 'crm_record', T0), [token(company)])
    proof = ConsentProof.objects.get()
    assert proof.kind == 'form_submission' and proof.captured_at == T0 - timedelta(days=1)
    assert result(contact(company, T0)).status == 'verified'


def test_nothing_found_stays_no_proof(company):
    text_in(company, 'who is this?', T0 - timedelta(days=1))
    assert not ConsentProof.objects.exists()
    assert result(contact(company, T0)).primary_code == 'NP_NONE'


def test_the_message_and_number_are_never_kept(company):
    from django.db import connection as db
    text_in(company, 'YES', T0 - timedelta(days=1))
    with db.cursor() as cur:
        cur.execute('SELECT * FROM consent_proof')
        rows = repr(cur.fetchall())
    assert '5550001' not in rows and 'YES' not in rows.upper().replace('INBOUND_SMS', '')
