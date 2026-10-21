"""Hand-off receiver: notes when, by whom (user ID) and how each CRM person or lead was created."""
import hashlib
import json
from datetime import UTC, datetime

from django.db import IntegrityError, transaction

from .models import CrmCreation, CrmUpdate


def _when(value) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.isdigit():  # HubSpot can send milliseconds
        return datetime.fromtimestamp(int(text) / 1000, UTC)
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', None):
        try:
            return datetime.strptime(text, fmt) if fmt else datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            continue
    return None


def creation_facts(provider: str, raw: bytes) -> tuple[datetime | None, str, str]:
    try:
        row = json.loads(raw)
    except ValueError:
        return None, '', ''
    if provider == 'salesforce':
        return _when(row.get('CreatedDate')), str(row.get('CreatedById') or ''), ''
    if provider == 'hubspot':
        p = row.get('properties', {})
        return _when(p.get('createdate') or row.get('createdAt')), str(p.get('hs_created_by_user_id') or ''), str(p.get('hs_object_source') or '').upper()
    return None, '', ''


# Fields that name who supplied a lead (any CRM, custom fields included), and source words that are categories, not vendors.
VENDOR_FIELD = ('vendor', 'provider', 'publisher', 'affiliate', 'supplier', 'lead_source', 'leadsource', 'utm_source', 'source_name')
NOT_A_VENDOR = {'', 'web', 'website', 'web form', 'webform', 'form', 'forms', 'organic', 'organic search', 'organic_search', 'direct',
                'direct traffic', 'direct_traffic', 'offline', 'other', 'other campaigns', 'other_campaigns', 'referral', 'referrals',
                'email', 'email marketing', 'email_marketing', 'social', 'social media', 'social_media', 'organic social', 'paid search',
                'paid_search', 'paid social', 'paid_social', 'phone', 'phone inquiry', 'inbound', 'inbound call', 'walk-in', 'walk in',
                'trade show', 'word of mouth', 'partner', 'purchased list', 'list', 'import', 'crm', 'crm_ui', 'none', 'null', 'unknown', 'n/a',
                'na', '-', 'internal', 'manual', 'api', 'integration'}


OPT_FIELD = ('donotcall', 'do_not_call', 'dnc', 'opt_out', 'optout', 'opted_out', 'unsubscribe')


def _yes(value) -> bool:
    return value is True or str(value).strip().lower() in ('true', 'yes', '1', 'y')


def watched(provider: str, raw: bytes) -> tuple[str, bool | None, str]:
    """(fingerprint of the opt-out / do-not-call / lead-source fields, opted out now, who last changed the record).
    Only the fingerprint and a yes/no are kept, never the values."""
    try:
        row = json.loads(raw)
    except ValueError:
        return '', None, ''
    fields = row.get('properties', {}) if provider == 'hubspot' else row
    picked, opted = {}, None
    for name, value in sorted(fields.items()):
        low = name.lower().replace('-', '_')
        if any(w in low.replace('_', '') for w in ('donotcall', 'dnc')) or any(w in low for w in OPT_FIELD):
            if 'email' in low:
                continue  # email opt-outs are not about calls or texts
            picked[name] = value
            opted = bool(opted) or _yes(value)
        elif any(w in low for w in VENDOR_FIELD):
            picked[name] = value
    by = str(row.get('LastModifiedById') or fields.get('hs_updated_by_user_id') or '')
    digest = hashlib.sha256(json.dumps(picked, sort_keys=True, default=str).encode()).hexdigest() if picked else ''
    return digest, opted, by


def vendor_of(provider: str, raw: bytes) -> str:
    """The supplier the record names, lightly cleaned (owner decision: case and spaces only); '' when none."""
    try:
        row = json.loads(raw)
    except ValueError:
        return ''
    fields = row.get('properties', {}) if provider == 'hubspot' else row
    for name, value in fields.items():
        if not isinstance(value, str) or not any(word in name.lower() for word in VENDOR_FIELD) or is_sub(name):
            continue
        text = ' '.join(value.split())[:120]
        if text.lower() not in NOT_A_VENDOR and not text.lower().startswith('http'):
            return text
    return ''


