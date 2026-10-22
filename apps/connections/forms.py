"""Add / edit form for a connection. Key fields are write-only: they are never filled back in."""
from django import forms
from unfold.widgets import UnfoldAdminPasswordToggleWidget, UnfoldAdminSelectWidget, UnfoldAdminTextInputWidget

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
            if p.setting_label:
                parts.append(f'{p.setting_label} → Time zone or region')
            lines.append(f'{p.name}: ' + ', '.join(parts))
    return lines


# The "Time zone or region" dropdown (owner, 2026-10-23: pick, don't type). US zones first: clients call US numbers.
TIME_ZONES = [
    ('America/New_York', 'Eastern — New York'), ('America/Chicago', 'Central — Chicago'), ('America/Denver', 'Mountain — Denver'),
    ('America/Phoenix', 'Arizona — Phoenix (no daylight saving)'), ('America/Los_Angeles', 'Pacific — Los Angeles'),
    ('America/Anchorage', 'Alaska — Anchorage'), ('Pacific/Honolulu', 'Hawaii — Honolulu'), ('America/Puerto_Rico', 'Atlantic — Puerto Rico'),
    ('UTC', 'UTC'), ('America/Toronto', 'Toronto'), ('America/Mexico_City', 'Mexico City'), ('Europe/London', 'London'),
    ('Asia/Manila', 'Manila'), ('Asia/Kolkata', 'India — Kolkata'), ('Asia/Dhaka', 'Dhaka'),
]
GENESYS_REGIONS = [
    ('mypurecloud.com', 'US East (Virginia) — mypurecloud.com'), ('use2.us-gov-pure.cloud', 'US East 2 (Gov) — use2.us-gov-pure.cloud'),
    ('usw2.pure.cloud', 'US West (Oregon) — usw2.pure.cloud'), ('cac1.pure.cloud', 'Canada — cac1.pure.cloud'),
    ('mypurecloud.ie', 'EU West (Ireland) — mypurecloud.ie'), ('euw2.pure.cloud', 'EU West 2 (London) — euw2.pure.cloud'),
    ('mypurecloud.de', 'EU Central (Frankfurt) — mypurecloud.de'), ('aps1.pure.cloud', 'Asia Pacific (Mumbai) — aps1.pure.cloud'),
    ('mypurecloud.com.au', 'Asia Pacific (Sydney) — mypurecloud.com.au'), ('mypurecloud.jp', 'Asia Pacific (Tokyo) — mypurecloud.jp'),
    ('sae1.pure.cloud', 'South America (São Paulo) — sae1.pure.cloud'),
]
SETTING_CHOICES = [('', '— Not needed for this tool —'),
                   ('Time zone (Five9, Convoso, Vicidial)', TIME_ZONES), ('Region (Genesys)', GENESYS_REGIONS)]


class ConnectionForm(forms.ModelForm):
    account = forms.CharField(required=False, label='Account ID / username', widget=UnfoldAdminTextInputWidget(attrs={'autocomplete': 'off'}),
                              help_text='Only for tools that need one (see "Which fields each tool needs").')
    key = forms.CharField(required=False, label='API key / token', widget=UnfoldAdminPasswordToggleWidget(attrs={'autocomplete': 'new-password'}),
                          help_text='Read-only key from the client. Locked when saved; never shown again.')
    secret = forms.CharField(required=False, label='API secret', widget=UnfoldAdminPasswordToggleWidget(attrs={'autocomplete': 'new-password'}),
                             help_text='Only for tools that need a second secret.')

    class Meta:
        model = Connection
        fields = ('client', 'provider', 'label', 'setting')
        help_texts = {'setting': 'Pick the tool\'s time zone (Five9, Convoso, Vicidial) or its region (Genesys). '
                                 'Not a secret: stays visible. "Not needed" for other tools.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(SETTING_CHOICES)
        current = getattr(self.instance, 'setting', '')
        known = {v for _, group in SETTING_CHOICES[1:] for v, _ in group}
        if current and current not in known:  # a value saved before the list: kept, never lost
            choices.append(('Saved earlier', [(current, current)]))
        self.fields['setting'] = forms.ChoiceField(required=False, choices=choices, label='Time zone or region',
                                                   widget=UnfoldAdminSelectWidget, help_text=self.fields['setting'].help_text)

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
        fields = ('provider', 'label', 'setting')

