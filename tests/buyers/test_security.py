"""Module 15 step 4: what an insurer or acquirer can never do, run like a real browser (no all-companies view in the
test): reach any client endpoint, read or change; see a company that does not share; keep access after sharing stops,
the end date passes or CiV blocks it; see another insurer's companies or settings; get personal data in a sheet."""
import json
import re
from datetime import date, timedelta

import pytest
from django.core import mail
from django.test import Client as Browser
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

from apps.buyers import engines
from apps.buyers.attestation import save
from apps.buyers.models import BuyerLink, BuyerOrg, BuyerUser, RatingEngine
from apps.consent.models import ConsentResult
from apps.contacts.models import ContactEvent
from apps.tenancy.scope import _scope
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db

# The only addresses a buyer may use; everything else under /api/ belongs to clients.
BUYER_READS = {'session', 'insureds', 'insureds/<ref>', 'litigation', 'rating-engine', 'health', 'invites/check'}
BUYER_WRITES = {'session/sign-in', 'session/sign-out', 'invites/accept', 'rating-engine', 'rating-engine/send'}


def api_routes() -> list[str]:
    out = []

    def walk(patterns, prefix=''):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                out.append(prefix + str(p.pattern))
    walk(get_resolver().url_patterns)
    return sorted({r.removeprefix('api/') for r in out if r.startswith('api/')})


def filled(route: str, pk: int) -> str:
    return re.sub(r'<(?:(\w+):)?(\w+)>', lambda m: str(pk) if m.group(1) == 'int' else f'x-{pk}', route)


def name(route: str) -> str:
    return re.sub(r'<(?:\w+:)?\w+>', '<ref>', route)


def contact(company) -> ContactEvent:
    c = ContactEvent.objects.create(client=company, phone_token='tok-secret-1', phone_token_kid='k', source_system='twilio',
                                    source_record_id='SM-secret', source_grade='C', channel='text', direction='outbound',
                                    occurred_at=timezone.now() - timedelta(days=2))
    ConsentResult.objects.create(client=company, contact=c, variant='strict', status='no_proof', codes=['NP_AFTER_OPT_OUT'],
                                 evaluation_as_of=c.occurred_at, rulebook_version='3.0')
    return c


def insurer(company, admin_user, signed_in, email='a.lee@falconrisk.com', name_='Falcon Risk') -> Browser:
    """The company shares; the person accepts the invite in a fresh browser with no scope at all."""
    signed_in(admin_user).call('post', '/api/buyer-links', {'name': name_, 'email': email})
    token = re.search(r'invite=([\w-]+)', mail.outbox[-1].body).group(1)
    b = Browser()
    with _scope('', ''):
        assert b.post('/api/invites/accept', {'token': token, 'password': PASSWORD}, content_type='application/json').status_code == 200
    return b


def test_no_client_endpoint_answers_an_insurer(company, admin_user, signed_in):
    c = contact(company)
    b = insurer(company, admin_user, signed_in)
    leaks = []
    with _scope('', ''):
        for route in api_routes():
            path = '/api/' + filled(route, c.pk)
            if name(route) not in BUYER_READS and 200 <= b.get(path).status_code < 300:
                leaks.append(f'GET {route}')
            if name(route) not in BUYER_WRITES:
                for method in ('post', 'patch', 'put', 'delete'):
                    if 200 <= getattr(b, method)(path, '{}', content_type='application/json').status_code < 300:
                        leaks.append(f'{method.upper()} {route}')
    assert leaks == []


def test_what_an_insurer_reads_holds_no_personal_data(company, admin_user, signed_in, monkeypatch):
    contact(company)
    save(company, timezone.localdate().replace(day=1))
    b = insurer(company, admin_user, signed_in)
    got = []
    monkeypatch.setattr(engines, 'check_address', lambda url: None)
    monkeypatch.setattr(engines, '_post', lambda url, body, headers: got.append(body) or (200, 'ok'))
    with _scope('', ''):
        b.post('/api/rating-engine', {'url': 'https://rate.falconrisk.com/in', 'key': 'k-1234'}, content_type='application/json')
        ref = b.get('/api/insureds').json()[0]['id']
        seen = json.dumps(b.get('/api/insureds').json()) + json.dumps(b.get(f'/api/insureds/{ref}').json())
        assert b.post('/api/rating-engine/send', {'insured': ref}, content_type='application/json').json()['ok']
    for text in (seen, got[0].decode()):
        assert 'tok-secret' not in text and 'SM-secret' not in text and 'statementRows' not in text


def test_only_sharing_companies_and_never_another_insurer(company, other_company, admin_user, other_admin, signed_in):
    contact(other_company)
    falcon = insurer(company, admin_user, signed_in)
    atlas = insurer(other_company, other_admin, signed_in, email='kim@atlasmutual.com', name_='Atlas Mutual')
    with _scope('', ''):
        assert [r['name'] for r in falcon.get('/api/insureds').json()] == [company.name]
        assert [r['name'] for r in atlas.get('/api/insureds').json()] == [other_company.name]
        assert falcon.get(f'/api/insureds/c-{other_company.pk}').status_code == 404  # guessing the number
        assert falcon.post('/api/rating-engine/send', {'insured': f'c-{other_company.pk}'}, content_type='application/json').status_code in (400, 404)
        atlas.post('/api/rating-engine', {'url': 'https://example.com/in', 'key': 'atlas-key'}, content_type='application/json')
        assert falcon.get('/api/rating-engine').json()['url'] == ''


def test_access_ends_at_once(company, admin_user, signed_in):
    b = insurer(company, admin_user, signed_in)
    org = BuyerOrg.objects.get()
    with _scope('', ''):
        assert len(b.get('/api/insureds').json()) == 1
    BuyerLink.objects.update(ends_on=date.today() - timedelta(days=1))  # an acquirer's end date passed
    with _scope('', ''):
        assert b.get('/api/insureds').json() == []
    BuyerLink.objects.update(ends_on=None)
    org.is_active = False  # CiV blocks the insurer in the admin panel
    org.save()
    with _scope('', ''):
        assert b.get('/api/insureds').status_code in (401, 403)
        assert b.get('/api/session').json().get('signedIn') is False
    org.is_active = True
    org.save()
    BuyerUser.objects.update(is_active=False)  # or one person is turned off
    with _scope('', ''):
        assert b.get('/api/insureds').status_code in (401, 403)


def test_the_rating_key_never_comes_back(company, admin_user, signed_in, monkeypatch):
    b = insurer(company, admin_user, signed_in)
    monkeypatch.setattr(engines, 'check_address', lambda url: None)
    with _scope('', ''):
        reply = b.post('/api/rating-engine', {'url': 'https://rate.falconrisk.com/in', 'key': 'very-secret-9876'}, content_type='application/json')
        assert 'very-secret' not in reply.content.decode() and 'very-secret' not in b.get('/api/rating-engine').content.decode()
    assert 'very-secret' not in RatingEngine.objects.get().key
