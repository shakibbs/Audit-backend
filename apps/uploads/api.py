"""Client API: the Upload centre. GET lists the company's files; POST (multipart: source name + file) keeps the file
write-once, fingerprints it and reads its rows. Admins and the company's lawyer upload; everyone at the company sees the list."""
import hashlib
import logging
from pathlib import Path

from django.db import transaction
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .models import Source, UploadedFile
from .read import read

log = logging.getLogger('civ.uploads')

MAX_BYTES = 50 * 1024 * 1024
CSV = {'.csv', '.txt'}
DOCUMENTS = {'.pdf', '.doc', '.docx'}  # policies and contracts only
BY_NAME = {label: key for key, label in Source.choices}


def row(u: UploadedFile) -> dict:
    return {'artifactId': f'up-{u.pk}', 'source': u.get_source_display(), 'fileName': u.original_name, 'sha256': u.sha256,
            'receivedAt': u.received_at, 'rowsRead': u.rows_read, 'rowsRejected': u.rows_rejected}


class UploadsView(APIView):
    permission_classes = [IsClientUser]
    parser_classes = [MultiPartParser]

    def get(self, request):
        from apps.refs import month_span
        files = UploadedFile.objects.filter(client=request.user.client)
        if span := month_span(request.query_params.get('period')):  # files uploaded in the chosen month (2026-10-30)
            files = files.filter(received_at__date__gte=span[0], received_at__date__lt=span[1])
        return Response([row(u) for u in files[:200]])

    def post(self, request):
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your company lawyer can upload files.'}, status=403)
        source = BY_NAME.get(request.data.get('source', ''))
        upload = request.FILES.get('file')
        if source is None or upload is None:
            return Response({'detail': 'Choose what the file is and attach it.'}, status=400)
        allowed = CSV | DOCUMENTS if source == Source.POLICIES else CSV
        if Path(upload.name).suffix.lower() not in allowed or upload.size > MAX_BYTES:
            return Response({'detail': 'Use a CSV file of 50 MB or less (policies and contracts may also be PDF or Word).'}, status=400)
        content = upload.read()
        if not content.strip():
            return Response({'detail': 'That file is empty.'}, status=400)
        sha = hashlib.sha256(content).hexdigest()
        before = UploadedFile.objects.filter(client=user.client, source=source, sha256=sha).first()
        if before is not None:  # the same file again would count its rows twice (QA 2026-10-23)
            return Response({'detail': f'This file was already uploaded on {before.received_at:%-d %b %Y}.'}, status=400)
        saved = UploadedFile(client=user.client, source=source, original_name=upload.name[:255], sha256=sha, uploaded_by=user)
        upload.seek(0)
        try:
            with transaction.atomic():  # a file that cannot be read is not kept
                saved.file.save(upload.name, upload, save=False)
                saved.save()
                saved.rows_read, saved.rows_rejected = read(saved, content)
                saved.save(update_fields=['rows_read', 'rows_rejected'])
        except Exception:
            log.exception('Upload could not be read: %s', upload.name)
            if saved.file:
                saved.file.delete(save=False)
            return Response({'detail': 'CiV could not read this file. Check it is a normal CSV with one row per line.'}, status=400)
        from .effects import after_upload
        after_upload(saved)
        from apps.scoring.tasks import queue_refresh
        queue_refresh(user.client)  # scores, findings and reports follow within minutes, not tonight
        record('upload_received', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{saved} · {saved.rows_read} rows'[:254])
        return Response(row(saved))
