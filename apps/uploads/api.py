"""Client API: the Upload centre. GET lists the company's files; POST (multipart: source name + file) keeps the file
write-once, fingerprints it and reads its rows. Admins and the company's lawyer upload; everyone at the company sees the list."""
import hashlib
from pathlib import Path

from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .models import Source, UploadedFile
from .read import read

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
        return Response([row(u) for u in UploadedFile.objects.filter(client=request.user.client)[:200]])

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
        saved = UploadedFile(client=user.client, source=source, original_name=upload.name[:255], sha256=hashlib.sha256(content).hexdigest(),
                             uploaded_by=user)
        upload.seek(0)
        saved.file.save(upload.name, upload, save=False)
        saved.save()
        saved.rows_read, saved.rows_rejected = read(saved, content)
        saved.save(update_fields=['rows_read', 'rows_rejected'])
        from .effects import after_upload
        after_upload(saved)
        record('upload_received', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{saved} · {saved.rows_read} rows'[:254])
        return Response(row(saved))
