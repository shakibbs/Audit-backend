"""Opens a client document for CiV staff only. Files are never served from a public address."""
import mimetypes

from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from apps.access_log.recorder import record
from apps.documents.models import ClientDocument

SHOW_IN_BROWSER = {'application/pdf', 'image/png', 'image/jpeg'}


def open_document(request, client_id, document_id):
    if not request.user.has_perm('documents.view_clientdocument'):
        raise PermissionDenied
    document = get_object_or_404(ClientDocument, pk=document_id, client_id=client_id)
    if not document.file:
        raise Http404
    record('document_opened', request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=document.client_id, object=f'{document.get_kind_display()}: {document}')
    content_type = mimetypes.guess_type(document.file.name)[0] or 'application/octet-stream'
    response = FileResponse(document.file.open('rb'), content_type=content_type,
                            as_attachment=content_type not in SHOW_IN_BROWSER,
                            filename=document.original_name or document.file.name.rsplit('/', 1)[-1])
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
