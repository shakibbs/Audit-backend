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
        (LEAD_FEED, 'Lead feed or lead platform'), (CRM, 'CRM'),
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


# Every tool a client may connect. Clients use different systems, so all stay available; a tool is read only once
# its adapter exists (apps/sync/connectors). Until then it shows "Saved, not tested". Order = order in the dropdown.
PROVIDERS = {
    # Dialers
    'five9': Provider('Five9', Kind.DIALER, 'api_key', account_label='Username (reports only)', key_label='Password', secret_label='Report time zone (e.g. America/New_York)'),
    'convoso': Provider('Convoso', Kind.DIALER, 'api_key', key_label='Auth token', secret_label='Account time zone (e.g. America/New_York)'),
    'ringcentral': Provider('RingCentral', Kind.DIALER, 'oauth'),
    'vicidial': Provider('Vicidial', Kind.DIALER, 'api_key', account_label='Database server (host:port/database)', key_label='Read-only database user', secret_label='Password'),
    'genesys': Provider('Genesys Cloud', Kind.DIALER, 'api_key', account_label='Client ID', key_label='Client secret', secret_label='Region (e.g. mypurecloud.com)'),
    'nice_cxone': Provider('NICE CXone', Kind.DIALER, 'oauth'),
    'talkdesk': Provider('Talkdesk', Kind.DIALER, 'oauth'),
    'readymode': Provider('ReadyMode', Kind.DIALER, 'api_key', account_label='Account domain', key_label='API key'),
    'aircall': Provider('Aircall', Kind.DIALER, 'api_key', account_label='API ID', key_label='API token'),
    'dialpad': Provider('Dialpad', Kind.DIALER, 'api_key', key_label='API key'),
    'amazon_connect': Provider('Amazon Connect', Kind.DIALER, 'api_key', account_label='Access key ID', key_label='Secret access key', secret_label='Instance ID and region'),
    'other_dialer': Provider('Other dialer', Kind.DIALER, 'api_key', account_label='Account ID', secret_label='API secret'),
    # Texting
    'twilio': Provider('Twilio', Kind.SMS, 'api_key', account_label='Account SID', key_label='Auth token'),
    'telnyx': Provider('Telnyx', Kind.SMS, 'api_key', key_label='API key'),
    'bandwidth': Provider('Bandwidth', Kind.SMS, 'api_key', account_label='Account ID', key_label='API username', secret_label='API password'),
    'plivo': Provider('Plivo', Kind.SMS, 'api_key', account_label='Auth ID', key_label='Auth token'),
    'vonage': Provider('Vonage', Kind.SMS, 'api_key', account_label='API key', key_label='API secret'),
    'sinch': Provider('Sinch', Kind.SMS, 'api_key', account_label='Service plan ID', key_label='API token'),
    'other_sms': Provider('Other texting tool', Kind.SMS, 'api_key', account_label='Account ID', secret_label='API secret'),
    # Consent certificates
    'trustedform': Provider('TrustedForm', Kind.CERTIFICATES, 'api_key', key_label='API key'),
    'jornaya': Provider('Jornaya', Kind.CERTIFICATES, 'api_key', account_label='Account code (LAC)', key_label='API key'),
    # Lead feeds and lead platforms
    'lead_feed': Provider('Lead feed copy (CiV as extra destination)', Kind.LEAD_FEED, 'api_key', key_label='Shared secret'),
    'leadconduit': Provider('LeadConduit (ActiveProspect)', Kind.LEAD_FEED, 'api_key', account_label='Account ID', key_label='API key'),
    'boberdoo': Provider('Boberdoo', Kind.LEAD_FEED, 'api_key', account_label='Server address', key_label='API key'),
    'leadspedia': Provider('LeadsPedia', Kind.LEAD_FEED, 'api_key', account_label='Account', key_label='API key', secret_label='API secret'),
    'phonexa': Provider('Phonexa', Kind.LEAD_FEED, 'api_key', account_label='Account', key_label='API key'),
    # CRMs
    'salesforce': Provider('Salesforce', Kind.CRM, 'oauth'),
    'hubspot': Provider('HubSpot', Kind.CRM, 'oauth'),
    'zoho': Provider('Zoho CRM', Kind.CRM, 'oauth'),
    'gohighlevel': Provider('GoHighLevel', Kind.CRM, 'oauth'),
    'velocify': Provider('Velocify', Kind.CRM, 'api_key', account_label='Username', key_label='Password'),
    'dynamics': Provider('Microsoft Dynamics 365', Kind.CRM, 'oauth'),
    'pipedrive': Provider('Pipedrive', Kind.CRM, 'api_key', key_label='API token'),
    'other_crm': Provider('Other CRM', Kind.CRM, 'api_key', account_label='Account ID', secret_label='API secret'),
}

# Grouped by type in the dropdown, e.g. "Dialer: Five9, Convoso, …".
PROVIDER_CHOICES = [
    (label, [(code, p.name) for code, p in PROVIDERS.items() if p.kind == kind]) for kind, label in Kind.CHOICES
]
