"""The Documents tab on a client company's page."""
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import StackedInline

from apps.access_log.recorder import record
from apps.documents.fingerprint import sha256_of
from apps.documents.forms import DocumentForm
from apps.documents.models import ClientDocument


class DocumentInline(StackedInline):
    model = ClientDocument
    form = DocumentForm
    tab = True
    extra = 0
    verbose_name = 'document'
    verbose_name_plural = 'Documents'
    fields = ('kind', 'title', 'file', 'link', 'signed_on', 'open_link', 'fingerprint', 'uploaded')
    readonly_fields = ('open_link', 'fingerprint', 'uploaded')

    @admin.display(description='Open')
    def open_link(self, document):
        if document.pk and document.file:
            url = reverse('admin:clients_client_document_open', args=[document.client_id, document.pk])
            return format_html('<a class="civ-btn" href="{}" target="_blank" rel="noopener">Open {}</a>', url, document.original_name or 'file')
        if document.link:
            return format_html('<a class="civ-btn civ-btn-ghost" href="{}" target="_blank" rel="noopener noreferrer">Open link</a>', document.link)
        return '-'

    @admin.display(description='Fingerprint (SHA-256)')
    def fingerprint(self, document):
        return format_html('<span class="civ"><span class="mono tiny" title="{}">{}…</span></span>', document.sha256, document.sha256[:16]) if document.sha256 else '-'

    @admin.display(description='Uploaded')
    def uploaded(self, document):
        if not document.pk:
            return 'When you click Save'
        who = document.uploaded_by.name if document.uploaded_by else 'CiV'
        size = f' · {document.size / 1024:,.0f} KB' if document.size else ''
        return f'{who} · {document.uploaded_at:%d %b %Y %H:%M} UTC{size}'


def save_documents(request, formset) -> None:
    """Saves the tab: fingerprints new files, removes deleted ones from disk, logs every change."""
    formset.save(commit=False)  # fills deleted_objects and the lists the admin's change message reads

    def log(action, document):
        record(action, request=request, actor_kind='staff', actor_id=request.user.pk, actor_label=request.user.email,
               client_id=document.client_id, object=f'{document.get_kind_display()}: {document}')

    for document in formset.deleted_objects:
        log('document_removed', document)
        if document.file:
            document.file.delete(save=False)
        document.delete()
    for form in formset.forms:
        if form in formset.deleted_forms or not form.has_changed():
            continue
        document = form.save(commit=False)
        created = document.pk is None
        if 'file' in form.changed_data and form.cleaned_data.get('file'):
            upload = form.cleaned_data['file']
            document.sha256, document.size, document.original_name = sha256_of(upload), upload.size, upload.name[:255]
            document.uploaded_by = request.user
        elif created:
            document.uploaded_by = request.user
        document.save()
        log('document_added' if created else 'document_changed', document)
