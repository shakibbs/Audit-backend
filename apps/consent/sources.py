"""Where a proof came from (owner decision 2026-10-21): the client's own consent form straight into its CRM, a lead
vendor (an automatic feed or an uploaded list), or unknown. Never guessed. The label never skips a check.

- HubSpot says how each record was made (hs_object_source): FORM → own form; IMPORT → uploaded list; INTEGRATION /
  API → vendor feed.
- Salesforce: an uploaded list or an automatic feed is seen from the creation pattern (Module 5 import batches); a
  lead whose LeadSource says "Web" and that is not part of one is the client's own web form.
"""
from apps.imports.models import CrmCreation, ImportBatch

CLIENT_FORM, VENDOR, UPLOADED_LIST, UNKNOWN = 'client_form', 'vendor', 'uploaded_list', 'unknown'
LABEL = {CLIENT_FORM: "Client's own form", VENDOR: 'From a vendor', UPLOADED_LIST: 'From a vendor (uploaded list)', UNKNOWN: 'Source unknown'}
HUBSPOT = {'FORM': CLIENT_FORM, 'FORMS': CLIENT_FORM, 'IMPORT': UPLOADED_LIST, 'INTEGRATION': VENDOR, 'API': VENDOR}


def hint_from_record(provider: str, row: dict) -> str:
    """What the tool itself says about how the record was made, kept as a short word (no personal data)."""
    if provider == 'hubspot':
        return str(row.get('properties', {}).get('hs_object_source') or '').upper()[:30]
    if provider == 'salesforce':
        return str(row.get('LeadSource') or '')[:30]
    return ''


def source_of(proof) -> str:
    if proof.source_system == 'vendor_lead_file':
        return VENDOR  # a consent link sent by the vendor with the lead (Module 12)
    if proof.source_system == 'hubspot' and proof.source_hint in HUBSPOT:
        return HUBSPOT[proof.source_hint]
    creation = (CrmCreation.objects.filter(client_id=proof.client_id, source_system=proof.source_system, record_id=proof.source_record_id)
                .select_related('batch').first())
    batch = creation.batch if creation else None
    if batch and batch.kind in (ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL):
        return UPLOADED_LIST
    if batch and batch.kind == ImportBatch.Kind.FEED:
        return VENDOR
    if proof.source_system == 'salesforce' and 'web' in proof.source_hint.lower():
        return CLIENT_FORM
    return UNKNOWN


CUSTODY = {'claimed': "Claimed in the client's account", 'lost': 'Not claimed in time', 'not_found': 'Provider does not have it',
           'waiting': 'Being claimed', 'no_key': 'Waiting for the certificate account'}


def custody_of(claim) -> str:
    """Who holds the certificate. CiV claims it in the client's own account, so a claimed one is the client's. A
    vendor-only holder cannot be seen through the API (to confirm on a real account): never guessed."""
    if claim.state == 'lost':
        return 'not_found' if claim.last_error == 'NotFound' else 'lost'
    return claim.state
