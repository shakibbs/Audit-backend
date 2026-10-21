"""What proof a call or text needs (spec §5, "before the checks"), using the rules in force on the contact's date.

- Every campaign is marketing (no campaign map: same for every client, strictest) and labelled category_unknown.
- Robocall: a dial mode in autodialed_modes, unknown dial mode (labelled), prerecorded or AI voice, or a marketing text
  when sms_treated_as_autodialed.
- Bases: robocall_marketing · dnc_listed (a STOP still in force: see opt_out_in_force) · dnc_unknown (no national
  do-not-call list supplied) · state_law (a state_consent_rule row matches) · civ_policy (none of the others).
- Inbound contacts and CiV's test numbers need nothing.
"""
import calendar
from datetime import timedelta

from apps.optouts.models import OptOutEvent
from apps.rulebook.business_days import BusinessCalendar, local_date
from apps.rulebook.lookup import RuleSet

from .models import ConsentNeed, ConsentProof

ANY = 'any'
EBR_ACTIVE = 'ebr_active'
LEGAL = {'robocall_marketing', 'robocall_informational', 'dnc_listed', 'state_law'}


def _value(rules, key, contact, variant, default=None):
    found = rules.get(key, on=contact.occurred_at.date(), state=contact.recipient_state or None, variant=variant).value
    return default if found is None else found


def opt_out_in_force(contact, rules, variant, newer_consent_lifts=True):
    """The latest opt-out before the contact that still applies, or None. Not in force for the one confirmation text
    inside confirmation_window_minutes, before the grace days end, or (for the STOP list) once the person gave a new
    consent after it; a later purchase or a CRM box never lifts it."""
    optout = (OptOutEvent.objects.filter(client_id=contact.client_id, phone_token=contact.phone_token, at__lt=contact.occurred_at,
                                         counts=True)  # not counted: found by an AI that had not passed its exam (Module 9)
              .exclude(lifted_at__lte=contact.occurred_at).order_by('-at').first())  # lifted: the person allowed contact again
    if optout is None:
        return None
    window = timedelta(minutes=int(_value(rules, 'confirmation_window_minutes', contact, variant, 5)))
    if contact.channel == 'text' and contact.occurred_at <= optout.at + window:
        first = (type(contact).objects.filter(client_id=contact.client_id, phone_token=contact.phone_token, channel='text',
                                              direction='outbound', occurred_at__gt=optout.at).order_by('occurred_at').first())
        if first is None or first.pk == contact.pk:
            return None  # one confirmation message is never cut off
    grace = int(_value(rules, 'optout_grace_business_days', contact, variant, 0))
    if grace:
        zone = (contact.time_zones or ['America/New_York'])[0]
        if local_date(contact.occurred_at, zone) < BusinessCalendar(rules).add(local_date(optout.at, zone), grace):
            return None
    if newer_consent_lifts and ConsentProof.objects.filter(
            client_id=contact.client_id, phone_token=contact.phone_token, kind=ConsentProof.Kind.CERTIFICATE,
            captured_at__gt=optout.at, captured_at__lt=contact.occurred_at).exists():
        return None
    return optout


def dnc_lists(contact, rules, variant) -> bool | None:
    """The client's uploaded lists on the contact date: its internal do-not-contact list (from the date added), and its
    DNC check records (a check within dnc_check_max_age_days before the contact covers that date)."""
    from apps.uploads.models import DncCheck, InternalListEntry
    day = contact.occurred_at.date()
    if InternalListEntry.objects.filter(client_id=contact.client_id, phone_token=contact.phone_token, added_on__lte=day).exists():
        return True
    age = int(_value(rules, 'dnc_check_max_age_days', contact, variant, 31))
    check = (DncCheck.objects.filter(client_id=contact.client_id, phone_token=contact.phone_token, checked_on__lte=day,
                                     checked_on__gte=day - timedelta(days=age)).order_by('-checked_on', '-listed').first())
    return None if check is None else check.listed


def is_robocall(contact, rules, variant) -> tuple[bool, list[str]]:
    labels = []
    if contact.prerecorded_or_ai:
        return True, labels
    if contact.channel == 'text':
        return bool(_value(rules, 'sms_treated_as_autodialed', contact, variant, True)), labels
    modes = _value(rules, 'autodialed_modes', contact, variant, 'every_mode_except_manual')
    if not contact.dial_mode:
        labels.append('dial_mode_unknown')
        return modes != 'none', labels  # unknown counts as autodialed, except where no mode does (lenient)
    if modes == 'every_mode_except_manual':
        return contact.dial_mode.lower() != 'manual', labels
    return contact.dial_mode in (modes if isinstance(modes, list) else []), labels


def _state_rows(contact, rules, variant) -> list[dict]:
    rows = _value(rules, 'state_consent_rule', contact, variant) or []
    return [r for r in rows if isinstance(r, dict) and contact.channel in r.get('channels', [contact.channel])]


