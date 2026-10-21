"""Module 13 step 2: sorting the law watcher's items without AI (owner decision 2026-10-22). Fixed word rules say which
Rulebook rules an item probably touches; High = a final rule touching a rule that changes results (affects_status),
Medium = a proposed rule, or a final rule on what CiV only measures, Low = the rest; the stage follows the dates; a
final rule is linked to the earlier proposed item with the same FCC case (docket) number. Hints only."""
import re
from datetime import date

from apps.rulebook.models import RuleValue

# words → rules (and metrics, shown as M-codes)
TOPICS = [
    (['revoc', 'revoke', 'opt-out', 'opt out', 'stop request', 'stop'], ['optout_deadline_business_days', 'optout_scope_rules', 'optout_keywords']),
    (['calling hours', 'time of day', 'calling times', 'quiet hours', '8 a.m', '9 p.m'], ['calling_hours', 'quiet_hours_apply_to_sms']),
    (['frequency', 'how often', 'calls per', 'number of calls'], ['frequency_limits']),
    (['written consent', 'one-to-one', 'prior express written', 'express consent', 'consent'], ['written_consent_types', 'consent_checklist']),
    (['autodial', 'automatic telephone dialing', 'prerecorded', 'artificial voice', 'ai-generated', 'artificial intelligence'], ['autodialed_modes']),
    (['text message', 'texting', 'sms', 'robotext'], ['sms_treated_as_autodialed', 'quiet_hours_apply_to_sms']),
    (['caller id', 'stir/shaken', 'call authentication', 'spoof'], ['M21']),
    (['reassigned'], ['M11']),
    (['do-not-call', 'do not call', 'registry'], ['dnc_check_max_age_days']),
]
LEVELS = {'High': 0, 'Medium': 1, 'Low': 2}


def rules_touched(text: str) -> list[str]:
    low = text.lower()
    out = []
    for words, keys in TOPICS:
        if any(re.search(r'\b' + re.escape(w), low) for w in words):
            out += [k for k in keys if k not in out]
    return out


def judging_rules() -> set[str]:
    return set(RuleValue.objects.filter(affects_status=True).values_list('key', flat=True).distinct())


def stage_of(kind: str, effective_on: date | None, today: date) -> str:
    if kind != 'Rule':
        return 'proposed'
    return 'in_force' if effective_on and effective_on <= today else 'final'


def level_of(kind: str, keys: list[str], judging: set[str]) -> str:
    rulebook_keys = [k for k in keys if not k.startswith('M')]
    if kind == 'Rule' and any(k in judging for k in rulebook_keys):
        return 'High'
    if kind == 'Proposed Rule' or (kind == 'Rule' and keys):
        return 'Medium'
    return 'Low'


def sort_item(item, judging: set[str], today: date) -> None:
    """Fills the hints on one item (and links it to the earlier proposed item of the same case)."""
    from .models import LawItem
    item.rule_keys = rules_touched(f'{item.title} {item.summary}')
    item.level = level_of(item.kind, item.rule_keys, judging)
    item.stage = stage_of(item.kind, item.effective_on, today)
    if item.kind == 'Rule' and item.dockets and item.follows_id is None:
        earlier = (LawItem.objects.filter(source=item.source, kind='Proposed Rule', published_on__lte=item.published_on)
                   .exclude(pk=item.pk).order_by('-published_on'))
        item.follows = next((e for e in earlier if set(e.dockets) & set(item.dockets)), None)


def resort(today: date | None = None) -> int:
    """Every item again (stages move with the dates; new final rules find their proposals)."""
    from .models import LawItem
    today, judging, n = today or date.today(), judging_rules(), 0
    for item in LawItem.objects.order_by('published_on'):
        sort_item(item, judging, today)
        item.save(update_fields=['rule_keys', 'level', 'stage', 'follows'])
        n += 1
    return n
