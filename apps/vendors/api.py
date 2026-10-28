"""Client API (Module 12 step 3): GET /api/vendor-contracts (the list), POST /api/vendor-contracts (multipart: vendor, file, endsOn, disputeDays; Admins and
the company's lawyer) and GET /api/vendor-contracts/vc-<id>/file (logged). The file is private."""
import hashlib
from datetime import date
from pathlib import Path

from django.http import FileResponse
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .contracts import ALLOWED, MAX_BYTES, state
from .models import VendorContract
from .rates import vendor_key
from apps.refs import day, number, text


def contract_row(c: VendorContract) -> dict:
    return {'id': f'vc-{c.pk}', 'vendor': c.name, 'file': c.original_name, 'endsOn': c.ends_on, 'disputeDays': c.dispute_days,
            'state': state(c, date.today()), 'uploadedBy': c.uploaded_by, 'uploadedAt': c.uploaded_at,
            'url': f'/api/vendor-contracts/vc-{c.pk}/file' if c.file and not c.purged_at else None}


class ContractsView(APIView):
    permission_classes = [IsClientUser]
    parser_classes = [MultiPartParser]

    def get(self, request):
        """Every contract the company uploaded, newest first (the newest per vendor is the one that counts)."""
        return Response([contract_row(c) for c in VendorContract.objects.filter(client=request.user.client)[:200]])

    def post(self, request):
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can add a contract.'}, status=status.HTTP_403_FORBIDDEN)
        vendor, upload = text(request.data.get('vendor'), 1000), request.FILES.get('file')
        if not vendor or upload is None:
            return Response({'detail': 'Choose the vendor and the contract file.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(vendor) > 120:
            return Response({'detail': 'Keep the vendor name under 120 characters.'}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size == 0:
            return Response({'detail': 'That file is empty.'}, status=status.HTTP_400_BAD_REQUEST)
        if Path(upload.name).suffix.lower() not in ALLOWED or upload.size > MAX_BYTES:
            return Response({'detail': 'Upload a PDF, Word file, picture or text file under 20 MB.'}, status=status.HTTP_400_BAD_REQUEST)
        ends = day(request.data.get('endsOn')) if request.data.get('endsOn') else None
        days = number(request.data.get('disputeDays')) if request.data.get('disputeDays') not in (None, '') else None
        if (request.data.get('endsOn') and ends is None) or (request.data.get('disputeDays') not in (None, '') and (days is None or days > 365)):
            return Response({'detail': 'Give the end date as YYYY-MM-DD and the dispute window as 0–365 days.'}, status=status.HTTP_400_BAD_REQUEST)
        data = upload.read()
        upload.seek(0)
        c = VendorContract(client=user.client, key=vendor_key(vendor), name=' '.join(vendor.split()), original_name=upload.name[:255],
                           sha256=hashlib.sha256(data).hexdigest(), ends_on=ends, dispute_days=days, uploaded_by=user.name)
        c.file.save(upload.name, upload, save=False)
        c.save()
        record('vendor_contract_added', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{c.name} · sha256 {c.sha256}'[:254])
        from apps.scoring.tasks import queue_refresh
        queue_refresh(user.client)  # vendor terms on file (M07) follow within minutes
        return Response(contract_row(c), status=status.HTTP_201_CREATED)


class ContractFileView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request, ref: str):
        pk = ref.removeprefix('vc-')
        c = VendorContract.objects.filter(client=request.user.client, pk=(number(pk) or 0), purged_at__isnull=True).exclude(file='').first()
        if c is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        record('vendor_contract_opened', request=request, actor_kind='client_user', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=c.client_id, object=c.name[:254])
        response = FileResponse(c.file.open('rb'), as_attachment=True, filename=c.original_name)
        response['Cache-Control'] = 'private, no-store'
        return response


class DisputesView(APIView):
    """GET /api/vendor-disputes?vendor=<name> (add &csv=1 for the file to send the vendor): that vendor's dispute
    candidates (Module 12 step 4). Every CSV download is logged; CiV never contacts vendors."""
    permission_classes = [IsClientUser]

    def get(self, request):
        import csv
        import io

        from django.http import HttpResponse

        from .disputes import candidates
        key = vendor_key(request.query_params.get('vendor') or '')
        found = candidates(request.user.client).get(key)
        if found is None:
            return Response({'detail': 'No leads from this vendor.'}, status=status.HTTP_404_NOT_FOUND)
        if request.query_params.get('csv'):
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(['lead', 'vendor', 'sub_id', 'date', 'price', 'result', 'reasons', 'number'])
            for r in found['rows']:
                w.writerow([r['lead'], r['vendor'], r['subId'] or '', r['date'], r['price'] or 'no price', r['result'], r['reasons'], r['number']])
            record('vendor_disputes_downloaded', request=request, actor_kind='client_user', actor_id=request.user.pk,
                   actor_label=request.user.email, client_id=request.user.client_id, object=f'{found["name"]} · {len(found["rows"])} leads'[:254])
            response = HttpResponse(out.getvalue(), content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="dispute-candidates-{key.replace(" ", "-")[:40]}.csv"'
            return response
        return Response({**found, 'total': str(found['total'])})
