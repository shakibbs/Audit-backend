from celery import shared_task

from apps.clients.models import Client
from apps.tenancy.scope import tenant

from .review import review_due


@shared_task
def review_conversations() -> int:
    """Every minute: conversations that went quiet. Does nothing while no AI is chosen."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += review_due(client)
    return count


@shared_task
def run_exams() -> int:
    """Daily: the AI's exam, when the AI or its instructions changed or 30 days passed. Nothing while no AI is chosen
    (calls also wait for speech-to-text). Each run sends about 300 conversations per channel to the AI."""
    from . import ai, exam, speech
    reviewer = ai.active()
    if reviewer is None:
        return 0
    channels = ['text'] + (['call'] if speech.active() is not None else [])
    ran = [exam.run(c, reviewer) for c in channels if exam.due(c, reviewer)]
    return len(ran)
