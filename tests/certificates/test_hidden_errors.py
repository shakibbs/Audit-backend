"""Super test 2026-10-23: Jornaya answers "OK" with the error written inside. That is a refused key, never "the key
works" and never a claimed certificate. Convoso's test reads the time zone from the Time zone box."""
import io
import urllib.error
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.certificates import claim as claims
from apps.certificates import vendors
from apps.certificates.models import CertificateClaim
from apps.connections import testers
from apps.connections.models import Connection, Status
from tests.certificates.test_claims import Reply, vendor_answers

pytestmark = pytest.mark.django_db
JORNAYA_ERROR = {'error': {'code': 2001, 'message': 'Malformed account code'}}


def test_jornaya_error_inside_an_ok_answer_is_a_refused_key(monkeypatch):
    vendor_answers(monkeypatch, JORNAYA_ERROR)
    status, message = testers.test_jornaya({'account': 'QA', 'key': 'fake'})
    assert status == Status.FAILED and 'refused' in message
    with pytest.raises(vendors.Refused):
        vendors.read_jornaya('A1B2C3D4-1111-2222-3333-444455556666', 'QA', 'fake')


def test_a_claim_with_a_refused_jornaya_key_is_never_marked_claimed(company, monkeypatch):
    conn = Connection(client=company, provider='jornaya', status=Status.CONNECTED)
    conn.set_credentials({'account': 'QA', 'key': 'fake'})
    conn.save()
    claim = CertificateClaim.objects.create(client=company, provider='jornaya', cert_ref='A1B2C3D4-1111-2222-3333-444455556666',
                                            deadline_at=timezone.now() + timedelta(days=3))
    vendor_answers(monkeypatch, JORNAYA_ERROR)
    claims.claim_one(claim)
    claim.refresh_from_db()
    assert claim.state != CertificateClaim.State.CLAIMED and claim.last_error == 'Refused'


def test_a_not_found_error_inside_the_answer_is_not_found(monkeypatch):
    vendor_answers(monkeypatch, {'error': {'message': 'Lead not found'}})
    assert testers.test_jornaya({'account': 'QA', 'key': 'k'})[0] == Status.CONNECTED  # the key itself was accepted


def test_convoso_reads_the_time_zone_box_and_says_refused_for_a_wrong_token(monkeypatch):
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        raise urllib.error.HTTPError(request.full_url, 401, 'x', {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(testers.urllib.request, 'urlopen', urlopen)
    status, message = testers.test_convoso({'key': 'fake', 'secret': '', 'setting': 'America/Chicago'})
    assert seen and status == Status.FAILED and 'refused' in message  # it reached Convoso: the time zone was found
    monkeypatch.setattr(testers.urllib.request, 'urlopen', lambda request, timeout: Reply(b'{"success": true}'))
    assert testers.test_convoso({'key': 'k', 'setting': 'America/Chicago'}) == (Status.CONNECTED, 'Read access works (call log, times in America/Chicago).')
    assert 'Time zone' in testers.test_convoso({'key': 'k', 'setting': ''})[1]
