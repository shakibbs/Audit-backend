"""The five checks (spec §5): for each basis a contact needs, filter the owner's proofs (check 1), judge each one left
(checks 2–5), keep the best; the contact's result is the worst basis. Time checks use evaluation_as_of, not the clock.

Not measured yet (never change a result): consent wording and pre-ticked boxes, phone and page match (Module 7), lead
trace (Module 8), seller name. They are listed in the result's labels.
"""
from datetime import timedelta

from django.utils import timezone

from apps.certificates.models import CertificateClaim
from apps.contacts.epochs import epoch_for
from apps.imports.models import CrmCreation
from apps.rulebook.lookup import RuleSet

from .models import ConsentNeed, ConsentProof, ConsentResult
from .needs import ebr_active, meets, opt_out_in_force
from .proofs import evidence_folder

S = ConsentResult.Status
BEST_FIRST = [S.VERIFIED, S.WEAK, S.PENDING, S.CONFLICTING, S.NO_PROOF]  # best proof per basis; reversed: worst basis
CHECK1_ORDER = ['NP_NONE', 'NP_SELF_ASSERTED', 'NP_NO_EVIDENCE_FOUND', 'NP_BEFORE_CONSENT', 'NP_AFTER_OPT_OUT',
                'NP_RELATIONSHIP_LAPSED', 'NP_WRONG_TYPE']
NOT_MEASURED = ['not_measured:consent_wording', 'not_measured:phone_match', 'not_measured:page_match',
                'not_measured:lead_trace', 'not_measured:seller_name']
EBR = (ConsentProof.Kind.EBR_PURCHASE, ConsentProof.Kind.EBR_INQUIRY)


def _value(rules, key, contact, variant, default):
    found = rules.get(key, on=contact.occurred_at.date(), variant=variant).value
    return default if found is None else found


def _timing(proof, contact, skew) -> str:
    """'' = before the contact, 'uncertain' = within the clock tolerance, 'after' = later."""
    when = proof.when()
    if when is None:
        return 'after'
    if proof.lead_id and proof.lead_id == contact.lead_id:  # linked: the chain proves the order, no tolerance
        return '' if when <= contact.occurred_at else 'after'
    if when < contact.occurred_at - skew:
        return ''
    return 'uncertain' if when <= contact.occurred_at + skew else 'after'


def check_one(proof, basis, contact, robocall, rules, variant, optout, skew) -> tuple[list[str], bool]:
    """Check 1 for one proof: the codes that remove it, and whether its timing is uncertain."""
    if proof.kind == ConsentProof.Kind.SELF_ASSERTED:
        return ['NP_SELF_ASSERTED'], False
    codes = []
    timing = _timing(proof, contact, skew)
    if timing == 'after':
        codes.append('NP_BEFORE_CONSENT')
    if optout and (proof.kind in EBR or (proof.when() or optout.at) <= optout.at):
        codes.append('NP_AFTER_OPT_OUT')  # only a new consent after the opt-out restores coverage, never a purchase
    if proof.kind in EBR and not ebr_active(proof, contact, rules, variant):
        codes.append('NP_RELATIONSHIP_LAPSED')
    elif not meets(proof, basis, contact, robocall, rules, variant):
        codes.append('NP_WRONG_TYPE')
    return codes, timing == 'uncertain'


def _delivered_at(proof):
    found = CrmCreation.objects.filter(client_id=proof.client_id, source_system=proof.source_system, record_id=proof.source_record_id).first()
    return found.created_at if found else None


def judge(proof, contact, uncertain, as_of, skew, warning_days, client_start) -> tuple[str, list[str], list[str]]:
    """Checks 2–5 for one proof that passed check 1: (status, codes, labels)."""
    labels = ['EBR_ONLY'] if proof.kind in EBR else []
    claim = proof.certificate
    if proof.kind == ConsentProof.Kind.CERTIFICATE and claim is not None:
        # 2. Does it open at its source?
        if claim.state == CertificateClaim.State.LOST:
            if claim.last_error == 'NotFound':
                return S.CONFLICTING, ['CF_NOT_FOUND'], labels
            if claim.deadline_at.date() < client_start:
                labels.append('pre_engagement')
            return S.CONFLICTING, ['CF_EXPIRED'], labels
        if claim.state != CertificateClaim.State.CLAIMED:
            return S.PENDING, ['PD_NO_CERT_ACCOUNT' if claim.state == CertificateClaim.State.NO_KEY else 'PD_NOT_READ_YET'], labels
        # 4. Do the sources agree? (certificate made after the lead was delivered)
        delivered = _delivered_at(proof)
        if delivered and claim.cert_created_at and claim.cert_created_at > delivered + skew:
            return S.CONFLICTING, ['CF_CERT_AFTER_DELIVERY'], labels
        if delivered and claim.cert_created_at and claim.cert_created_at > delivered:
            uncertain = True
    # 5. Completeness.
    codes = []
    if uncertain:
        codes.append('WK_TIMING_UNCERTAIN')
    if claim is not None and (claim.cert_expires_at is None or claim.cert_expires_at <= as_of + timedelta(days=warning_days)):
        codes.append('WK_RETENTION')
    return (S.WEAK, codes, labels) if codes else (S.VERIFIED, ['VF_OK'], labels)


