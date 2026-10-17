"""Consent results in the portal's words: status names, reason codes in plain English, the five checks' states."""
from .models import ConsentResult

REASONS = {
    'VF_OK': 'All checks CiV can run passed.',
    'NP_NONE': 'No proof of permission on record for this owner of the number.',
    'NP_SELF_ASSERTED': 'Only a CRM consent field says yes: never enough on its own.',
    'NP_NO_EVIDENCE_FOUND': 'The number came from an uploaded list with no evidence behind it.',
    'NP_BEFORE_CONSENT': 'The contact happened before the permission was given.',
    'NP_AFTER_OPT_OUT': 'The person had said STOP before this contact.',
    'NP_RELATIONSHIP_LAPSED': 'The existing-customer relationship had run out by the contact date.',
    'NP_WRONG_TYPE': 'The proof on record is not the kind this contact needs.',
    'CF_NOT_FOUND': 'The certificate provider does not have this certificate.',
    'CF_EXPIRED': 'The certificate expired before CiV could claim it.',
    'CF_CERT_AFTER_DELIVERY': 'The certificate was made after the lead was delivered.',
    'WK_TIMING_UNCERTAIN': 'The proof and the contact are within the clock tolerance of each other.',
    'WK_RETENTION': 'The certificate expires soon or is not kept long-term.',
    'PD_NOT_READ_YET': 'The certificate has not been read yet: left out of totals until it is.',
    'PD_NO_CERT_ACCOUNT': 'No certificate account is connected, so the certificate cannot be read yet.',
    'FZ_SOURCE_DELETED': 'The record this result stood on was deleted from the tool: result frozen.',
    'FZ_INPUTS_CHANGED': 'The record changed after it was checked: result frozen.',
}
NOT_MEASURED = {
    'not_measured:consent_wording': 'Consent wording and pre-ticked boxes (Module 7)',
    'not_measured:phone_match': 'Phone number on the form matches the number called (Module 7)',
    'not_measured:page_match': 'Page capture matches the certificate (Module 7)',
    'not_measured:lead_trace': 'Lead traced to a named vendor or the client’s own form (Module 8)',
    'not_measured:seller_name': 'Seller named in the consent wording (Module 7)',
}
LABELS = {'EBR_ONLY': 'existing customer only', 'pre_engagement': 'before CiV started', 'category_unknown': 'counted as marketing',
          'dial_mode_unknown': 'dial mode unknown', 'dnc_list_not_supplied': 'DNC list not supplied'}
CHANGE_REASONS = {'new_contact': 'first check', 'certificate_read': 'certificate read', 'new_proof': 'new proof',
                  'late_opt_out': 'STOP received', 'owner_changed': 'new owner of the number', 'rule_changed': 'Rulebook change',
                  'time_passed': 'time passed', 'frozen': 'frozen'}
DEFERRED = 'not_measured'  # a check CiV cannot run yet


def portal_status(result: ConsentResult | None) -> str:
    return 'NOT_CHECKED' if result is None else result.status.upper()


def reason_text(result: ConsentResult | None) -> str:
    if result is None:
        return 'Not checked yet: the consent engine looks at each new contact within a minute or two.'
    if result.status == ConsentResult.Status.NOT_NEEDED:
        return 'No consent needed: the person contacted the client, or it is one of CiV’s test numbers.'
    text = REASONS.get(result.primary_code, result.primary_code)
    if result.frozen:
        text = f'{text} {REASONS[result.frozen_reason]}'
    return text


def check_states(result: ConsentResult | None) -> list[str]:
    """The five checks in order: pass · fails · gap · not_reached · not_measured."""
    if result is None or result.status == ConsentResult.Status.NOT_NEEDED:
        return []
    code = result.primary_code
    rest = lambda n: ['not_reached'] * n  # noqa: E731
    if code.startswith('NP_'):
        return ['fails', *rest(4)]
    if code in ('CF_NOT_FOUND', 'CF_EXPIRED'):
        return ['pass', 'fails', *rest(3)]
    if code.startswith('PD_'):
        return ['pass', 'gap', *rest(3)]
    if code == 'CF_CERT_AFTER_DELIVERY':
        return ['pass', 'pass', DEFERRED, 'fails', 'not_reached']
    if code.startswith('WK_'):
        return ['pass', 'pass', DEFERRED, 'pass', 'gap']
    return ['pass', 'pass', DEFERRED, 'pass', 'pass']


def proof_text(result: ConsentResult | None) -> str:
    proof = result.proof if result else None
    if proof is None:
        return '—'
    if proof.certificate_id:
        made = proof.when()
        return f'{proof.certificate.get_provider_display()} certificate · made {made:%d %b %Y}' if made else f'{proof.certificate.get_provider_display()} certificate'
    return {'ebr_purchase': 'Existing customer (purchase)', 'ebr_inquiry': 'Existing customer (inquiry)',
            'self_asserted': 'CRM consent field'}.get(proof.kind, proof.kind)


def label_words(result: ConsentResult | None) -> list[str]:
    if result is None:
        return []
    words = [LABELS[l] for l in result.labels if l in LABELS]
    if result.frozen:
        words.append('frozen')
    return words
