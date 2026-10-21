"""Client API: proof requests. Everyone at the company sees them; only Admins and the company's lawyer answer.
Files are private: opened through this API (own company only) or the admin panel, and every opening is logged."""
from datetime import timedelta
from pathlib import Path

from django.http import FileResponse, Http404
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .models import ProofRequest
from .requests import answer, rates

MAX_BYTES = 25 * 1024 * 1024
ALLOWED = {'.pdf', '.jpg', '.jpeg', '.png', '.heic', '.mp3', '.wav', '.m4a', '.eml', '.msg', '.txt', '.doc', '.docx'}


def row(r: ProofRequest) -> dict:
    return {'id': f'pr-{r.pk}', 'batchKey': r.batch_key, 'list': r.batch_label, 'number': r.masked_label, 'sentAt': r.sent_at, 'dueAt': r.due_at,
            'answer': r.answer or None, 'answeredAt': r.answered_at, 'answeredBy': r.answered_by.name if r.answered_by else None,
            'fileType': r.get_file_type_display() if r.file_type else None, 'fileName': r.original_name or None,
            'fileUrl': f'/api/proof-requests/pr-{r.pk}/file' if r.file else None,
            'review': r.review or None, 'reviewNote': r.review_note or None, 'consentDate': r.consent_date}


def own(request, ref: str) -> ProofRequest:
    if not ref.startswith('pr-') or not ref[3:].isdigit():
        raise Http404
    found = ProofRequest.objects.filter(client=request.user.client, pk=int(ref[3:])).select_related('answered_by').first()
    if found is None:
        raise Http404
    return found


def can_answer(user) -> bool:
    return user.is_admin or user.is_counsel


class ProofRequestsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        client = request.user.client
        rows = ProofRequest.objects.filter(client=client).select_related('answered_by').order_by('-sent_at', 'pk')[:500]
        return Response({'canAnswer': can_answer(request.user), 'lists': rates(client), 'requests': [row(r) for r in rows]})


class AnswerView(APIView):
    """POST multipart {file, fileType} to attach proof, or JSON {"none": true}."""
    permission_classes = [IsClientUser]
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request, ref: str):
        if not can_answer(request.user):
            return Response({'detail': 'Only an Admin or your company lawyer can answer proof requests.'}, status=403)
        found = own(request, ref)
        if found.review:
            return Response({'detail': 'CiV has already checked this proof.'}, status=400)
        if request.data.get('none') in (True, 'true'):
            answer(found, request.user, none=True)
        else:
            upload, kind = request.FILES.get('file'), request.data.get('fileType', '')
            if upload is None or kind not in ProofRequest.FileType.values:
                return Response({'detail': 'Attach a file and say what it is.'}, status=400)
            if upload.size > MAX_BYTES or Path(upload.name).suffix.lower() not in ALLOWED:
                return Response({'detail': 'Use a PDF, picture, sound, email or Word file of 25 MB or less.'}, status=400)
            answer(found, request.user, upload=upload, file_type=kind)
        record('proof_request_answered', request=request, actor_kind='client_user', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=found.client_id, object=str(found)[:254])
        found.refresh_from_db()
        return Response(row(found))


class FileView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request, ref: str):
        found = own(request, ref)
        if not found.file:
            raise Http404
        record('proof_file_opened', request=request, actor_kind='client_user', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=found.client_id, object=str(found)[:254])
        response = FileResponse(found.file.open('rb'), as_attachment=True, filename=found.original_name or 'proof')
        response['Cache-Control'] = 'private, no-store'
        return response


def month_bounds(today):
    start = today.replace(day=1)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