def evaluate(contact, need: ConsentNeed, rules: RuleSet, as_of=None) -> dict:
    as_of = as_of or timezone.now()
    variant = need.variant
    base = {'evaluation_as_of': as_of, 'rulebook_version': rules.version.version, 'is_legal_basis': need.is_legal_basis}
    if not need.bases:
        return {**base, 'status': S.NOT_NEEDED, 'primary_code': '', 'codes': [], 'bases': [], 'proof': None, 'labels': []}
    skew = timedelta(seconds=int(_value(rules, 'clock_skew_seconds', contact, variant, 120)))
    warning_days = int(_value(rules, 'cert_expiry_warning_days', contact, variant, 30))
    epoch = contact.epoch or epoch_for(contact.client_id, contact.phone_token, contact.occurred_at)
    folder = evidence_folder(contact.client, contact.phone_token, epoch)
    proofs = [p for p in folder['proofs'] if p.withdrawn_at is None]  # a withdrawn proof is never used again
    optout = opt_out_in_force(contact, rules, variant, newer_consent_lifts=False)
    results, labels = [], set(NOT_MEASURED)
    for basis in need.bases:
        kept, fired = [], set()
        for proof in proofs:
            codes, uncertain = check_one(proof, basis, contact, need.robocall, rules, variant, optout, skew)
            if codes:
                fired.update(codes)
            else:
                kept.append((proof, uncertain))
        if not kept:
            if not proofs or all(p.kind == ConsentProof.Kind.SELF_ASSERTED for p in proofs):
                fired.add('NP_NONE' if not proofs else 'NP_SELF_ASSERTED')
                if folder['manual_import_no_evidence']:
                    fired.add('NP_NO_EVIDENCE_FOUND')
            codes = [c for c in CHECK1_ORDER if c in fired]
            results.append({'basis': basis['basis'], 'status': S.NO_PROOF, 'codes': codes, 'proof': None})
            continue
        judged = []
        for proof, uncertain in kept:
            status, codes, proof_labels = judge(proof, contact, uncertain, as_of, skew, warning_days, contact.client.start_date)
            judged.append((BEST_FIRST.index(status), -(proof.when() or as_of).timestamp(), proof, status, codes, proof_labels))
        judged.sort(key=lambda j: (j[0], j[1]))  # best status, then the most recently captured proof
        _, _, proof, status, codes, proof_labels = judged[0]
        labels.update(proof_labels)
        results.append({'basis': basis['basis'], 'status': status, 'codes': codes, 'proof': proof.pk})
    worst = max(results, key=lambda r: BEST_FIRST.index(r['status']))
    winner = ConsentProof.objects.filter(pk=worst['proof']).first() if worst['proof'] else None
    ebr_ids = {p.pk for p in proofs if p.kind in EBR}
    winners = [r['proof'] for r in results if r['proof']]
    if not winners or not all(w in ebr_ids for w in winners):
        labels.discard('EBR_ONLY')  # the label only when an existing-customer relationship is all that covers the contact
    return {**base, 'status': worst['status'], 'primary_code': worst['codes'][0] if worst['codes'] else '', 'codes': worst['codes'],
            'bases': results, 'proof': winner, 'labels': sorted(labels)}


def check_contact(contact, rules: RuleSet | None = None, as_of=None, reason: str = 'new_contact') -> list[ConsentResult]:
    """Checks (or checks again) one contact; a frozen result is never touched; every change goes in the history."""
    from .keeping import inputs_of, note_change
    rules = rules or RuleSet()
    saved = []
    for need in ConsentNeed.objects.filter(contact=contact):
        before = ConsentResult.objects.filter(contact=contact, variant=need.variant).first()
        if before and before.frozen:
            saved.append(before)
            continue
        found = evaluate(contact, need, rules, as_of)
        result, _ = ConsentResult.objects.update_or_create(contact=contact, variant=need.variant, defaults={
            **found, 'client_id': contact.client_id, 'inputs': inputs_of(contact), 'reeval_reason': '' if before is None else reason})
        if before:  # the history holds changes only; the first result is the row itself
            note_change(result, before.status, before.primary_code, reason)
        saved.append(result)
    return saved
