"""Who You Contact → "Each list at a glance" (owner 2026-11-16): one plain answer per list for the chosen month. Each
answer is a few database counts (no per-contact lookups), so it stays quick for clients with 10,000+ contacts a day.

A list with no file uploaded is "Can't tell" (CiV cannot see the check), never "Not checked"; a file that shows the list
was not checked (DNC records with national rows only, for State DNC) is "Not checked"."""
from datetime import timedelta

from django.db.models import DateField, Exists, ExpressionWrapper, OuterRef, Q
from django.db.models.functions import TruncDate

from apps.uploads.models import DncCheck, InternalListEntry, RndQuery, Source, UploadedFile

MAX_AGE = 31  # dnc_check_max_age_days: a check counts for the 31 days after it
NATIONAL = Q(list_name__iexact='national') | Q(list_name='')


def _share(covered: int, total: int) -> int:
    return round(100 * covered / total) if total else 0


def _tone(covered: int, total: int) -> str:
    return 'ok' if _share(covered, total) >= 99 else 'warn' if covered else 'bad'


def _verdict(tone: str) -> str:
    return {'ok': 'Checked', 'warn': 'Partly checked', 'bad': 'Not checked'}[tone]


def _upload(label: str, source: str) -> dict:
    return {'label': label, 'source': source}


def _checked_before(contacts, rows):
    """Contacts with a matching row on the contact's day or in the 31 days before it."""
    match = rows.filter(phone_token=OuterRef('phone_token'), checked_on__lte=OuterRef('day'), checked_on__gte=OuterRef('since'))
    return contacts.filter(Exists(match)).count()


def glance(client, contacts, words: str) -> dict:
    contacts = contacts.annotate(day=TruncDate('occurred_at'), since=ExpressionWrapper(TruncDate('occurred_at') - timedelta(days=MAX_AGE), output_field=DateField()))
    total = contacts.count()
    dnc = DncCheck.objects.filter(client=client)
    lists = []

    # National DNC
    if not dnc.exists():
        lists.append({'col': 'national', 'tone': 'gray', 'verdict': "Can't tell", 'text': 'Your DNC check records are not uploaded, so CiV cannot see this check.',
                      'upload': _upload('Upload DNC check records', Source.DNC_CHECKS)})
    elif not total:
        lists.append({'col': 'national', 'tone': 'gray', 'verdict': 'No contacts', 'text': f'No contacts {words} to check.'})
    else:
        covered = _checked_before(contacts, dnc.filter(NATIONAL))
        tone = _tone(covered, total)
        lists.append({'col': 'national', 'tone': tone, 'verdict': _verdict(tone),
                      'text': f'{covered:,} of {total:,} contacts ({_share(covered, total)}%) were checked by your DNC check file in the {MAX_AGE} days before the contact.',
                      'count': {'n': total - covered, 'label': 'not checked'} if total > covered else None})

    # State DNC
    states = dnc.exclude(NATIONAL)
    if not dnc.exists():
        lists.append({'col': 'state', 'tone': 'gray', 'verdict': "Can't tell", 'text': 'Your DNC check records are not uploaded, so CiV cannot see this check.',
                      'upload': _upload('Upload DNC check records', Source.DNC_CHECKS)})
    elif not states.exists():
        lists.append({'col': 'state', 'tone': 'bad', 'verdict': 'Not checked', 'text': 'Your DNC check file has national results only. No state list was checked.',
                      'upload': _upload('Upload state check records', Source.DNC_CHECKS)})
    elif not total:
        lists.append({'col': 'state', 'tone': 'gray', 'verdict': 'No contacts', 'text': f'No contacts {words} to check.'})
    else:
        covered = _checked_before(contacts, states)
        tone = _tone(covered, total)
        lists.append({'col': 'state', 'tone': tone, 'verdict': _verdict(tone),
                      'text': f'{covered:,} of {total:,} contacts ({_share(covered, total)}%) were checked against a state list in the {MAX_AGE} days before the contact.',
                      'count': {'n': total - covered, 'label': 'not checked'} if total > covered else None})

    # Internal DNC: every contact is compared with the client's own list; a number on it before the contact was called anyway.
    entries = InternalListEntry.objects.filter(client=client)
    last = UploadedFile.objects.filter(client=client, source=Source.INTERNAL_LIST).first()
    if not entries.exists() or last is None:
        lists.append({'col': 'internal', 'tone': 'gray', 'verdict': "Can't tell", 'text': 'Your internal do-not-contact list is not uploaded, so CiV cannot compare your contacts with it.',
                      'upload': _upload('Upload your internal list', Source.INTERNAL_LIST)})
    elif not total:
        lists.append({'col': 'internal', 'tone': 'gray', 'verdict': 'No contacts', 'text': f'No contacts {words} to check.'})
    else:
        size = entries.values('phone_token').distinct().count()
        on_list = entries.filter(phone_token=OuterRef('phone_token'), added_on__lte=OuterRef('day'))
        called = contacts.filter(Exists(on_list)).values('phone_token').distinct().count()
        where = f'Every contact was compared with your list ({size:,} numbers, uploaded {last.received_at:%-d %b}).'
        lists.append({'col': 'internal', 'tone': 'bad' if called else 'ok', 'verdict': f'Checked, {called:,} called anyway' if called else 'Checked, none called',
                      'text': f'{where} {called:,} number{"s" if called != 1 else ""} on it {"were" if called != 1 else "was"} still contacted.' if called else f'{where} No number on it was contacted.',
                      'count': {'n': called, 'label': 'called anyway'} if called else None})

    # Reassigned numbers: a "not reassigned" answer in the 31 days before the contact.
    queries = RndQuery.objects.filter(client=client)
    if not queries.exists():
        lists.append({'col': 'reassigned', 'tone': 'gray', 'verdict': "Can't tell", 'text': 'Your reassigned-number query logs are not uploaded, so CiV cannot see these checks.',
                      'upload': _upload('Upload query logs', Source.RND_QUERIES)})
    elif not total:
        lists.append({'col': 'reassigned', 'tone': 'gray', 'verdict': 'No contacts', 'text': f'No contacts {words} to check.'})
    else:
        asked = queries.filter(result=RndQuery.Result.NO, phone_token=OuterRef('phone_token'), queried_on__lte=OuterRef('day'), queried_on__gte=OuterRef('since'))
        covered = contacts.filter(Exists(asked)).count()
        tone = _tone(covered, total)
        lists.append({'col': 'reassigned', 'tone': tone, 'verdict': _verdict(tone),
                      'text': f'{covered:,} of {total:,} contacts ({_share(covered, total)}%) had a reassigned-number check answering "not reassigned" in the {MAX_AGE} days before.',
                      'count': {'n': total - covered, 'label': 'not checked'} if total > covered else None})

    names = {'national': 'National DNC', 'state': 'State DNC', 'internal': 'Internal DNC', 'reassigned': 'Reassigned'}
    return {'contacts': total, 'words': words, 'lists': [{'list': names[x['col']], 'count': None, 'upload': None, **x} for x in lists]}
