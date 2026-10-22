"""The client company form, with a box for why the stage changed and, for a new client, its first Admin (who gets an
invitation link to choose their own password)."""
from django import forms
from unfold.widgets import UnfoldAdminEmailInputWidget, UnfoldAdminTextInputWidget

from apps.clients.models import Client


class ClientForm(forms.ModelForm):
    status_reason = forms.CharField(
        required=False, max_length=300, label='Reason for stage change',
        widget=UnfoldAdminTextInputWidget(attrs={'placeholder': 'e.g. Contract signed 10 Oct; pilot ended'}),
        help_text='Optional. Saved in the stage history when the stage changes.')

    admin_name = forms.CharField(required=False, max_length=150, label="Client Admin's name",
                                 widget=UnfoldAdminTextInputWidget(attrs={'placeholder': 'e.g. Dana Ruiz'}))
    admin_email = forms.EmailField(required=False, label="Client Admin's email", widget=UnfoldAdminEmailInputWidget(),
                                   help_text='They get an invitation link (7 days) to choose their own password and sign in as Admin.')

    class Meta:
        model = Client
        fields = '__all__'

    def clean(self):
        data = super().clean()
        if self.instance.pk is None:  # a new client always gets its first Admin
            from apps.accounts.invites import taken
            if not data.get('admin_name', '').strip():
                self.add_error('admin_name', "Enter the client Admin's name.")
            email = data.get('admin_email', '')
            if not email:
                self.add_error('admin_email', "Enter the client Admin's email.")
            elif taken(email):
                self.add_error('admin_email', 'That email already has an account.')
        return data
