"""Module 7 step 6: the Wording tab API, its photos (own client only), certificate source and phone match, the admin tab."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.captures.browser import Shot
from apps.captures.capture import capture_due
from apps.captures.models import PageCapture
from apps.certificates.models import CertificateClaim
from apps.consent.models import ConsentProof
from apps.staff.models import StaffUser
from tests.captures.test_capture import FakeBrowser, fake  # noqa: F401
from tests.captures.test_checklist import form
from tests.conftest import PASSWORD
from tests.regulatory.test_portal_api import browser_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def photographed(company, fake):  # noqa: F811
    fake.answer = Shot(True, png=b'\x89PNG photo', text='Free quote', measurements=form(ticked=True))
    claim = CertificateClaim.objects.create(client=company, provider='trustedform', cert_ref='a' * 40, state='claimed',
                                            deadline_at=timezone.now(), page='sunpathsolar.com/free-quote', phone_match={'p1': True})
    ConsentProof.objects.create(client=company, phone_token='p1', kind='certificate', proof_type='web_cert', certificate=claim,
                                captured_at=timezone.now() - timedelta(days=1), source_system='hubspot', source_record_id='contacts:1',
                                source_hint='FORM')
    capture_due(FakeBrowser)
    return claim


def test_the_wording_tab_lists_each_page_with_photos_and_checklist(photographed, member_user):
    api = browser_for(member_user)
    page = api.get('/api/consent-pages').json()[0]
    assert page['address'] == 'sunpathsolar.com/free-quote' and page['sourceLabel'] == "Client's own form" and page['leads'] == 1
    assert [p['label'] for p in page['photos']] == ['Phone', 'Computer'] and page['wording'].startswith('By clicking')
    items = {i['code']: i for i in page['items']}
    assert items['CC_UNTICKED']['result'] == 'fail' and items['CC_UNTICKED']['effect'] == 'no_proof'
    assert items['CC_CONSENT_TEXT']['result'] == 'pass' and items['CC_OPT_OUT']['result'] == 'not_measured' and page['draft']
    photo = api.get(page['photos'][0]['url'])
    assert photo.status_code == 200 and photo['Content-Type'] == 'image/png' and b''.join(photo.streaming_content) == b'\x89PNG photo'


def test_another_client_never_sees_the_pages_or_photos(photographed, member_user, other_admin):
    url = browser_for(member_user).get('/api/consent-pages').json()[0]['photos'][0]['url']
    other = browser_for(other_admin)
    assert other.get('/api/consent-pages').json() == [] and other.get(url).status_code == 404


def test_certificates_show_their_source_and_phone_match(photographed, member_user):
    row = browser_for(member_user).get('/api/certificates').json()[0]
    assert row['source'] == "Client's own form" and row['phoneMatch'] is True


def test_the_admin_client_page_has_a_consent_pages_tab_with_photos(photographed, company, client):
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password=PASSWORD))
    html = client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'Consent pages' in html and 'sunpathsolar.com/free-quote' in html and '❌ Consent box not ticked in advance' in html
    shot = PageCapture.objects.first()
    photo = client.get(f'/civ-admin/clients/client/{company.pk}/consent-pages/{shot.pk}/photo/')
    assert photo.status_code == 200 and photo['Content-Type'] == 'image/png'
