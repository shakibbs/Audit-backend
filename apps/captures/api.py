"""Client API: the Wording tab (each consent page with CiV's latest photos and checklist) and the photos themselves.
Only the signed-in client's own pages; photos are served through this API only (no public address)."""
from collections import Counter

from django.http import FileResponse, Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.certificates.models import CertificateClaim
from apps.consent.models import ConsentProof
from apps.consent.sources import LABEL, UNKNOWN, source_of

from .checklist import evaluate
from .models import ConsentPage, PageCapture

ITEMS = {  # code: (words, effect when it fails)
    'CC_CONSENT_TEXT': ('Asks for permission to call or text', 'no_proof'),
    'CC_UNTICKED': ('Consent box not ticked in advance', 'no_proof'),
    'CC_BUTTON_MATCH': ('“By clicking …” names the real button', 'wording'),
    'CC_NUMBER_SHOWN': ('Mentions the phone number', 'wording'),
    'CC_FONT_SIZE': ('Text big enough (10 px, draft)', 'wording'),
    'CC_CONTRAST': ('Text easy to read (contrast)', 'wording'),
    'CC_ABOVE_BUTTON': ('Text above the button', 'warning'),
    'CC_NO_SCROLL': ('Seen without scrolling', 'warning'),
    'CC_SELLER_NAMED': ('Your company named', 'info'),
    'CC_OPT_OUT': ('Says how to stop', 'ai'),
    'CC_NOT_CONDITION': ('Says consent is not a condition of purchase', 'ai'),
    'CC_AUTODIAL_DISCLOSED': ('Says calls may be automated', 'ai'),
}


def page_ref(page: ConsentPage) -> str:
    return f'cpg-{page.pk}'


def latest(page: ConsentPage) -> list[PageCapture]:
    newest = page.captures.order_by('-captured_at').first()
    return list(page.captures.filter(captured_at=newest.captured_at)) if newest else []


def page_source(client, address: str) -> str:
    """The most common source of the proofs whose certificate came from this page."""
    proofs = ConsentProof.objects.filter(client=client, certificate__page=address).only('client_id', 'source_system', 'source_record_id', 'source_hint')[:200]
    found = Counter(source_of(p) for p in proofs)
    return found.most_common(1)[0][0] if found else UNKNOWN


def page_vendor(page: ConsentPage) -> str | None:
    """The vendor the client's CRM names on leads whose certificate came from this page (most common), if any."""
    from apps.imports.models import CrmCreation
    records = ConsentProof.objects.filter(client=page.client, certificate__page=page.address).values_list('source_system', 'source_record_id')[:200]
    names = Counter(CrmCreation.objects.filter(client=page.client, source_system=s, record_id=r).values_list('vendor', flat=True).first() or ''
                    for s, r in records)
    names.pop('', None)
    return names.most_common(1)[0][0] if names else None


def wording_changed_on(page: ConsentPage):
    """When the consent words last changed on CiV's photos (None while they never changed)."""
    shots = list(page.captures.filter(ok=True).exclude(consent_block_sha256='').order_by('captured_at').values_list('captured_at', 'consent_block_sha256'))
    changed, last = None, None
    for at, digest in shots:
        if last is not None and digest != last:
            changed = at
        last = digest
    return changed


def page_row(page: ConsentPage) -> dict:
    shots = latest(page)
    good = [s for s in shots if s.ok]
    checked = evaluate({s.viewport: s.measurements for s in good}, page.client.name) if good else None
    phone_first = sorted(good, key=lambda s: s.viewport != '390x844')
    source = page_source(page.client, page.address)
    measured = {k: v for k, v in (checked['items'] if checked else {}).items() if ITEMS[k][1] != 'ai' and v != 'not_measured'}
    return {
        'mark': page.client_mark, 'vendor': page_vendor(page), 'changedOn': wording_changed_on(page),
        'checklistPassed': sum(1 for v in measured.values() if v == 'pass'), 'checklistTotal': len(measured),
        'missing': [ITEMS[k][0] for k, v in measured.items() if v == 'fail'],
        'id': page_ref(page), 'address': page.address, 'source': source, 'sourceLabel': LABEL[source],
        'firstSeen': page.first_seen_at, 'lastSeen': page.last_seen_at,
        'leads': CertificateClaim.objects.filter(client=page.client, page=page.address).count(),
        'capturedAt': shots[0].captured_at if shots else None,
        'problem': '' if good or not shots else shots[0].problem,
        'photos': [{'viewport': s.viewport, 'label': 'Phone' if s.viewport.startswith('390') else 'Computer',
                    'url': f'/api/consent-pages/{page_ref(page)}/photo/{s.viewport}'} for s in phone_first if s.screenshot],
        'wording': phone_first[0].consent_block if phone_first else '',
        'items': [{'code': code, 'label': words, 'effect': effect,
                   'result': checked['items'].get(code, 'not_measured') if checked else 'not_measured'}
                  for code, (words, effect) in ITEMS.items()],
        'draft': True,  # the checklist is not approved by counsel yet
    }


class ConsentPagesView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        pages = ConsentPage.objects.filter(client=request.user.client).select_related('client').order_by('-last_seen_at')[:100]
        return Response([page_row(p) for p in pages])


class PageMarkView(APIView):
    """PATCH {mark}: the client's own mark on a page's wording (approved / unmarked / rejected). Never changes a result."""
    permission_classes = [IsClientUser]

    def patch(self, request, ref: str):
        if not ref.startswith('cpg-') or not ref[4:].isdigit():
            raise Http404
        page = ConsentPage.objects.filter(client=request.user.client, pk=int(ref[4:])).select_related('client').first()
        if page is None:
            raise Http404
        mark = request.data.get('mark')
        if mark not in ('approved', 'unmarked', 'rejected'):
            return Response({'detail': 'Choose Approved, Not marked or Rejected.'}, status=400)
        page.client_mark = mark
        page.save(update_fields=['client_mark'])
        return Response(page_row(page))


class PagePhotoView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request, ref: str, viewport: str):
        if not ref.startswith('cpg-') or not ref[4:].isdigit():
            raise Http404
        page = ConsentPage.objects.filter(client=request.user.client, pk=int(ref[4:])).first()
        shot = next((s for s in latest(page) if s.viewport == viewport and s.screenshot), None) if page else None
        if shot is None:
            raise Http404
        return FileResponse(shot.screenshot.open('rb'), content_type='image/png')
