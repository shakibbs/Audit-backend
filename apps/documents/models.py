"""Signed paperwork between CiV and a client (agreement, Annex C, statements). Never the client's customer records."""
import uuid
from pathlib import Path

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from apps.clients.models import Client

ALLOWED_EXTENSIONS = ['pdf', 'png', 'jpg', 'jpeg', 'docx']
MAX_BYTES = 20 * 1024 * 1024  # 20 MB


def upload_path(document, filename: str) -> str:
    # A random name on disk; the original name is kept in the database.
    return f'client-docs/{document.client_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class ClientDocument(models.Model):
    class Kind(models.TextChoices):
        AGREEMENT = 'agreement', 'Service agreement'
        ANNEX_C = 'annex_c', 'Annex C (test opt-out permission)'
        STATEMENT = 'statement', 'Signed statement (Insured states)'
        DPA = 'dpa', 'Data processing agreement (DPA)'
        OTHER = 'other', 'Other'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='documents')
    kind = models.CharField('type', max_length=20, choices=Kind.choices, default=Kind.AGREEMENT)
    title = models.CharField(max_length=200, blank=True, help_text='Optional, e.g. "MSA v2, signed by J. Smith".')
    file = models.FileField(upload_to=upload_path, blank=True,
                            validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
                            help_text='PDF, image or Word file, up to 20 MB. Kept privately on the server.')
    link = models.URLField('or link', blank=True, help_text='If the file lives elsewhere (Google Drive, DocuSign…).')
    signed_on = models.DateField(null=True, blank=True)
    original_name = models.CharField(max_length=255, blank=True, editable=False)
    sha256 = models.CharField('fingerprint (SHA-256)', max_length=64, blank=True, editable=False)
    size = models.PositiveIntegerField(null=True, blank=True, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    editable=False, related_name='+')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'client_document'
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.title or self.get_kind_display()
