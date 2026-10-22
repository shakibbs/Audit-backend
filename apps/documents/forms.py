"""Checks on a document: a file or a link (not neither), and files no bigger than 20 MB."""
from django import forms

from apps.documents.models import MAX_BYTES, ClientDocument


class PrivateFileInput(forms.ClearableFileInput):
    """Files are private (no public address), so the box shows no "currently: <link>"; the row's Open button opens the
    file and logs it (bug fix 2026-10-23: that link and its download icon went to a "not found" page)."""
    def is_initial(self, value):
        return False


class DocumentForm(forms.ModelForm):
    class Meta:
        model = ClientDocument
        fields = ('kind', 'title', 'file', 'link', 'signed_on')
        widgets = {'file': PrivateFileInput}

    def clean(self):
        data = super().clean()
        upload = data.get('file')
        if not upload and not data.get('link'):
            raise forms.ValidationError('Add a file or a link.')
        if upload and getattr(upload, 'size', 0) > MAX_BYTES:
            raise forms.ValidationError('The file is bigger than 20 MB.')
        return data
