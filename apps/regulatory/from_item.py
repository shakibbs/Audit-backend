"""Module 13 step 4: "Create a law change from this item". One click makes a law change (Regulatory changes) filled from
the item — title, date, source, plain-words summary, the rules and metrics it touches — marked "To check" like a
hand-made one (owner decision 2026-10-22). A final rule also gets a rule update draft for each value the AI drafted
(with its sentence); a proposed rule gets none until it becomes final. Clients' lawyers review the drafts in the portal;
CiV approves them, and approving ends the old value the day before the new one starts (rulebook/apply.py)."""
from datetime import date

from django.db import transaction

from apps.access_log.recorder import record

from .models import LawItem, RegChange, RuleUpdate


def status_of(item: LawItem, today: date) -> str:
    if item.kind != 'Rule':
        return RegChange.Status.PROPOSED
    return RegChange.Status.IN_FORCE if item.effective_on and item.effective_on <= today else RegChange.Status.ADOPTED


@transaction.atomic
def make_change(item: LawItem, user, today: date | None = None) -> RegChange:
    if item.reg_change_id:
        return item.reg_change  # made already
    today = today or date.today()
    keys = [k for k in item.rule_keys if not k.startswith('M')]
    change = RegChange.objects.create(
        title=item.title[:200], jurisdiction='Federal · FCC', status=status_of(item, today), announced_on=item.published_on,
        effective_from=item.effective_on,
        effective_text=f'From {item.effective_on:%-d %B %Y}' if item.effective_on else ('Not law yet (proposed)' if item.kind != 'Rule' else 'Date to confirm'),
        summary=item.ai_summary or item.summary or item.title, rule_keys=keys, metrics=[k for k in item.rule_keys if k.startswith('M')],
        source=f'Federal Register {item.ref}'[:200], source_url=item.url, suggested_by='CiV law watcher')
    if item.kind == 'Rule':
        for d in item.ai_drafts:
            if not d.get('known') or not d.get('quote'):
                continue  # only rules CiV has, and only values with their sentence
            start = date.fromisoformat(d['effective_from']) if d.get('effective_from') else item.effective_on
            if start is None:
                continue  # no start date: CiV staff add it by hand on the law change
            RuleUpdate.objects.create(reg_change=change, key=d['key'], jurisdiction='US', value=d.get('value'), shown=str(d.get('shown') or d.get('value'))[:300],
                                      status=RuleUpdate.RuleStatus.PROPOSED, effective_from=start, proposed_by=f'AI draft ({item.ai_model}), added by {user.email}')
    item.reg_change, item.state = change, LawItem.State.USED
    item.save(update_fields=['reg_change', 'state'])
    record('law_change_from_item', actor_kind='staff', actor_id=user.pk, actor_label=user.email, object=f'{item.ref} → {change.title}'[:254])
    return change
