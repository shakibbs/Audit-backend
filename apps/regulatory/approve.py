"""Approve or reject a rule update. Approving writes it into the Rulebook in force (dated, never overlapping)."""
from django.db import transaction
from django.utils import timezone

from apps.access_log.recorder import record
from apps.rulebook.apply import apply_update
from apps.rulebook.lookup import current_version
from apps.rulebook.signals import rules_changed

from .models import RuleUpdate


def approve(update: RuleUpdate, user) -> None:
    with transaction.atomic():
        update.state, update.approved_by, update.approved_at = RuleUpdate.State.APPROVED, user.email, timezone.now()
        apply_update(current_version('internal'), update.as_update())  # refuses an overlap: nothing is saved then
        update.save(update_fields=['state', 'approved_by', 'approved_at'])
    rules_changed.send(sender=RuleUpdate, from_date=update.effective_from)  # results from that date are checked again
    record('rule_update_approved', actor_kind='staff', actor_id=user.pk, actor_label=user.email, object=str(update)[:254])


def reject(update: RuleUpdate, user) -> None:
    update.state = RuleUpdate.State.REJECTED
    update.save(update_fields=['state'])
    record('rule_update_rejected', actor_kind='staff', actor_id=user.pk, actor_label=user.email, object=str(update)[:254])
