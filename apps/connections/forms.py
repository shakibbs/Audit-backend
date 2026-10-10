"""Add / edit form for a connection. Key fields are write-only: they are never filled back in."""
from django import forms
from unfold.widgets import UnfoldAdminPasswordToggleWidget, UnfoldAdminTextInputWidget

from apps.connections.models import Connection
from apps.connections.providers import PROVIDERS


def key_guide() -> str:
    """One line per tool: which fields it needs."""
    lines = []
    for p in PROVIDERS.values():
        if p.auth == 'oauth':
            lines.append(f'{p.name}: no key, send a connect link')
        else:
            parts = [f'{p.account_label} → Account ID'] if p.account_label else []
            parts.append(f'{p.key_label} → API key')
            if p.secret_label:
                parts.append(f'{p.secret_label} → API secret')
            lines.append(f'{p.name}: ' + ', '.join(parts))
    return lines


class ConnectionForm(forms.ModelForm):
    account = forms.CharField(required=False, label='Account ID / username', widget=UnfoldAdminTextInputWidget(attrs={'autocomplete': 'off'}),
                              help_text='Only for tools that need one (see "Which fields each tool needs").')
    key = forms.CharField(required=False, label='API key / token', widget=UnfoldAdminPasswordToggleWidget(attrs={'autocomplete': 'new-password'}),
                          help_text='Read-only key from the client. Locked when saved; never shown again.')
    secret = forms.CharField(required=False, label='API secret', widget=UnfoldAdminPasswordToggleWidget(attrs={'autocomplete': 'new-password'}),
                             help_text='Only for tools that need a second secret.')

    class Meta:
        model = Connection
        fields = ('client', 'provider', 'label')

    def new_credentials(self) -> dict:
        if not hasattr(self, 'cleaned_data'):
            return {}
        return {k: self.cleaned_data.get(k, '').strip() for k in ('account', 'key', 'secret') if self.cleaned_data.get(k, '').strip()}

    def clean(self):
        data = super().clean()
        provider = PROVIDERS.get(data.get('provider', ''))
        if provider and provider.auth == 'oauth' and self.new_credentials():
            raise forms.ValidationError(f'{provider.name} connects by the client clicking Allow. Leave the key fields empty and use "Send connect link".')
        return data


class ConnectionInlineForm(ConnectionForm):
    """The same form inside a client company's page: the client is that page's company."""

    class Meta(ConnectionForm.Meta):
        fields = ('provider', 'label')

