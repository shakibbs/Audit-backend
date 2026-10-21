"""Up to five example numbers for a finding: masked label and number-page reference, never the number."""
from apps.consent.models import ConsentResult
from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent
from apps.conversations.models import ConversationReview
from apps.metrics.conduct import Rules, contacts, outside
from apps.optouts.models import OptOutEvent, ReaddedNumber
from apps.uploads.models import InternalListEntry

LIMIT = 5


def shown(rows) -> tuple[list[dict], int]:
    """(examples, distinct numbers) from contacts, newest first."""
    seen, out = set(), []
    for c in rows:
        if c.phone_token not in seen:
            seen.add(c.phone_token)
            if len(out) < LIMIT:
                out.append({'label': c.masked_label or 'Number hidden', 'ref': number_ref(c.phone_token)})
    return out, len(seen)


def flagged(client, code: str, start, end) -> tuple[list[dict], int | None]:
    sent = contacts(client, start, end).order_by('-occurred_at')
    if code in ('M10', 'M01', 'M19'):
        codes = {'M10': ['NP_AFTER_OPT_OUT']}.get(code)
        results = ConsentResult.objects.filter(client=client, variant='strict', frozen=False, contact__in=sent)
        results = results.filter(codes__contains=codes) if codes else results.filter(is_legal_basis=True, status__in=['no_proof', 'conflicting'])
        return shown(sent.filter(pk__in=results.values('contact_id')))
    if code == 'M12':
        return shown(c for c in sent if InternalListEntry.objects.filter(client=client, phone_token=c.phone_token, added_on__lte=c.occurred_at.date()).exists())
    if code == 'M48':
        told = OptOutEvent.objects.filter(client=client, counts=True, method='ai', keyword='wrong number')
        return shown(c for e in told for c in sent.filter(phone_token=e.phone_token, occurred_at__gt=e.at))
    if code == 'M45':
        named = ConversationReview.objects.filter(client=client, trusted=True, attorney_at__isnull=False)
        return shown(c for r in named for c in sent.filter(phone_token=r.phone_token, occurred_at__gt=r.attorney_at))
    if code == 'M15':
        return shown(sent.filter(is_non_us=True))
    if code == 'M16':
        rules = Rules(start.date())
        return shown(c for c in sent.exclude(is_non_us=True)[:5000]
                     if rules.get('calling_hours', c.recipient_state) and c.time_zones and outside(c, rules.get('calling_hours', c.recipient_state)))
    if code == 'M34':
        tokens = list(ReaddedNumber.objects.filter(client=client, record_created_at__gte=start, record_created_at__lt=end)
                      .values_list('phone_token', flat=True).distinct())
        latest = [ContactEvent.objects.filter(client=client, phone_token=t).order_by('-occurred_at').first() for t in tokens]
        examples, _ = shown(c for c in latest if c)
        return examples, len(tokens)
    return [], None
