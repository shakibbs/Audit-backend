"""Applies an approved rule update to a Rulebook version: the old value ends the day before, the new one starts.
There is always exactly one value per rule, place and day."""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.db.models import F

from .models import RulebookVersion, RuleValue


class OverlapRefused(Exception):
    pass


@dataclass
class Update:
    key: str
    jurisdiction: str
    value: object
    shown: str
    status: str
    effective_from: date
    changed_by: str
    approved_by: str
    source_url: str = ''
    new_meaning: str = ''  # set for a brand-new rule


def apply_update(version: RulebookVersion, update: Update) -> RuleValue:
    rows = RuleValue.objects.select_for_update().filter(version=version, key=update.key)
    with transaction.atomic():
        template = rows.filter(jurisdiction=update.jurisdiction).first() or rows.first()
        if template is None:
            if not update.new_meaning:
                raise OverlapRefused(f'{update.key} is not in Rulebook v{version.version}.')
            # A brand-new rule: owned by counsel, and it can change results until shown otherwise.
            template = RuleValue(section='Added by rule update', meaning=update.new_meaning, owner='Counsel',
                                 counsel_item='', affects_status=True, counsel_approved=False)
        place = rows.filter(jurisdiction=update.jurisdiction)
        if place.filter(effective_from__gte=update.effective_from).exists():
            raise OverlapRefused(f'{update.key} [{update.jurisdiction}] already has a value starting on or after '
                                 f'{update.effective_from}; pick a later start date.')
        place.filter(effective_to__isnull=True).update(effective_to=update.effective_from - timedelta(days=1))
        place.filter(effective_to__gte=update.effective_from).update(effective_to=update.effective_from - timedelta(days=1))
        new = RuleValue.objects.create(
            version=version, key=update.key, jurisdiction=update.jurisdiction, section=template.section,
            meaning=template.meaning, owner=template.owner, counsel_item=template.counsel_item,
            affects_status=template.affects_status, counsel_approved=template.counsel_approved,
            status=update.status, value=update.value, shown=update.shown, effective_from=update.effective_from,
            changed_by=update.changed_by, approved_by=update.approved_by, source_url=update.source_url)
        RulebookVersion.objects.filter(pk=version.pk).update(revision=F('revision') + 1)  # lookups read the rules again
        check_no_overlap(version)
    return new


def check_no_overlap(version: RulebookVersion) -> None:
    """Refuses two values for the same rule, place and day."""
    by_place: dict[tuple, list[RuleValue]] = {}
    for row in RuleValue.objects.filter(version=version):
        by_place.setdefault((row.key, row.jurisdiction), []).append(row)
    for (key, place), rows in by_place.items():
        rows.sort(key=lambda r: r.effective_from or date.min)  # no start date = from the beginning (the database puts it last)
        for before, after in zip(rows, rows[1:]):
            end = before.effective_to or date.max
            start = after.effective_from or date.min
            if end >= start:
                raise OverlapRefused(f'{key} [{place}] has two values on {start}.')
