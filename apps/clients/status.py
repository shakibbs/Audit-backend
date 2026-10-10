"""Moving a client between stages (Trial → Onboarding → Active → Paused → Ended) and keeping the history."""
from django.utils import timezone
from django.utils.html import format_html

from apps.access_log.recorder import record
from apps.clients.models import Client, StatusChange

PILL = {'trial': 'blue', 'onboarding': 'amber', 'active': 'green', 'paused': 'gray', 'ended': 'red'}


def status_pill(client: Client) -> str:
    return format_html('<span class="civ"><span class="pill pill-{}">{}</span></span>', PILL[client.status], client.get_status_display())


def prepare(client: Client, old_status: str) -> bool:
    """Before saving: keep is_active in step with the stage. Returns True if the stage changed."""
    client.is_active = client.status != Client.Status.ENDED
    if client.status == old_status:
        return False
    client.status_changed_at = timezone.now()
    return True


def record_change(request, client: Client, old_status: str, reason: str = '') -> StatusChange:
    """After saving: write the history row and the access log entry."""
    change = StatusChange.objects.create(client=client, old_status=old_status, new_status=client.status,
                                         reason=reason, changed_by=request.user)
    labels = dict(Client.Status.choices)
    text = f'{labels.get(old_status, "New")} → {labels[client.status]}' + (f' ({reason})' if reason else '')
    record('client_status_changed', request=request, actor_kind='staff', actor_id=request.user.pk,
           actor_label=request.user.email, client_id=client.pk, object=text)
    return change
