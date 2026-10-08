"""Numbers and lists on the admin panel's home page."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.access_log.labels import action_label
from apps.access_log.models import AccessEntry
from apps.accounts.lockout import MAX_FAILURES, WINDOW
from apps.accounts.models import ClientUser, Invite
from apps.clients.models import Client
from apps.connections.models import Connection, Status



def stat(tag: str, value: int, foot: str, url: str) -> dict:
    return {'tag': tag, 'value': value, 'foot': foot, 'url': reverse(url)}


def locked_count(now) -> int:
    failures = AccessEntry.objects.filter(action='sign_in_failed', at__gte=now - WINDOW)
    emails = failures.values_list('object', flat=True).distinct()
    return sum(1 for email in emails if failures.filter(object=email).count() >= MAX_FAILURES)


def dashboard(request, context: dict) -> dict:
    now = timezone.now()
    day = AccessEntry.objects.filter(at__gte=now - timedelta(hours=24))
    clients = Client.objects.filter(is_active=True)
    context.update({
        'stats': [
            stat('Active clients', clients.count(), f'{Client.objects.count()} in total', 'admin:clients_client_changelist'),
            stat('Client users', ClientUser.objects.filter(is_active=True).count(), 'Active accounts', 'admin:accounts_clientuser_changelist'),
            stat('Open invites', Invite.objects.filter(used_at__isnull=True, expires_at__gt=now).count(), 'Waiting for a password', 'admin:accounts_invite_changelist'),
            stat('Connections', Connection.objects.filter(status=Status.CONNECTED).count(),
                 f'{Connection.objects.filter(status=Status.WAITING).count()} waiting · '
                 f'{Connection.objects.filter(status__in=[Status.FAILED, Status.STALE]).count()} failed or stale',
                 'admin:connections_connection_changelist'),
            stat('Sign-ins · 24 h', day.filter(action='sign_in').count(),
                 f'{day.filter(action="sign_in_failed").count()} failed · {locked_count(now)} locked now', 'admin:access_log_accessentry_changelist'),
        ],
        'clients': [
            {'name': c.name, 'url': reverse('admin:clients_client_change', args=[c.pk]), 'plan': c.get_plan_display(),
             'users': c.users.filter(is_active=True).count(), 'counsel': c.counsel_directed, 'start': c.start_date,
             'level': c.access_level}
            for c in clients.order_by('-created_at')[:8]
        ],
        'log': [
            # Before sign-in there is no actor, so the email tried is shown as "who".
            {'at': e.at, 'who': e.actor_label or e.object or e.get_actor_kind_display(),
             'label': action_label(e.action),
             'object': e.object if e.actor_label else ''}
            for e in AccessEntry.objects.order_by('-at')[:10]
        ],
        'clients_url': reverse('admin:clients_client_changelist'),
        'log_url': reverse('admin:access_log_accessentry_changelist'),
    })
    return context
