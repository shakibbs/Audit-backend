"""Checks on a document: a file or a link (not neither), and files no bigger than 20 MB."""
from django import forms

from apps.documents.models import MAX_BYTES, ClientDocument


class DocumentForm(forms.ModelForm):
    class Meta:
        model = ClientDocument
        fields = ('kind', 'title', 'file', 'link', 'signed_on')

    def clean(self):
        data = super().clean()
        upload = data.get('file')
        if not upload and not data.get('link'):
            raise forms.ValidationError('Add a file or a link.')
        if upload and getattr(upload, 'size', 0) > MAX_BYTES:
            raise forms.ValidationError('The file is bigger than 20 MB.')
        return data
