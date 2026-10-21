"""Which pages to capture and when (about once a day, phone and computer size), sealing each capture, and deleting
screenshots and text after 4 years (owner decision 2026-10-21; the fingerprints stay)."""
import hashlib
import json
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db.models import Max, Min
from django.utils import timezone

from apps.certificates.models import CertificateClaim
from apps.ledger.models import ContentKind, SourceGrade
from apps.ledger.record import ledger_job
from apps.rulebook.lookup import NoRulebook, RuleSet
from apps.tenancy.scope import all_clients, tenant

from .models import ConsentPage, PageCapture

ACTIVE_DAYS = 30  # pages named by a certificate in the last 30 days are captured
KEEP_YEARS = 4  # how long someone has to sue under the TCPA
PER_RUN = 25  # pages per run (each opened twice)
DEFAULT_VIEWPORTS = [[390, 844], [1440, 900]]
CAPTURED: list = []  # callables (page, captured_at): a new capture can change results that used this page


def _rule(key: str, default):
    try:
        return RuleSet().get(key, on=timezone.localdate()).value or default
    except NoRulebook:
        return default


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def pages_from_certificates() -> int:
    """Every page named by a claimed certificate becomes (or refreshes) a consent page to capture."""
    found = (CertificateClaim.objects.exclude(page='').values('client_id', 'page')
             .annotate(first=Min('seen_at'), last=Max('seen_at')))
    for row in found:
        page, created = ConsentPage.objects.get_or_create(client_id=row['client_id'], address=row['page'],
                                                          defaults={'first_seen_at': row['first'], 'last_seen_at': row['last']})
        if not created and page.last_seen_at < row['last']:
            ConsentPage.objects.filter(pk=page.pk).update(last_seen_at=row['last'])
    return len(found)


def due(now=None):
    now = now or timezone.now()
    every = timedelta(hours=int(_rule('page_capture_interval_hours', 24)))
    pages = ConsentPage.objects.filter(last_seen_at__gte=now - timedelta(days=ACTIVE_DAYS)).select_related('client')
    return [p for p in pages.order_by('last_captured_at') if p.last_captured_at is None or p.last_captured_at <= now - every]


def capture_page(page: ConsentPage, browser, now=None) -> list[PageCapture]:
    now = now or timezone.now()
    saved = []
    with tenant(page.client):
        for width, height in _rule('cc_viewports', DEFAULT_VIEWPORTS):
            shot = browser.capture(f'https://{page.address}', width, height)
            block = ((shot.measurements or {}).get('consentBlock') or {}).get('text', '')
            capture = PageCapture(client=page.client, page=page, captured_at=now, viewport=f'{width}x{height}', ok=shot.ok,
                                  problem=shot.problem[:200], text=shot.text, text_sha256=sha(shot.text) if shot.ok else '',
                                  consent_block=block, consent_block_sha256=sha(block) if block else '', measurements=shot.measurements or {})
            if shot.ok:
                capture.screenshot_sha256 = sha(shot.png)
                capture.screenshot.save('shot.png', ContentFile(shot.png), save=False)
                facts = json.dumps({'url': page.address, 'viewport': capture.viewport, 'captured_at': now.isoformat(),
                                    'screenshot': capture.screenshot_sha256, 'text': capture.text_sha256,
                                    'consent_block': capture.consent_block_sha256, 'measurements': capture.measurements},
                                   sort_keys=True).encode()
                with ledger_job(page.client, 'page capture') as job:  # sealed with the night's seal like every record
                    fp = job.record(source_system='civ_capture', source_record_id=f'{page.address}@{capture.viewport}@{now:%Y%m%dT%H%M%S}',
                                    raw=facts, content_kind=ContentKind.PAGE_CAPTURE, source_grade=SourceGrade.A)
                capture.fingerprint_sha256 = fp.sha256
            capture.save()
            saved.append(capture)
        ConsentPage.objects.filter(pk=page.pk).update(last_captured_at=now)
        if any(c.ok for c in saved):
            for receiver in CAPTURED:
                receiver(page, now)
    return saved


def capture_due(browser_factory=None, limit: int = PER_RUN) -> int:
    from .browser import Browser
    with all_clients():
        pages_from_certificates()
        pages = due()[:limit]
    if not pages:
        return 0
    with (browser_factory or Browser)() as browser:
        for page in pages:
            capture_page(page, browser)
    return len(pages)


def purge_old(now=None) -> int:
    """Captures older than 4 years: the screenshot and words are deleted; the hashes and fingerprint stay."""
    now = now or timezone.now()
    old = PageCapture.objects.filter(captured_at__lt=now - timedelta(days=365 * KEEP_YEARS + 1), purged_at__isnull=True)
    count = 0
    for capture in old:
        if capture.screenshot:
            capture.screenshot.delete(save=False)
        PageCapture.objects.filter(pk=capture.pk).update(screenshot='', text='', consent_block='', purged_at=now)
        count += 1
    return count
