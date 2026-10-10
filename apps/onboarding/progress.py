"""Where a client stands in onboarding: each step done or not, who ticked it and when."""
from apps.clients.models import Client
from apps.documents.models import ClientDocument
from apps.onboarding.models import OnboardingTick
from apps.onboarding.steps import STEPS


def checklist(client: Client) -> dict:
    ticks = {t.step: t for t in OnboardingTick.objects.filter(client=client).select_related('done_by')}
    uploaded = set(ClientDocument.objects.filter(client=client).values_list('kind', flat=True))
    rows = []
    for step in STEPS:
        tick = ticks.get(step.code)
        by_document = bool(step.document_kind) and step.document_kind in uploaded
        done = step.auto(client) if step.auto else (tick is not None or by_document)
        rows.append({
            'code': step.code, 'label': step.label, 'hint': step.hint, 'auto': step.auto is not None, 'done': done,
            'by_document': by_document and tick is None,
            'done_at': tick.done_at if tick else None, 'done_by': tick.done_by.name if tick and tick.done_by else '',
        })
    done = sum(r['done'] for r in rows)
    return {'steps': rows, 'done': done, 'total': len(rows), 'percent': round(100 * done / len(rows)), 'complete': done == len(rows)}
