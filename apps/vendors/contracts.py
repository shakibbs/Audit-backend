"""Module 12 step 3: vendor contracts and M07 Vendor terms on file. Until the AI reader exists (owner decision
2026-10-21) and counsel confirms the clauses (vendor_required_clauses, a CiV draft since 2026-10-22), M07 counts
active vendors with an unexpired contract on file, labelled "clauses not checked yet"."""
from datetime import timedelta

from django.utils import timezone

from .models import VendorContract
from .rates import setting, vendor_key

KEEP = timedelta(days=4 * 365)
ALLOWED = {'.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.txt'}
MAX_BYTES = 20 * 1024 * 1024


def latest(client, key: str) -> VendorContract | None:
    return VendorContract.objects.filter(client=client, key=key).first()


def state(contract: VendorContract | None, today) -> str:
    if contract is None:
        return 'none'
    return 'expired' if contract.ends_on and contract.ends_on < today else 'on_file'


def active_vendors(client, now=None) -> dict[str, str]:
    """{key: name} of vendors with a lead in the last vendor_active_days (90)."""
    now = now or timezone.now()
    days = int(setting('vendor_active_days', now.date()) or 90)
    from .rates import all_leads
    out = {}
    for lead in all_leads(client, now - timedelta(days=days), now):
        out.setdefault(vendor_key(lead['vendor']), ' '.join(lead['vendor'].split()))
    return out


def terms_on_file(client, now=None) -> dict:
    """M07: active vendors with an unexpired contract on file ÷ active vendors (clauses checked later)."""
    now = now or timezone.now()
    vendors = active_vendors(client, now)
    if not vendors:
        return {'code': 'M07', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No vendor named in your CRM records'}
    if not VendorContract.objects.filter(client=client).exists():
        return {'code': 'M07', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'Contracts not supplied'}
    ok = sum(state(latest(client, k), now.date()) == 'on_file' for k in vendors)
    share = round(100 * ok / len(vendors), 1)
    note = f'{ok} of {len(vendors)} active vendors have an unexpired contract on file'
    read = [latest(client, k) for k in vendors if state(latest(client, k), now.date()) == 'on_file' and latest(client, k).clauses]
    if read:  # Module 16: the AI reader checked the clauses
        from apps.rulebook.lookup import RuleSet
        required = [c['id'] for c in RuleSet().get('vendor_required_clauses', on=now.date()).value if c.get('required')]
        full = sum(all(c.clauses.get(r) for r in required) for c in read)
        note += f' · {full} of {len(read)} checked have every required clause'
    else:
        note += ' · clauses not checked yet (needs the AI reader)'
    return {'code': 'M07', 'value': share, 'display': f'{share}%', 'notMeasured': None, 'note': note}


def purge_old(now=None) -> int:
    now = now or timezone.now()
    n = 0
    from apps.evidence.holds import Holds
    holds = Holds()
    for c in VendorContract.objects.filter(uploaded_at__lt=now - KEEP, purged_at__isnull=True).exclude(file=''):
        if holds.covers(c.client_id, c.uploaded_at, vendors=[c.key]):
            continue  # under a legal hold (Module 14)
        c.file.delete(save=False)
        c.purged_at = now
        c.save(update_fields=['file', 'purged_at'])
        n += 1
    return n
