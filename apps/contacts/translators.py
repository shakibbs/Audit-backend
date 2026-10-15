"""Turns each tool's record into the one contact shape. Returns None for records that are not calls or texts
(CRM leads and contacts: they serve consent and lead source later). Raw numbers are returned in memory only, to be
turned into phone codes by the caller; they are never stored.

Field names follow each vendor's docs (see apps/sync/connectors); to confirm on real accounts."""
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from apps.sync.connector import Record


def _out_in(value: str) -> str:
    text = (value or '').lower()
    return 'inbound' if text.startswith('in') else 'outbound' if text.startswith('out') or 'manual' in text else 'unknown'


def _int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _hms(value: str) -> int | None:
    """'00:01:05' → 65."""
    try:
        h, m, s = (int(x) for x in str(value).split(':'))
        return h * 3600 + m * 60 + s
    except ValueError:
        return _int(value)


def _rfc(value) -> datetime | None:
    return parsedate_to_datetime(value).astimezone(UTC) if value else None


def twilio(record: Record, row: dict) -> dict | None:
    direction = _out_in(row.get('direction', ''))
    person = row.get('from') if direction == 'inbound' else row.get('to')
    shown = row.get('to') if direction == 'inbound' else row.get('from')
    if record.content_kind == 'text':
        return {'channel': 'text', 'direction': direction, 'person': person, 'caller_id': shown, 'occurred_at': record.changed_at,
                'sms_status': row.get('status', ''), 'disposition': row.get('status', '')}
    length = _int(row.get('duration'))
    return {'channel': 'call', 'direction': direction, 'person': person, 'caller_id': shown, 'occurred_at': record.changed_at,
            'ended_at': _rfc(row.get('end_time')), 'length_seconds': length, 'disposition': row.get('status', ''),
            'answered': row.get('status') == 'completed' and (length or 0) > 0 if row.get('status') else None}


def convoso(record: Record, row: dict) -> dict | None:
    length = _int(row.get('call_length'))
    return {'channel': 'call', 'direction': _out_in(row.get('call_type', 'outbound')), 'person': row.get('phone_number') or row.get('number_dialed'),
            'caller_id': row.get('caller_id_displayed'), 'occurred_at': record.changed_at, 'length_seconds': length,
            'answered': (length or 0) > 0 if length is not None else None, 'disposition': row.get('status', ''),
            'campaign': row.get('campaign') or row.get('campaign_id') or '', 'agent_id': str(row.get('user_id') or row.get('user') or ''),
            'lead_id': str(row.get('lead_id') or '')}


def _col(row: dict, *names: str) -> str:
    wanted = [n.replace(' ', '').upper() for n in names]
    return next((v.strip() for k, v in row.items() if k and k.replace(' ', '').upper() in wanted and v), '')


def five9(record: Record, row: dict) -> dict | None:
    direction = _out_in(_col(row, 'CALL TYPE') or 'outbound')
    length = _hms(_col(row, 'LENGTH', 'CALL TIME', 'TALK TIME'))
    return {'channel': 'call', 'direction': direction, 'person': _col(row, 'ANI') if direction == 'inbound' else _col(row, 'DNIS'),
            'caller_id': _col(row, 'DNIS') if direction == 'inbound' else _col(row, 'ANI'), 'occurred_at': record.changed_at,
            'length_seconds': length, 'answered': (length or 0) > 0 if length is not None else None,
            'disposition': _col(row, 'DISPOSITION'), 'campaign': _col(row, 'CAMPAIGN'), 'agent_id': _col(row, 'AGENT', 'AGENT NAME')}


def vicidial(record: Record, row: dict) -> dict | None:
    length = _int(row.get('length_in_sec'))
    end = _int(row.get('end_epoch'))
    return {'channel': 'call', 'direction': 'inbound' if record.source_record_id.startswith('inbound:') else 'outbound',
            'person': f"{row.get('phone_code') or ''}{row.get('phone_number') or ''}", 'occurred_at': record.changed_at,
            'ended_at': datetime.fromtimestamp(end, UTC) if end else None, 'length_seconds': length,
            'answered': (length or 0) > 0 if length is not None else None, 'disposition': row.get('status') or '',
            'campaign': row.get('campaign_id') or '', 'agent_id': row.get('user') or '', 'lead_id': str(row.get('lead_id') or '')}


def hubspot(record: Record, row: dict) -> dict | None:
    if not record.source_record_id.startswith('calls:'):
        return None  # CRM contacts are not contacts made
    p = row.get('properties', {})
    direction = _out_in(p.get('hs_call_direction', ''))
    ms = _int(p.get('hs_call_duration'))
    return {'channel': 'call', 'direction': direction,
            'person': p.get('hs_call_from_number') if direction == 'inbound' else p.get('hs_call_to_number'),
            'caller_id': p.get('hs_call_to_number') if direction == 'inbound' else p.get('hs_call_from_number'),
            'occurred_at': record.changed_at, 'length_seconds': ms // 1000 if ms is not None else None,
            'disposition': p.get('hs_call_disposition') or p.get('hs_call_status') or ''}


def salesforce(record: Record, row: dict) -> dict | None:
    return None  # Salesforce call Tasks carry no phone number; the same calls come from the dialer (Module 4 step 3)


TRANSLATORS = {'twilio': twilio, 'convoso': convoso, 'five9': five9, 'vicidial': vicidial, 'hubspot': hubspot, 'salesforce': salesforce}


def translate(provider: str, record: Record) -> dict | None:
    """The contact fields for this record, or None when it is not a call or text (or not readable)."""
    if record.content_kind not in ('call', 'text', 'crm_record'):
        return None
    translator = TRANSLATORS.get(provider)
    if translator is None:
        return None
    try:
        row = json.loads(record.raw)
    except ValueError:
        return None
    fields = translator(record, row)
    return fields if fields and fields.get('person') else None
