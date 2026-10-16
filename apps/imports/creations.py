"""Hand-off receiver: notes when, by whom (user ID) and how each CRM person or lead was created."""
import json
from datetime import UTC, datetime

from django.db import IntegrityError, transaction

from .models import CrmCreation


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


def creation_seen(client, connection, record, phone_tokens) -> None:
    if record.content_kind not in ('lead', 'crm_record') or record.source_record_id.startswith('calls:'):
        return
    created_at, created_by, how = creation_facts(connection.provider, record.raw)
    if created_at is None:
        return
    existing = CrmCreation.objects.filter(client=client, source_system=connection.provider, record_id=record.source_record_id).first()
    if existing:  # creation time and creator never change; numbers may
        if set(existing.phone_tokens) != set(phone_tokens):
            existing.phone_tokens = sorted(set(existing.phone_tokens) | set(phone_tokens))
            existing.save(update_fields=['phone_tokens'])
        return
    try:
        with transaction.atomic():
            CrmCreation.objects.create(client=client, source_system=connection.provider, record_id=record.source_record_id,
                                       created_at=created_at, created_by=created_by, how=how, phone_tokens=sorted(set(phone_tokens)))
    except IntegrityError:
        pass
