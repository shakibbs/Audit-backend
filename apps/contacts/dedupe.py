"""One real call or text recorded by several tools is counted once.

Two contacts are the same when: same person (phone code), same channel, same direction (or one unknown), from
different tools, and within dedupe_window_seconds (Rulebook: 120, never below clock_skew_seconds) of each other.
A group never holds two records from the same tool: one tool does not record one call twice. Nothing is deleted:
copies stay, linked by dedupe_group; the main record (counted) is the best source, then the earliest.
"""
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import ContactEvent

DEFAULT_WINDOW_SECONDS = 120
# Lower = better source for "what happened": the tool that made the contact beats a CRM where someone logged it.
SOURCE_RANK = {'convoso': 1, 'five9': 1, 'vicidial': 1, 'twilio': 1, 'hubspot': 2, 'salesforce': 2}


def window() -> timedelta:
    from apps.rulebook.lookup import NoRulebook, RuleSet
    try:
        rules = RuleSet()
        today = timezone.localdate()
        seconds = max(rules.get('dedupe_window_seconds', on=today).value or 0, rules.get('clock_skew_seconds', on=today).value or 0)
    except NoRulebook:
        seconds = 0
    return timedelta(seconds=seconds or DEFAULT_WINDOW_SECONDS)


def members(contact: ContactEvent) -> list[ContactEvent]:
    if contact.dedupe_group is None:
        return [contact]
    return list(ContactEvent.objects.filter(client_id=contact.client_id, dedupe_group=contact.dedupe_group))


def choose_primary(group: list[ContactEvent]) -> None:
    best = min(group, key=lambda c: (SOURCE_RANK.get(c.source_system, 3), c.occurred_at, c.pk))
    for c in group:
        c.is_primary = c.pk == best.pk
    ContactEvent.objects.bulk_update(group, ['dedupe_group', 'is_primary'])


def leave_group(contact: ContactEvent) -> None:
    """Before re-grouping (a changed time or direction): the rest of the old group stays together."""
    if contact.dedupe_group is None:
        return
    rest = [c for c in members(contact) if c.pk != contact.pk]
    if len(rest) == 1:
        rest[0].dedupe_group = None
    if rest:
        choose_primary(rest)
    contact.dedupe_group, contact.is_primary = None, True


def group(contact: ContactEvent) -> None:
    """Joins the contact to the nearest matching record from another tool (or its group), if any."""
    with transaction.atomic():
        contact = ContactEvent.objects.select_for_update().get(pk=contact.pk)
        leave_group(contact)
        span = window()
        near = (ContactEvent.objects.select_for_update()
                .filter(client_id=contact.client_id, phone_token=contact.phone_token, channel=contact.channel,
                        occurred_at__gte=contact.occurred_at - span, occurred_at__lte=contact.occurred_at + span)
                .exclude(pk=contact.pk).exclude(source_system=contact.source_system))
        if contact.direction != 'unknown':
            near = near.filter(direction__in=[contact.direction, 'unknown'])
        best = None
        for candidate in sorted(near, key=lambda c: abs((c.occurred_at - contact.occurred_at).total_seconds())):
            if contact.source_system not in {m.source_system for m in members(candidate)}:
                best = candidate
                break
        if best is None:
            contact.save(update_fields=['dedupe_group', 'is_primary'])
            return
        together = members(best) + [contact]
        key = best.dedupe_group or uuid.uuid4()
        for c in together:
            c.dedupe_group = key
        choose_primary(together)
