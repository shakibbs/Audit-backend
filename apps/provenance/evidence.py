"""Evidence for numbers with no certificate (spec §5a evidence search). Read from a record while it is being synced;
only the fact, the date and the phone code are kept, never the message or the number.

- inbound_call: the person called the client (dialer or Twilio log, direction inbound).
- inbound_sms: the WHOLE text is a yes word (YES, Y, START, UNSTOP, SUBSCRIBE), read like STOP words.
- form_submission: the CRM says the record was made by the client's web form (HubSpot FORM, a Salesforce "Web" lead).
Purchases are the Module 6 existing-customer proofs; recordings wait for AI (Module 9).
"""
import re

from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.imports.creations import creation_facts
from apps.keyring.phones import normalize as clean_number

YES_WORDS = {'YES', 'Y', 'START', 'UNSTOP', 'SUBSCRIBE'}  # owner decision 2026-10-21: whole message only
INBOUND_DAYS = 30  # inbound_contact_scope is TBD (counsel B12): draft, live calls only


def yes_word(body: str) -> str:
    text = re.sub(r'[\s.!]+$', '', (body or '').strip()).upper()
    return text if re.sub(r'\s+', ' ', text) in YES_WORDS else ''


def found(client, connection, record, row: dict, tokens: list[str]) -> list[dict]:
    """Evidence in this record: [{kind, phone_token, at}]."""
    provider, out = connection.provider, []
    if record.content_kind == 'call' or (provider == 'hubspot' and record.source_record_id.startswith('calls:')):
        contact = ContactEvent.objects.filter(client=client, source_system=provider, source_record_id=record.source_record_id).first()
        if contact and contact.direction == 'inbound' and contact.channel == 'call':
            out.append({'kind': 'inbound_call', 'phone_token': contact.phone_token, 'at': contact.occurred_at})
    if provider == 'twilio' and record.content_kind == 'text' and str(row.get('direction', '')).startswith('inbound'):
        number = clean_number(row.get('from', ''))
        if number and yes_word(row.get('body', '')):
            out.append({'kind': 'inbound_sms', 'phone_token': codes_for(client).token(number), 'at': record.changed_at})
    if record.content_kind in ('lead', 'crm_record') and not record.source_record_id.startswith('calls:'):
        created_at, _, how = creation_facts(provider, record.raw)
        by_form = (provider == 'hubspot' and how in ('FORM', 'FORMS')) or (provider == 'salesforce' and str(row.get('LeadSource') or '').strip().lower() in ('web', 'website', 'web form'))
        if by_form and created_at:
            out += [{'kind': 'form_submission', 'phone_token': t, 'at': created_at} for t in tokens]
    return out
