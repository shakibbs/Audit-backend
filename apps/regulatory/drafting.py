"""Module 13 step 3: the AI slot for law drafts (owner decisions 2026-10-21 / 2026-10-22: the AI is chosen later; until
then the slot is off — nothing is sent anywhere, nothing costs anything). A drafter gets one item —
{title, kind, summary, text (the full document for High items, else ''), rules: [{key, meaning, shown}]} — and returns
{summary: plain words, rule_keys: [...], drafts: [{key, value, shown, effective_from, quote}], confidence 0–1}. The
quote is the document's own sentence each value came from, so CiV staff can check it. Drafts never touch the Rulebook:
they only prefill the law change CiV staff create (step 4)."""
import urllib.request
from datetime import date

from django.utils import timezone

from apps.rulebook.lookup import NoRulebook, RuleSet

from .models import LawItem

PROMPT_VERSION = 'law-v1'
MAX_TEXT = 200_000  # characters of a full document read into memory
_drafter = None  # set by tests, or by the chosen AI's adapter


def use(drafter) -> None:
    global _drafter
    _drafter = drafter


def active():
    """The drafter in use, or None while no AI is chosen."""
    return _drafter


def full_text(item: LawItem) -> str:
    if not item.text_url:
        return ''
    request = urllib.request.Request(item.text_url, headers={'User-Agent': 'CiV law watcher (Comply iV)'})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return reply.read(MAX_TEXT * 2).decode('utf-8', 'ignore')[:MAX_TEXT]


def rules_for(item: LawItem) -> list[dict]:
    try:
        rules = RuleSet('internal')
    except NoRulebook:
        return []
    out = []
    for key in item.rule_keys:
        if key.startswith('M'):
            continue
        try:
            rule = rules.get(key, on=date.today())
        except LookupError:
            continue
        out.append({'key': key, 'shown': rule.shown, 'status': rule.status})
    return out


def draft_one(item: LawItem, drafter) -> LawItem:
    read_full = item.level == 'High'  # owner decision 2026-10-22: the full document for High items, the summary otherwise
    text = ''
    if read_full:
        try:
            text = full_text(item)
        except Exception:
            read_full = False  # the full text did not come: the summary only
    answer = drafter({'title': item.title, 'kind': item.kind, 'summary': item.summary, 'text': text, 'rules': rules_for(item)})
    del text  # read in memory only
    known = set(item.rule_keys) | {r['key'] for r in rules_for(item)}
    drafts = [d for d in answer.get('drafts') or [] if isinstance(d, dict) and d.get('key') and d.get('quote')]
    item.ai_summary = str(answer.get('summary') or '')[:4000]
    item.ai_drafts = [{**d, 'known': d['key'] in known} for d in drafts][:10]  # a draft without a quote is never kept
    item.ai_confidence = answer.get('confidence')
    item.ai_model = getattr(drafter, 'model', 'unknown')[:60]
    item.ai_read = 'full_text' if read_full else 'summary'
    item.ai_done_at = timezone.now()
    item.save(update_fields=['ai_summary', 'ai_drafts', 'ai_confidence', 'ai_model', 'ai_read', 'ai_done_at'])
    return item


def draft_new(limit: int = 20) -> int:
    drafter = active()
    if drafter is None:
        return 0  # no AI chosen yet: nothing is sent anywhere
    done = 0
    for item in LawItem.objects.filter(state=LawItem.State.NEW, ai_done_at__isnull=True)[:limit]:
        try:
            draft_one(item, drafter)
            done += 1
        except Exception:
            continue  # tried again tomorrow
    return done
