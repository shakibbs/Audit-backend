"""The tools a client can connect, what kind each is, and how it signs in."""
from dataclasses import dataclass


class Kind:
    DIALER = 'dialer'
    SMS = 'sms'
    CERTIFICATES = 'certificates'
    LEAD_FEED = 'lead_feed'
    CRM = 'crm'

    CHOICES = [
        (DIALER, 'Dialer'), (SMS, 'Texting tool'), (CERTIFICATES, 'Certificate account'),
        (LEAD_FEED, 'Lead feed copy'), (CRM, 'CRM'),
    ]


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str
    # 'api_key': we paste the client's read-only key. 'oauth': the client clicks Allow on the tool's own page.
    auth: str
    account_label: str = ''  # what "account ID" means for this tool, if it needs one
    key_label: str = 'API key'
    secret_label: str = ''  # what "secret" means for this tool, if it needs one


PROVIDERS = {
    'five9': Provider('Five9', Kind.DIALER, 'api_key', account_label='Username', key_label='Password'),
    'convoso': Provider('Convoso', Kind.DIALER, 'api_key', key_label='Auth token'),
    'ringcentral': Provider('RingCentral', Kind.DIALER, 'oauth'),
    'twilio': Provider('Twilio', Kind.SMS, 'api_key', account_label='Account SID', key_label='Auth token'),
    'trustedform': Provider('TrustedForm', Kind.CERTIFICATES, 'api_key'),
    'jornaya': Provider('Jornaya', Kind.CERTIFICATES, 'api_key'),
    'lead_feed': Provider('Lead feed copy (CiV as extra destination)', Kind.LEAD_FEED, 'api_key', key_label='Shared secret'),
    'salesforce': Provider('Salesforce', Kind.CRM, 'oauth'),
    'hubspot': Provider('HubSpot', Kind.CRM, 'oauth'),
    'other_dialer': Provider('Other dialer', Kind.DIALER, 'api_key', account_label='Account ID', secret_label='API secret'),
    'other_sms': Provider('Other texting tool', Kind.SMS, 'api_key', account_label='Account ID', secret_label='API secret'),
    'other_crm': Provider('Other CRM', Kind.CRM, 'api_key', account_label='Account ID', secret_label='API secret'),
}

# Grouped by type in the dropdown, e.g. "Dialer: Five9, Convoso, …".
PROVIDER_CHOICES = [
    (label, [(code, p.name) for code, p in PROVIDERS.items() if p.kind == kind]) for kind, label in Kind.CHOICES
]