def missing_items(client) -> list[dict]:
    """Module 7 checklist items failing on the client's consent pages, counted in certificates from each page."""
    from apps.captures.api import ITEMS, latest
    from apps.captures.checklist import evaluate
    from apps.captures.models import ConsentPage
    from apps.certificates.models import CertificateClaim
    counts: dict[str, int] = {}
    for page in ConsentPage.objects.filter(client=client).select_related('client')[:200]:
        good = [s for s in latest(page) if s.ok]
        if not good:
            continue
        items = evaluate({s.viewport: s.measurements for s in good}, client.name)['items']
        leads = CertificateClaim.objects.filter(client=client, page=page.address).count()
        for code, result in items.items():
            if result == 'fail' and ITEMS.get(code, ('', ''))[1] in ('no_proof', 'wording', 'warning'):
                counts[ITEMS[code][0]] = counts.get(ITEMS[code][0], 0) + leads
    return [{'label': k, 'count': v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def uploads(client) -> list[dict]:
    from apps.consent.models import ConsentProof
    from apps.imports.models import ImportBatch

    from .requests import EVIDENCE, UPLOADS, batch_key, batch_label, tokens_of
    by_key = {r['batchKey']: r for r in rates(client)}
    out = []
    for batch in ImportBatch.objects.filter(client=client, kind__in=UPLOADS).order_by('-starts')[:50]:
        tokens = tokens_of(batch)
        with_evidence = ConsentProof.objects.filter(client=client, phone_token__in=tokens, kind__in=EVIDENCE, withdrawn_at__isnull=True) \
            .values('phone_token').distinct().count()
        asked = by_key.get(batch_key(batch))
        out.append({'id': f'ib-{batch.pk}', 'label': batch_label(batch), 'system': batch.system, 'numbers': len(tokens),
                    'withEvidence': with_evidence, 'stopBroughtBack': batch.opted_out_readded, 'optOutsCleared': batch.optouts_cleared,
                    'asked': asked['asked'] if asked else 0, 'proofRate': asked['rate'] if asked else None})
    return out


class ProvenanceView(APIView):
    """The Lead Provenance page: this month's ladder, top sources, untraced list, uploads, missing checklist items."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from django.db.models import Count
        from django.utils import timezone

        from .ladder import untraced
        from .models import Provenance
        client = request.user.client
        start, end = month_bounds(timezone.localdate())
        month = Provenance.objects.filter(client=client, first_contact_at__date__gte=start, first_contact_at__date__lte=end)
        total = month.count()
        counts = dict(month.values_list('basis').annotate(n=Count('id')))
        ladder = [{'basis': b, 'label': label, 'count': counts.get(b, 0), 'share': round(100 * counts.get(b, 0) / total, 1) if total else 0,
                   'available': b not in ('feed', 'invoice')} for b, label in Provenance.Basis.choices]
        top = (month.exclude(source_name='').exclude(basis='manual_import').values('basis', 'source_name')
               .annotate(n=Count('id')).order_by('-n')[:10])
        return Response({
            'period': start.strftime('%B %Y'), 'numbers': total, 'ladder': ladder,
            'topSources': [{'name': t['source_name'], 'basis': Provenance.Basis(t['basis']).label, 'count': t['n']} for t in top],
            'untraced': untraced(client, start, end)[:200], 'uploads': uploads(client), 'missing': missing_items(client),
        })


class LeadsView(APIView):
    """Lead Provenance's first cards that are real now: leads this month, consent completeness (leads whose form page
    passed every rule checklist item, among leads with a photographed page) and the items most often missing. Signal
    levels and page match need paid certificate data: left out (the portal keeps its sample)."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from django.utils import timezone

        from apps.captures.api import ITEMS, latest
        from apps.captures.checklist import evaluate
        from apps.captures.models import ConsentPage
        from apps.certificates.models import CertificateClaim
        from apps.imports.models import CrmCreation
        client = request.user.client
        start, end = month_bounds(timezone.localdate())
        out = {'inspected': CrmCreation.objects.filter(client=client, created_at__date__gte=start, created_at__date__lte=end).count()}
        passed = judged = 0
        for page in ConsentPage.objects.filter(client=client).select_related('client'):
            good = [s for s in latest(page) if s.ok]
            if not good:
                continue
            items = evaluate({s.viewport: s.measurements for s in good}, client.name)['items']
            leads = CertificateClaim.objects.filter(client=client, page=page.address, seen_at__date__gte=start).count()
            judged += leads
            if all(v != 'fail' for k, v in items.items() if ITEMS.get(k, ('', ''))[1] in ('no_proof', 'wording')):
                passed += leads
        if judged:
            out['completeness'] = round(100 * passed / judged, 1)
        missing = missing_items(client)
        if missing:
            out['missing'] = missing
        return Response(out)


def vendor_id(name: str) -> str:
    import hashlib
    return 'v-' + hashlib.sha256(name.encode()).hexdigest()[:10]


class VendorsView(APIView):
    """Vendor Ledger: the client's vendor scorecards (Module 12, `vendors.portal`)."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from apps.vendors.portal import vendors_page
        return Response(vendors_page(request.user.client))


class SearchView(APIView):
    """Numbers (last 4 digits or a full number, masked in the answer) and vendors. Pages, domains and metrics are
    searched in the portal."""
    permission_classes = [IsClientUser]

    def get(self, request):
        import re

        from apps.contacts.api import find_tokens, number_ref
        from apps.contacts.models import ContactEvent
        from apps.imports.models import CrmCreation
        client = request.user.client
        q = (request.query_params.get('q') or '').strip()
        hits = []
        if len(re.sub(r'\D', '', q)) >= 4 and (match := find_tokens(client, q)) is not None:
            seen = set()
            for token, label in ContactEvent.objects.filter(client=client, **match).values_list('phone_token', 'masked_label')[:50]:
                if token not in seen:
                    seen.add(token)
                    hits.append({'kind': 'number', 'id': number_ref(token), 'label': label, 'hint': 'Evidence file'})
        if len(q) >= 2:
            for name in CrmCreation.objects.filter(client=client, vendor__icontains=q).values_list('vendor', flat=True).distinct()[:5]:
                from apps.vendors.rates import vendor_key
                hits.append({'kind': 'vendor', 'id': vendor_id(f'{vendor_key(name)}|'), 'label': name, 'hint': 'Vendor'})  # opens its Vendor Ledger row
        return Response(hits[:10])