def profile(contact, rules: RuleSet, variant: str) -> dict:
    if contact.direction != 'outbound' or contact.is_test:
        return {'category': 'informational', 'robocall': False, 'bases': [], 'labels': ['no_consent_needed'], 'is_legal_basis': False}
    robocall, labels = is_robocall(contact, rules, variant)
    labels.insert(0, 'category_unknown')
    bases = []
    if robocall:
        written = _value(rules, 'written_consent_required_by_forum', contact, variant, True)
        needs = _value(rules, 'written_consent_types', contact, variant) if written else _value(rules, 'prior_express_evidence_types', contact, variant)
        bases.append({'basis': 'robocall_marketing', 'needs': list(needs or [])})
    listed = dnc_lists(contact, rules, variant)  # True: on a list · False: a check covers the date, not listed · None: no list covers it
    if opt_out_in_force(contact, rules, variant) or listed:
        bases.append({'basis': 'dnc_listed', 'needs': [*(_value(rules, 'signed_written_consent_types', contact, variant) or []), EBR_ACTIVE]})
    elif listed is None:
        bases.append({'basis': 'dnc_unknown', 'needs': [ANY]})
        labels.append('dnc_list_not_supplied')
    for row in _state_rows(contact, rules, variant):
        bases.append({'basis': 'state_law', 'needs': list(row.get('consent_type_required', [ANY]))})
    if not any(b['basis'] in LEGAL or b['basis'] == 'dnc_unknown' for b in bases):
        bases.append({'basis': 'civ_policy', 'needs': [ANY]})
    return {'category': 'marketing', 'robocall': robocall, 'bases': bases, 'labels': labels,
            'is_legal_basis': any(b['basis'] in LEGAL for b in bases)}


def add_months(moment, months: int):
    month = moment.month - 1 + months
    year, month = moment.year + month // 12, month % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1]))


def ebr_active(proof: ConsentProof, contact, rules, variant) -> bool:
    """An existing-customer relationship still in its window on the contact's date."""
    months = {ConsentProof.Kind.EBR_PURCHASE: 'ebr_purchase_months', ConsentProof.Kind.EBR_INQUIRY: 'ebr_inquiry_months'}.get(proof.kind)
    since = proof.when()
    if not months or since is None:
        return False
    return since <= contact.occurred_at < add_months(since, int(_value(rules, months, contact, variant, 0)))


def ebr_covers_contact(contact, robocall: bool, rules, variant) -> bool:
    allowed = _value(rules, 'ebr_allowed_contact_types', contact, variant, [])
    return 'live_manual_call' in allowed and contact.channel == 'call' and not robocall


def meets(proof: ConsentProof, basis: dict, contact, robocall: bool, rules, variant) -> bool:
    """Whether this kind of proof can satisfy this basis for this contact (dates and checks come in the five checks)."""
    if proof.kind == ConsentProof.Kind.SELF_ASSERTED:
        return False  # a CRM box alone is never enough
    if proof.proof_type == 'client_unchecked':
        return True  # not read yet: weak whatever the need, until a CiV staff member checks it
    if proof.kind in (ConsentProof.Kind.EBR_PURCHASE, ConsentProof.Kind.EBR_INQUIRY):
        if basis['basis'] == 'robocall_marketing' or not ebr_covers_contact(contact, robocall, rules, variant):
            return False
        return ebr_active(proof, contact, rules, variant) and (ANY in basis['needs'] or EBR_ACTIVE in basis['needs'])
    if proof.kind in (ConsentProof.Kind.INBOUND_CALL, ConsentProof.Kind.INBOUND_SMS, ConsentProof.Kind.FORM_SUBMISSION):
        return evidence_meets(proof, basis, contact, robocall)
    return ANY in basis['needs'] or proof.proof_type in basis['needs']


def evidence_meets(proof: ConsentProof, basis: dict, contact, robocall: bool) -> bool:
    """Module 8 evidence is prior express consent at most: never written consent, so never a robocall or marketing text
    that needs it (those bases list only written types). An incoming call covers live calls for 30 days (draft, counsel B12);
    a YES text covers texts; the client's own form covers what any accepted proof covers."""
    from apps.provenance.evidence import INBOUND_DAYS
    if ANY not in basis['needs'] and proof.proof_type not in basis['needs']:
        return False
    since = proof.when()
    if proof.kind == ConsentProof.Kind.INBOUND_CALL:
        return (contact.channel == 'call' and not robocall and since is not None
                and since <= contact.occurred_at < since + timedelta(days=INBOUND_DAYS))
    if proof.kind == ConsentProof.Kind.INBOUND_SMS:
        return contact.channel == 'text'
    from .sources import CLIENT_FORM, source_of
    return source_of(proof) == CLIENT_FORM  # a "Web" lead inside an uploaded list is not the client's form


def work_out(contact, rules: RuleSet | None = None) -> list[ConsentNeed]:
    rules = rules or RuleSet()
    saved = []
    for variant in ConsentNeed.Variant.values:
        found = profile(contact, rules, variant)
        need, _ = ConsentNeed.objects.update_or_create(contact=contact, variant=variant,
                                                       defaults={**found, 'client_id': contact.client_id, 'rulebook_version': rules.version.version})
        saved.append(need)
    return saved


def work_out_new(limit: int = 2000) -> int:
    """New contacts: what proof each needs, then its result."""
    from apps.contacts.models import ContactEvent
    rules = RuleSet()
    from .checks import check_contact
    contacts = ContactEvent.objects.filter(consent_needs__isnull=True, is_primary=True).select_related('client', 'epoch').order_by('occurred_at')[:limit]
    count = 0
    for contact in contacts:
        work_out(contact, rules)
        check_contact(contact, rules)  # the five checks right away: every call's result within minutes
        count += 1
    return count
