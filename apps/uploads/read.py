"""Reads an uploaded file into its table. CSV columns are matched loosely (case, spaces and underscores ignored); a row
with no usable phone or date is not read and is counted. Numbers become phone codes in memory and are never kept.
Policies and contracts may be documents (PDF, Word): they are kept and fingerprinted, with no rows to read."""
import csv
import hashlib
import io
import re
from datetime import date, datetime

from django.db import transaction

from apps.contacts.normalize import codes_for

from .models import Complaint, DncCheck, InternalListEntry, RndQuery, Source, TrainingRecord, UploadedFile

PHONE = ('phone', 'phonenumber', 'number', 'telephone', 'mobile', 'cell', 'ani', 'dnis', 'tn', 'msisdn')
DATE_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d', '%d-%b-%Y', '%b %d %Y', '%Y%m%d')
YES = {'y', 'yes', 'true', '1', 'listed', 'on list', 'onlist', 'dnc', 'match', 'matched', 'found', 'blocked', 'do not call'}
NO = {'n', 'no', 'false', '0', 'not listed', 'clean', 'clear', 'ok', 'not found', 'nomatch', 'no match', 'callable', 'allowed'}


def _key(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def pick(row: dict, names: tuple[str, ...]) -> str:
    """The first non-empty value whose column name is one of `names`, or contains one of them."""
    keys = {_key(k): (v or '').strip() for k, v in row.items() if k}
    for name in names:
        if keys.get(name):
            return keys[name]
    for name in names:
        for key, value in keys.items():
            if name in key and value:
                return value
    return ''


def to_date(text: str) -> date | None:
    text = (text or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.split(' ')[0] if fmt.count(' ') == 0 else text, fmt).date()
        except ValueError:
            continue
    return None


def yes_no(text: str) -> bool | None:
    value = (text or '').strip().lower()
    return True if value in YES else False if value in NO else None


def rows_of(content: bytes) -> list[dict]:
    text = content.decode('utf-8-sig', errors='replace')
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.DictReader(io.StringIO(text), dialect=dialect) if any((v or '').strip() for v in r.values() if isinstance(v, str))]


def read(upload: UploadedFile, content: bytes) -> tuple[int, int]:
    """Reads the file's rows into the table for its source. Returns (rows read, rows not read)."""
    if upload.source == Source.POLICIES and not upload.original_name.lower().endswith('.csv'):
        return 0, 0  # a policy or contract document: kept and fingerprinted only
    codes, client, today = codes_for(upload.client), upload.client, upload.received_at.date()
    made, rejected = [], 0
    for row in rows_of(content):
        token = codes.token(pick(row, PHONE)) if pick(row, PHONE) else None
        if upload.source == Source.INTERNAL_LIST:
            ok = token is not None
            if ok:
                made.append(InternalListEntry(client=client, upload=upload, phone_token=token,
                                              added_on=to_date(pick(row, ('added', 'addedon', 'date', 'created', 'since', 'optout'))) or today))
        elif upload.source == Source.DNC_CHECKS:
            checked = to_date(pick(row, ('checked', 'checkedon', 'scrubbed', 'scrubdate', 'date', 'run', 'queried')))
            listed = yes_no(pick(row, ('listed', 'onlist', 'dnc', 'result', 'status', 'match', 'registry')))
            ok = bool(token and checked and listed is not None)
            if ok:
                made.append(DncCheck(client=client, upload=upload, phone_token=token, checked_on=checked, listed=listed,
                                     list_name=pick(row, ('list', 'listname', 'registryname', 'state', 'source'))[:40] or 'national'))
        elif upload.source == Source.RND_QUERIES:
            queried = to_date(pick(row, ('queried', 'queriedon', 'querydate', 'date', 'checked')))
            answer = pick(row, ('result', 'response', 'reassigned', 'answer', 'status')).strip().lower()
            result = 'no_data' if 'no data' in answer or answer in ('nodata', 'unknown', 'n/a') else 'yes' if yes_no(answer) else 'no' if yes_no(answer) is False else ''
            ok = bool(token and queried and result)
            if ok:
                made.append(RndQuery(client=client, upload=upload, phone_token=token, queried_on=queried, result=result))
        elif upload.source == Source.COMPLAINTS:
            received = to_date(pick(row, ('received', 'receivedon', 'date', 'opened', 'created', 'filed')))
            ok = received is not None
            if ok:
                made.append(Complaint(client=client, upload=upload, phone_token=token or '', received_on=received,
                                      resolved_on=to_date(pick(row, ('resolved', 'resolvedon', 'closed', 'closedon'))),
                                      channel=pick(row, ('channel', 'source', 'via', 'type'))[:30]))
        else:  # training log
            agent = pick(row, ('agentid', 'agent', 'employeeid', 'employee', 'user', 'userid', 'id'))
            trained = to_date(pick(row, ('trained', 'trainedon', 'completed', 'completion', 'date')))
            ok = bool(agent and trained)
            if ok:
                made.append(TrainingRecord(client=client, upload=upload, agent_ref=hashlib.sha256(agent.lower().encode()).hexdigest(), trained_on=trained))
        rejected += not ok
    with transaction.atomic():
        if made:
            type(made[0]).objects.bulk_create(made, batch_size=1000)
    return len(made), rejected
