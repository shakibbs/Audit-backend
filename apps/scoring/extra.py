"""Module 10 step 3: metrics CiV already measures on other pages, counted for one month so they can be saved and
scored: M12 internal list, M34 opted-out numbers re-added, M11 reassigned checks, and the Module 9 checks M41, M42,
M45, M48. A source the client never supplied gives the worst case (spec §7); a check CiV cannot run yet gives
"not measured"."""
from datetime import timedelta
from statistics import median

from apps.conversations.models import ConversationReview
from apps.optouts.models import OptOutEvent, ReaddedNumber
from apps.uploads.models import InternalListEntry, RndQuery


def metric(code, value, display, note='', not_measured=None, worst=False):
    return {'code': code, 'value': value, 'display': display, 'note': note, 'notMeasured': not_measured,
            **({'worstCase': True} if worst else {})}


def not_measured(code, why):
    return metric(code, None, 'Not measured', not_measured=why)


def internal_list(client, contacts) -> dict:
    if not InternalListEntry.objects.filter(client=client).exists():
        return metric('M12', None, 'Worst case', 'worst case — internal list not supplied', worst=True)
    n = sum(1 for c in contacts.only('phone_token', 'occurred_at') if InternalListEntry.objects.filter(
        client=client, phone_token=c.phone_token, added_on__lte=c.occurred_at.date()).exists())
    return metric('M12', n, f'{n:,}', 'Contacts after the number joined your internal list')


def readded(client, start, end) -> dict:
    n = ReaddedNumber.objects.filter(client=client, record_created_at__gte=start, record_created_at__lt=end).count()
    return metric('M34', n, f'{n:,}', 'Opted-out numbers brought back by an uploaded list')


def reassigned_checks(client, contacts) -> dict:
    if not RndQuery.objects.filter(client=client).exists():
        return metric('M11', None, 'Worst case', 'worst case — reassigned-number query logs not supplied ("not checked")', worst=True)
    total = contacts.count()
    if not total:
        return not_measured('M11', 'No contacts in the month')
    asked = sum(1 for c in contacts.only('phone_token', 'occurred_at') if RndQuery.objects.filter(
        client=client, phone_token=c.phone_token, result='no', queried_on__lte=c.occurred_at.date(),
        queried_on__gte=c.occurred_at.date() - timedelta(days=31)).exists())
    share = round(100 * asked / total, 1)
    return metric('M11', share, f'{share}%', 'Contacts preceded by your reassigned-number check within a month')


def ai_running(client) -> bool:
    return ConversationReview.objects.filter(client=client).exclude(result='not_reviewed').exists()


def stops(client, start, end) -> list[dict]:
    asked = [e for e in OptOutEvent.objects.filter(client=client, counts=True, method__in=['keyword', 'ai'], at__gte=start, at__lt=end)
             .prefetch_related('mark_checks') if any(c.marked is not None for c in e.mark_checks.all())]
    if not asked:
        return [not_measured('M41', 'No stop request checked in your tools'), not_measured('M42', 'No stop request checked in your tools')]
    never = sum(any(c.missed for c in e.mark_checks.all()) for e in asked)
    out = [metric('M41', never, f'{never:,} of {len(asked):,}', 'Stop requests that never reached every tool by the deadline')]
    due = [e for e in asked if all(c.deadline_at and c.deadline_at <= end for c in e.mark_checks.all() if c.marked is not None)]
    if not due:
        return out + [not_measured('M42', 'No deadline passed yet')]
    late = sum(any(c.missed for c in e.mark_checks.all()) for e in due)
    share = round(100 * (len(due) - late) / len(due), 1)
    days = [(max(c.marked_at for c in e.mark_checks.all() if c.marked_at) - e.at).total_seconds() / 86400
            for e in due if any(c.marked_at for c in e.mark_checks.all())]
    return out + [metric('M42', share, f'{share}%', f'Median {median(days):.0f} days' if days else '')]


def wrong_numbers(client, contacts) -> dict:
    if not ai_running(client):
        return not_measured('M48', 'Comes with AI review of calls and texts')
    n = sum(contacts.filter(phone_token=e.phone_token, occurred_at__gt=e.at).count()
            for e in OptOutEvent.objects.filter(client=client, counts=True, method='ai', keyword='wrong number'))
    return metric('M48', n, f'{n:,}', 'Contacts after a "wrong number" reply')


def attorneys(client, contacts) -> dict:
    if not ai_running(client):
        return not_measured('M45', 'Comes with AI review of calls and texts')
    named = {}
    for r in ConversationReview.objects.filter(client=client, trusted=True, attorney_at__isnull=False).order_by('attorney_at'):
        named.setdefault(r.phone_token, r.attorney_at)
    again = sum(contacts.filter(phone_token=t, occurred_at__gt=at).exists() for t, at in named.items())
    return metric('M45', again, f'{again:,} of {len(named):,}', 'People contacted after naming an attorney')


def extra_metrics(client, start, end, contacts) -> list[dict]:
    return [internal_list(client, contacts), readded(client, start, end), reassigned_checks(client, contacts),
            *stops(client, start, end), wrong_numbers(client, contacts), attorneys(client, contacts)]
