"""The client company form, with a box for why the stage changed."""
from django import forms
from unfold.widgets import UnfoldAdminTextInputWidget

from apps.clients.models import Client


class ClientForm(forms.ModelForm):
    status_reason = forms.CharField(
        required=False, max_length=300, label='Reason for stage change',
        widget=UnfoldAdminTextInputWidget(attrs={'placeholder': 'e.g. Contract signed 10 Oct; pilot ended'}),
        help_text='Optional. Saved in the stage history when the stage changes.')

    class Meta:
        model = Client
        fields = '__all__'
