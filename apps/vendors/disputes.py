"""Module 12 step 4: dispute candidates (Lead Inspector spec) — leads the client may return to the vendor under its
contract: a consent problem (NO_PROOF or CONFLICTING on its contacts; high-risk signals later with the Lead Inspector),
still inside the vendor's dispute window (the contract's days, the last day included; no contract → the Rulebook's
default_dispute_window_days, 0 → none, "no contract on file"). Leads with no price are counted, flagged and left out of
the total. M30 Disputable lead value is the total. CiV never contacts vendors."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.consent.models import ConsentResult
from apps.consent.words import REASONS
from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent

from .contracts import latest, state
from .rates import all_leads, setting, vendor_key


def window_days(client, key: str, today) -> tuple[int, str]:
    contract = latest(client, key)
    if contract and state(contract, today) == 'on_file' and contract.dispute_days is not None:
        return contract.dispute_days, 'contract'
    return int(setting('default_dispute_window_days', today) or 0), 'no contract on file'


def candidates(client, now=None) -> dict[str, dict]:
    """{vendor key: {name, windowDays, basis, rows, total, noPrice}}."""
    now = now or timezone.now()
    today = now.date()
    out = {}
    longest = 400
    leads = all_leads(client, now - timedelta(days=longest), now)
    tokens = {t for lead in leads for t in lead['phone_tokens']}
    sent = defaultdict(list)
    for c in ContactEvent.objects.filter(client=client, phone_token__in=tokens, direction='outbound', is_primary=True, is_test=False) \
            .values('pk', 'phone_token', 'occurred_at', 'masked_label'):
        sent[c['phone_token']].append(c)
    bad = defaultdict(list)
    for r in ConsentResult.objects.filter(client=client, variant='strict', frozen=False, contact__phone_token__in=tokens,
                                          status__in=['no_proof', 'conflicting']).values('contact_id', 'status', 'primary_code'):
        bad[r['contact_id']].append(r)
    for lead in leads:
        key = vendor_key(lead['vendor'])
        if key not in out:
            days, basis = window_days(client, key, today)
            out[key] = {'name': ' '.join(lead['vendor'].split()), 'windowDays': days, 'basis': basis, 'rows': [], 'total': Decimal(0), 'noPrice': 0}
        v = out[key]
        if lead['created_at'].date() + timedelta(days=v['windowDays']) < today or v['windowDays'] == 0:
            continue  # the window closed (or there is none)
        calls = [c for t in lead['phone_tokens'] for c in sent[t] if c['occurred_at'] >= lead['created_at']]
        found = [(c, r) for c in calls for r in bad[c['pk']]]
        if not found:
            continue
        contact, result = found[0]
        v['rows'].append({'lead': lead['ref'], 'vendor': v['name'], 'subId': lead['sub_id'] or None, 'date': lead['created_at'].date().isoformat(),
                          'price': str(lead['price']) if lead['price'] is not None else None,
                          'result': 'No proof' if result['status'] == 'no_proof' else 'Conflicting',
                          'reasons': REASONS.get(result['primary_code'] or '', result['primary_code'] or ''),
                          'number': contact['masked_label'] or 'Number hidden', 'ref': number_ref(contact['phone_token'])})
        if lead['price'] is None:
            v['noPrice'] += 1
        else:
            v['total'] += lead['price']
    return out


def disputable_value(client, now=None) -> dict:
    """M30: the price of every dispute candidate still inside its window."""
    found = candidates(client, now)
    rows = sum(len(v['rows']) for v in found.values())
    if not found:
        return {'code': 'M30', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No vendor leads'}
    total = sum(v['total'] for v in found.values())
    no_price = sum(v['noPrice'] for v in found.values())
    closed = sum(1 for v in found.values() if v['windowDays'] == 0)
    note = f'{rows:,} lead{"" if rows == 1 else "s"} inside the dispute window' + (f' · {no_price:,} with no price, left out' if no_price else '') \
        + (f' · {closed:,} vendor{"" if closed == 1 else "s"} with no contract on file' if closed else '')
    return {'code': 'M30', 'value': float(total), 'display': f'${total:,.2f}', 'note': note, 'notMeasured': None}
