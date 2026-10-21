"""Module 15: the insurer saves its rating engine's address and key (locked, only the last 4 shown); the button sends
a sharing company's newest sheet, signed; private or local addresses are refused; the 6th sends last month's locked
sheets once; the company's access log shows each send; another insurer never sees the settings."""
import hashlib
import hmac
import json
import socket
from datetime import UTC, date, datetime

import pytest
from django.test import Client as Browser

from apps.access_log.models import AccessEntry
from apps.buyers import engines
from apps.buyers.attestation import save
from apps.buyers.models import BuyerLink, BuyerOrg, BuyerUser, RatingEngine, RatingSend
from apps.buyers.rating import send_monthly
from apps.tenancy.scope import buyer
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db
PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]


@pytest.fixture
def engine_box(monkeypatch):
    """A pretend rating engine: keeps what it got and answers 202."""
    got = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *a, **k: PUBLIC if host == 'rate.falconrisk.com' else real(host, *a, **k))

    def post(url, body, headers):
        got.append((url, body, headers))
        return 202, 'queued'
    monkeypatch.setattr(engines, '_post', post)
    return got


def underwriter(org) -> Browser:
    person = BuyerUser(org=org, email=f'j.merchant@{org.domain}', name='J. Merchant')
    person.set_password(PASSWORD)
    person.save()
    b = Browser()
    assert b.post('/api/session/sign-in', {'email': person.email, 'password': PASSWORD}, content_type='application/json').status_code == 200
    return b


def put(b, **body):
    return b.post('/api/rating-engine', body, content_type='application/json')


def test_save_send_and_log(company, engine_box):
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    BuyerLink.objects.create(org=org, client=company, granted_by='Dana')
    save(company, date(2026, 10, 1))
    b = underwriter(org)
    assert put(b, url='http://rate.falconrisk.com/in', key='k').status_code == 400  # https only
    assert put(b, url='https://127.0.0.1/in', key='k').status_code == 400  # never inside our own server
    assert put(b, url='https://10.1.2.3/in', key='k').status_code == 400
    saved = put(b, url='https://rate.falconrisk.com/in', key='secret-key-7781', monthly=True).json()
    assert saved['keyHint'] == '7781' and 'secret' not in json.dumps(saved)
    assert 'secret-key' not in RatingEngine.objects.get().key  # locked in the database
    reply = b.post('/api/rating-engine/send', {'insured': f'c-{company.pk}'}, content_type='application/json').json()
    assert reply == {'ok': True, 'detail': 'Accepted by the rating engine'}
    url, body, headers = engine_box[0]
    assert headers['Authorization'] == 'Bearer secret-key-7781'
    assert headers['X-CiV-Signature'] == 'sha256=' + hmac.new(b'secret-key-7781', body, hashlib.sha256).hexdigest()
    sheet = json.loads(body)
    assert sheet['schema'] == 'civ.attestation.v1' and sheet['companyId'] == f'c-{company.pk}' and 'phone' not in body.decode().lower()
    assert AccessEntry.objects.get(action='attestation_sent').client_id == company.pk
    assert b.get('/api/rating-engine').json()['sends'][0]['company'] == company.name


def test_no_send_for_a_company_that_does_not_share(company, other_company, engine_box):
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    save(other_company, date(2026, 10, 1))
    b = underwriter(org)
    put(b, url='https://rate.falconrisk.com/in', key='k123')
    assert b.post('/api/rating-engine/send', {'insured': f'c-{other_company.pk}'}, content_type='application/json').status_code == 404
    assert engine_box == []


def test_the_monthly_send_goes_once_and_only_locked_sheets(company, engine_box):
    from apps.connections.crypto import lock
    org = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    BuyerLink.objects.create(org=org, client=company, granted_by='Dana')
    RatingEngine.objects.create(org=org, url='https://rate.falconrisk.com/in', key=lock({'key': 'k123'}), key_hint='k123', monthly=True)
    save(company, date(2026, 10, 1), now=datetime(2026, 11, 7, tzinfo=UTC))  # October, locked
    assert send_monthly(date(2026, 11, 6)) == 1 and send_monthly(date(2026, 11, 6)) == 0
    assert RatingSend.objects.get().by == 'Monthly send'


def test_another_insurer_never_sees_the_settings(company):
    falcon = BuyerOrg.objects.create(name='Falcon Risk', domain='falconrisk.com')
    other = BuyerOrg.objects.create(name='Atlas Mutual', domain='atlasmutual.com')
    RatingEngine.objects.create(org=falcon, url='https://rate.falconrisk.com/in', key='x', key_hint='0000')
    with buyer(other):
        assert not RatingEngine.objects.exists()
    with buyer(falcon):
        assert RatingEngine.objects.count() == 1
    assert underwriter(other).get('/api/rating-engine').json()['url'] == ''