SUB_FIELD = ('sub_id', 'subid', 'sub_source', 'subsource', 'aff_sub', 'affiliate_sub', 'sub_affiliate', 'subaffiliate', 'publisher_sub')


def is_sub(name: str) -> bool:
    low = name.lower().replace('-', '_')
    return any(w in low or w.replace('_', '') in low.replace('_', '') for w in SUB_FIELD)


def sub_of(provider: str, raw: bytes) -> str:
    """The vendor's sub-source (sub-ID) the record names, '' when none (Module 12: vendors are scored per sub-ID too)."""
    try:
        row = json.loads(raw)
    except ValueError:
        return ''
    fields = row.get('properties', {}) if provider == 'hubspot' else row
    for name, value in fields.items():
        if is_sub(name) and isinstance(value, (str, int)) and str(value).strip():
            return ' '.join(str(value).split())[:60]
    return ''


PRICE_FIELD = ('lead_price', 'leadprice', 'lead_cost', 'leadcost', 'cost_per_lead', 'cpl', 'price', 'cost', 'payout')


def price_of(provider: str, raw: bytes):
    """What the lead cost, when the CRM record has a price field; None otherwise."""
    from decimal import Decimal, InvalidOperation
    try:
        row = json.loads(raw)
    except ValueError:
        return None
    fields = row.get('properties', {}) if provider == 'hubspot' else row
    for want in PRICE_FIELD:
        for name, value in fields.items():
            if name.lower().replace('-', '_').replace(' ', '_') in (want, f'{want}__c') and value not in (None, ''):
                try:
                    found = Decimal(str(value).replace('$', '').replace(',', '').strip())
                except InvalidOperation:
                    continue
                if 0 <= found < 100000:
                    return found
    return None


def creation_seen(client, connection, record, phone_tokens) -> None:
    if record.content_kind not in ('lead', 'crm_record') or record.source_record_id.startswith('calls:'):
        return
    created_at, created_by, how = creation_facts(connection.provider, record.raw)
    if created_at is None:
        return
    vendor, sub = vendor_of(connection.provider, record.raw), sub_of(connection.provider, record.raw)
    price = price_of(connection.provider, record.raw)
    sha, opted, by = watched(connection.provider, record.raw)
    existing = CrmCreation.objects.filter(client=client, source_system=connection.provider, record_id=record.source_record_id).first()
    if existing:  # creation time and creator never change; numbers and a vendor filled in later may
        changed = []
        if sha and existing.watched_sha and sha != existing.watched_sha:  # the opt-out or lead-source fields changed
            CrmUpdate.objects.create(client=client, source_system=connection.provider, record_id=record.source_record_id,
                                     updated_at=record.changed_at, updated_by=by, cleared_optout=bool(existing.opted_out) and opted is False,
                                     phone_tokens=sorted(set(existing.phone_tokens) | set(phone_tokens)))
        if sha and sha != existing.watched_sha:
            existing.watched_sha, existing.opted_out = sha, opted
            changed += ['watched_sha', 'opted_out']
        if set(existing.phone_tokens) != set(phone_tokens):
            existing.phone_tokens = sorted(set(existing.phone_tokens) | set(phone_tokens))
            changed.append('phone_tokens')
        if vendor and not existing.vendor:
            existing.vendor = vendor
            changed.append('vendor')
        if sub and not existing.sub_id:
            existing.sub_id = sub
            changed.append('sub_id')
        if price is not None and existing.price is None:
            existing.price = price
            changed.append('price')
        if changed:
            existing.save(update_fields=changed)
        return
    try:
        with transaction.atomic():
            CrmCreation.objects.create(client=client, source_system=connection.provider, record_id=record.source_record_id,
                                       created_at=created_at, created_by=created_by, how=how, phone_tokens=sorted(set(phone_tokens)),
                                       vendor=vendor, sub_id=sub, price=price, watched_sha=sha, opted_out=opted)
    except IntegrityError:
        pass
