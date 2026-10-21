"""Client API (Module 14 step 1): GET /api/evidence-file/<ref>?format=pdf|json — a number's evidence file, for the
company's Admins and lawyer (owner decision 2026-10-22). The banned-word check runs first; every download is logged
with the file's fingerprint."""
import hashlib
import json

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser
from apps.reports.words import banned_words

from .file import build
from .pdf import render


class EvidenceFileView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request, ref: str):
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can download an evidence file.'}, status=status.HTTP_403_FORBIDDEN)
        data = build(user.client, ref)
        if data is None:
            return Response({'detail': 'No evidence file for this number.'}, status=status.HTTP_404_NOT_FOUND)
        text = json.dumps(data, default=str, ensure_ascii=False)
        bad = banned_words(text)
        if bad:
            record('evidence_file_blocked', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
                   client_id=user.client_id, object=f'{data["number"]} · {", ".join(bad)}'[:254])
            return Response({'detail': 'This file was held back for a wording check; CiV has been told.'}, status=status.HTTP_409_CONFLICT)
        as_pdf = request.query_params.get('format', 'pdf') != 'json'
        content = render(data) if as_pdf else text.encode()
        sha = hashlib.sha256(content).hexdigest()
        record('evidence_file_downloaded', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{data["number"]} · {"pdf" if as_pdf else "json"} · sha256 {sha}'[:254])
        response = HttpResponse(content, content_type='application/pdf' if as_pdf else 'application/json')
        response['Content-Disposition'] = f'attachment; filename="evidence-file-{ref[2:10]}.{"pdf" if as_pdf else "json"}"'
        response['Cache-Control'] = 'private, no-store'
        return response


class RefetchView(APIView):
    """POST /api/evidence-file/<ref>/refetch — ask the tools again for every record behind this number (Admins and the
    lawyer), before exporting its evidence file. Returns each record's result."""
    permission_classes = [IsClientUser]

    def post(self, request, ref: str):
        from apps.contacts.api import contacts_of

        from .file import records_of
        from .refetch import check_records
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can do this.'}, status=status.HTTP_403_FORBIDDEN)
        contacts = contacts_of(user.client, ref)
        if not contacts:
            return Response({'detail': 'No evidence file for this number.'}, status=status.HTTP_404_NOT_FOUND)
        records = [(tool, rid) for _, tool, rid in records_of(user.client, contacts[-1].phone_token, contacts)]
        done = check_records(user.client, records)
        record('evidence_refetched', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{contacts[-1].masked_label} · {len(done)} records'[:254])
        counts: dict[str, int] = {}
        for c in done:
            counts[c.get_result_display()] = counts.get(c.get_result_display(), 0) + 1
        return Response({'checked': len(done), 'results': counts})


class BundleView(APIView):
    """POST /api/evidence-bundle {numbers: [...], pack: bool} (Module 14 step 3; Admins and the lawyer): one ZIP with the
    evidence file of each number (up to 25), and with pack=true the certification pack. The typed numbers are turned
    into phone codes in memory and never stored; the banned-word check runs on every file; the download is logged."""
    permission_classes = [IsClientUser]

    def post(self, request):
        from .bundle import MAX_NUMBERS, files_for, resolve, zip_bundle
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can export evidence files.'}, status=status.HTTP_403_FORBIDDEN)
        typed = [str(n) for n in (request.data.get('numbers') or []) if str(n).strip()]
        if not typed:
            return Response({'detail': 'Paste at least one phone number.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(typed) > MAX_NUMBERS:
            return Response({'detail': f'Up to {MAX_NUMBERS} numbers at a time.'}, status=status.HTTP_400_BAD_REQUEST)
        found, missing = resolve(user.client, typed)
        files = files_for(user.client, found)
        bad = banned_words(json.dumps(files, default=str, ensure_ascii=False))
        if bad:
            record('evidence_file_blocked', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
                   client_id=user.client_id, object=f'bulk · {", ".join(bad)}'[:254])
            return Response({'detail': 'These files were held back for a wording check; CiV has been told.'}, status=status.HTTP_409_CONFLICT)
        pack = bool(request.data.get('pack'))
        content = zip_bundle(user.client, files, missing, pack)
        sha = hashlib.sha256(content).hexdigest()
        record('evidence_bundle_downloaded', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email, client_id=user.client_id,
               object=f'{len(files)} files · {len(missing)} not found{" · certification pack" if pack else ""} · sha256 {sha}'[:254])
        response = HttpResponse(content, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{"certification-pack" if pack else "evidence-files"}-{timezone.now():%Y%m%d}.zip"'
        response['Cache-Control'] = 'private, no-store'
        response['X-Not-Found'] = str(len(missing))
        return response


def hold_row(h) -> dict:
    return {'id': f'lh-{h.pk}', 'scope': h.scope, 'target': h.target, 'reason': h.reason, 'setBy': h.set_by, 'setOn': h.set_at.date().isoformat(),
            'releasedOn': h.released_at.date().isoformat() if h.released_at else None}


class HoldsView(APIView):
    """GET /api/legal-holds (everyone in the company) · POST {scope, target, reason} (Admins and the lawyer) — Module 14
    step 4. A number is turned into its phone code and shown masked; it is never stored as typed."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from .models import LegalHold
        return Response([hold_row(h) for h in LegalHold.objects.filter(client=request.user.client)[:200]])

    def post(self, request):
        from .holds import place
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can place a hold.'}, status=status.HTTP_403_FORBIDDEN)
        reason = str(request.data.get('reason') or '').strip()
        if not reason:
            return Response({'detail': 'Say why (e.g. the case name).'}, status=status.HTTP_400_BAD_REQUEST)
        made = place(user.client, str(request.data.get('scope') or ''), str(request.data.get('target') or ''), reason, user.name)
        if isinstance(made, str):
            return Response({'detail': made}, status=status.HTTP_400_BAD_REQUEST)
        record('legal_hold_placed', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{made.get_scope_display()} {made.target} · {reason}'[:254])
        return Response(hold_row(made), status=status.HTTP_201_CREATED)


class ReleaseHoldView(APIView):
    permission_classes = [IsClientUser]

    def post(self, request, ref: str):
        from .models import LegalHold
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can release a hold.'}, status=status.HTTP_403_FORBIDDEN)
        pk = ref.removeprefix('lh-')
        hold = LegalHold.objects.filter(client=user.client, pk=int(pk) if pk.isdigit() else 0, released_at__isnull=True).first()
        if hold is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        hold.released_by, hold.released_at = user.name, timezone.now()
        hold.save(update_fields=['released_by', 'released_at'])
        record('legal_hold_released', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{hold.get_scope_display()} {hold.target}'[:254])
        return Response(hold_row(hold))
