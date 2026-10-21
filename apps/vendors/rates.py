"""Module 12 step 1: each vendor's leads over vs_window_days (90) and its problem rates (Lead Inspector spec, vendor
scorecard). A lead is a CRM record that names a vendor (Module 8), even if never called; vendors are counted per
sub-ID too when the CRM names one (owner decision 2026-10-22). Rates CiV can measure now:
- consent problems: called leads whose contacts are NO_PROOF or CONFLICTING (strict reading) ÷ called leads;
- consent gaps: called leads whose consent failed a required checklist item (NP_NO_CONSENT_TEXT, NP_PRETICKED,
  WK_WORDING) ÷ called leads;
- late delivery: leads that reached the CRM more than vs_max_delivery_hours (24) after the consent time ÷ leads with
  a known consent time;
- stops and complaints: a stop or complaint within vs_stop_window_days (30) of the first contact ÷ called leads whose
  30 days have finished.
High-risk signals and name match need the Lead Inspector signals: "not measured yet" (owner decision 2026-10-22).
A rate with nothing to count is left out."""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from apps.consent.models import ConsentProof, ConsentResult
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation
from apps.optouts.models import OptOutEvent
from apps.rulebook.lookup import NoRulebook, RuleSet
from apps.uploads.models import Complaint

RATES = [('high_signals', 'High-risk signals'), ('consent_problems', 'Consent problems'), ('consent_gaps', 'Consent gaps'),
         ('name_match', 'Name mismatch'), ('late_delivery', 'Late delivery'), ('stops', 'Stops and complaints')]
NOT_YET = {'high_signals', 'name_match'}  # need the Lead Inspector signals
GAP_CODES = {'NP_NO_CONSENT_TEXT', 'NP_PRETICKED', 'WK_WORDING'}
DRAFT = {'vs_window_days': 90, 'vs_max_delivery_hours': 24, 'vs_stop_window_days': 30, 'vs_min_leads_for_score': 100}


def setting(key: str, on):
    try:
        return RuleSet().get(key, on=on).value
    except (NoRulebook, KeyError, LookupError):
        return DRAFT.get(key)


def vendor_key(name: str) -> str:
    return ' '.join(name.lower().split())


def all_leads(client, start, end) -> list[dict]:
    """Vendor leads from the CRM and from uploaded vendor lead files, in one shape."""
    from .models import VendorLead
    crm = [{**r, 'ref': f'{r.pop("source_system")}:{r.pop("record_id")}'} for r in CrmCreation.objects.filter(
        client=client, created_at__gte=start, created_at__lte=end).exclude(vendor='')
        .values('vendor', 'sub_id', 'created_at', 'phone_tokens', 'price', 'source_system', 'record_id')]
    uploaded = [{'vendor': v.vendor, 'sub_id': v.sub_id, 'created_at': v.received_at, 'phone_tokens': [v.phone_token], 'price': v.price,
                 'ref': v.lead_ref or f'upload {v.upload_id} row {v.row}'}
                for v in VendorLead.objects.filter(client=client, received_at__gte=start, received_at__lte=end)]
    return crm + uploaded


def vendor_rates(client, now=None) -> list[dict]:
    """One row per vendor (sub_id None) and per vendor sub-ID, most leads first."""
    now = now or timezone.now()
    on = now.date()
    days, late_hours, stop_days = (int(setting(k, on)) for k in ('vs_window_days', 'vs_max_delivery_hours', 'vs_stop_window_days'))
    leads = all_leads(client, now - timedelta(days=days), now)
    tokens = {t for lead in leads for t in lead['phone_tokens']}
    sent = defaultdict(list)
    for c in ContactEvent.objects.filter(client=client, phone_token__in=tokens, direction='outbound', is_primary=True, is_test=False) \
            .values('pk', 'phone_token', 'occurred_at'):
        sent[c['phone_token']].append(c)
    results = defaultdict(list)
    for r in ConsentResult.objects.filter(client=client, variant='strict', frozen=False, contact__phone_token__in=tokens) \
            .exclude(status__in=['pending', 'not_needed']).values('contact_id', 'status', 'codes'):
        results[r['contact_id']].append(r)
    consent_at = defaultdict(list)
    for p in ConsentProof.objects.filter(client=client, phone_token__in=tokens, captured_at__isnull=False, date_known=True) \
            .values('phone_token', 'captured_at'):
        consent_at[p['phone_token']].append(p['captured_at'])
    stops = defaultdict(list)
    for o in OptOutEvent.objects.filter(client=client, phone_token__in=tokens, counts=True).values('phone_token', 'at'):
        stops[o['phone_token']].append(o['at'])
    for c in Complaint.objects.filter(client=client, phone_token__in=tokens).values('phone_token', 'received_on'):
        stops[c['phone_token']].append(timezone.make_aware(timezone.datetime.combine(c['received_on'], timezone.datetime.min.time())))

    groups = defaultdict(lambda: {'name': '', 'leads': 0, 'called': 0, 'problems': 0, 'gaps': 0, 'timed': 0, 'late': 0, 'finished': 0, 'stopped': 0})
    for lead in leads:
        mine = lead['phone_tokens']
        calls = sorted((c for t in mine for c in sent[t] if c['occurred_at'] >= lead['created_at']), key=lambda c: c['occurred_at'])
        checked = [r for c in calls for r in results[c['pk']]]
        consents = [at for t in mine for at in consent_at[t] if at <= lead['created_at']]
        facts = {'called': bool(checked),
                 'problem': any(r['status'] in ('no_proof', 'conflicting') for r in checked),
                 'gap': any(GAP_CODES & set(r['codes'] or []) for r in checked),
                 'timed': bool(consents), 'late': bool(consents) and lead['created_at'] - max(consents) > timedelta(hours=late_hours)}
        first = calls[0]['occurred_at'] if calls else None
        facts['finished'] = bool(first) and first + timedelta(days=stop_days) <= now
        facts['stopped'] = facts['finished'] and any(first <= at <= first + timedelta(days=stop_days) for t in mine for at in stops[t])
        vk = vendor_key(lead['vendor'])
        for key in [(vk, None)] + ([(vk, lead['sub_id'])] if lead['sub_id'] else []):  # the vendor row, and its sub-ID row
            g = groups[key]
            g['name'] = g['name'] or ' '.join(lead['vendor'].split())
            g['leads'] += 1
            g['called'] += facts['called']
            g['problems'] += facts['problem']
            g['gaps'] += facts['gap']
            g['timed'] += facts['timed']
            g['late'] += facts['late']
            g['finished'] += facts['finished']
            g['stopped'] += facts['stopped']

    def rate(n, d):
        return round(n / d, 4) if d else None

    out = []
    for (key, sub), g in groups.items():
        rates = {'high_signals': None, 'name_match': None, 'consent_problems': rate(g['problems'], g['called']),
                 'consent_gaps': rate(g['gaps'], g['called']), 'late_delivery': rate(g['late'], g['timed']), 'stops': rate(g['stopped'], g['finished'])}
        out.append({'key': key, 'name': g['name'], 'subId': sub, 'leads': g['leads'], 'rates': rates,
                    'counts': {k: g[k] for k in ('called', 'problems', 'gaps', 'timed', 'late', 'finished', 'stopped')},
                    'measured': sum(v is not None for k, v in rates.items() if k not in NOT_YET)})
    return sorted(out, key=lambda r: (r['key'], r['subId'] is not None, -r['leads'], r['subId'] or ''))
