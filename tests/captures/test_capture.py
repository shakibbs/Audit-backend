"""Module 7 step 3: CiV's own copy of each consent page, about once a day, phone and computer size, sealed; never an
internal address; screenshots and words deleted after 4 years, fingerprints kept."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.captures import browser as browser_module
from apps.captures.browser import Shot, is_public
from apps.captures.capture import capture_due, purge_old
from apps.captures.models import ConsentPage, PageCapture
from apps.certificates.models import CertificateClaim
from apps.ledger.models import Fingerprint
from apps.tenancy.scope import _scope

pytestmark = pytest.mark.django_db
FORM = {'consentBlock': {'text': 'I agree that SunPath Solar may call and text me using an autodialer.', 'fontSize': 9},
        'checkboxes': [{'checked': True, 'label': 'Yes'}], 'buttons': [{'text': 'Get My Quote'}]}
n = iter(range(10**6))


class FakeBrowser:
    opened: list = []
    answer = Shot(True, png=b'\x89PNG fake', text='Free solar quote. I agree...', measurements=FORM)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def capture(self, url, width, height):
        FakeBrowser.opened.append((url, width, height))
        return FakeBrowser.answer


@pytest.fixture(autouse=True)
def fake(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    FakeBrowser.opened, FakeBrowser.answer = [], Shot(True, png=b'\x89PNG fake', text='Free solar quote. I agree...', measurements=FORM)
    return FakeBrowser


def certificate(client, page='sunpathsolar.com/free-quote', seen=None):
    claim = CertificateClaim.objects.create(client=client, provider='trustedform', cert_ref=f'{next(n):040x}', state='claimed',
                                            deadline_at=timezone.now(), page=page)
    if seen:
        CertificateClaim.objects.filter(pk=claim.pk).update(seen_at=seen)
    return claim


def test_each_page_is_captured_once_at_phone_and_computer_size_and_sealed(company):
    for _ in range(10):
        certificate(company)  # ten leads from the same form
    assert capture_due(FakeBrowser) == 1
    assert FakeBrowser.opened == [('https://sunpathsolar.com/free-quote', 390, 844), ('https://sunpathsolar.com/free-quote', 1440, 900)]
    shots = PageCapture.objects.all()
    assert sorted(s.viewport for s in shots) == ['1440x900', '390x844'] and all(s.ok and s.screenshot for s in shots)
    phone = shots.get(viewport='390x844')
    assert phone.consent_block.startswith('I agree') and phone.measurements['checkboxes'][0]['checked'] is True
    assert Fingerprint.objects.filter(content_kind='page_capture', source_grade='A').count() == 2
    assert phone.fingerprint_sha256 in set(Fingerprint.objects.values_list('sha256', flat=True))


def test_about_once_a_day(company):
    certificate(company)
    capture_due(FakeBrowser)
    assert capture_due(FakeBrowser) == 0  # captured less than a day ago
    ConsentPage.objects.update(last_captured_at=timezone.now() - timedelta(hours=25))
    assert capture_due(FakeBrowser) == 1


def test_pages_not_seen_for_30_days_are_left_alone(company):
    certificate(company, seen=timezone.now() - timedelta(days=40))
    assert capture_due(FakeBrowser) == 0


def test_a_page_that_does_not_open_is_recorded_with_the_reason(company, fake):
    fake.answer = Shot(False, 'The page answered 404')
    certificate(company)
    capture_due(FakeBrowser)
    shot = PageCapture.objects.first()
    assert not shot.ok and shot.problem == 'The page answered 404' and not shot.screenshot
    assert not Fingerprint.objects.exists()


def test_only_public_web_addresses_are_ever_opened(monkeypatch):
    def resolves_to(ip):
        monkeypatch.setattr(browser_module.socket, 'getaddrinfo', lambda host, port: [(None, None, None, None, (ip, 0))])
    resolves_to('93.184.215.14')
    assert is_public('https://sunpathsolar.com/free-quote')
    for ip in ('127.0.0.1', '10.0.0.5', '172.18.0.3', '192.168.1.1', '169.254.169.254', '::1'):
        resolves_to(ip)
        assert not is_public('https://looks-public.example/'), ip
    resolves_to('93.184.215.14')
    assert not is_public('https://sunpathsolar.com:8080/') and not is_public('ftp://sunpathsolar.com/') and not is_public('file:///etc/passwd')


def test_after_4_years_the_screenshot_and_words_go_the_fingerprint_stays(company):
    certificate(company)
    capture_due(FakeBrowser)
    PageCapture.objects.update(captured_at=timezone.now() - timedelta(days=365 * 4 + 2))
    assert purge_old() == 2
    shot = PageCapture.objects.first()
    assert shot.purged_at and not shot.screenshot and shot.text == '' and shot.screenshot_sha256 and shot.fingerprint_sha256
    assert purge_old() == 0


def test_pages_and_captures_are_locked_per_client(company, other_company):
    certificate(company)
    certificate(other_company, page='ridgelinehvac.com/quote')
    capture_due(FakeBrowser)
    with _scope('client', str(company.pk)):
        assert set(ConsentPage.objects.values_list('client_id', flat=True)) == {company.pk}
        assert set(PageCapture.objects.values_list('client_id', flat=True)) == {company.pk}
