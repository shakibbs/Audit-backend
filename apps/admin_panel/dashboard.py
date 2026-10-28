"""Numbers and lists on the admin panel's home page."""
from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from apps.access_log.labels import action_label
from apps.access_log.labels import who as who_of
from apps.access_log.models import AccessEntry
from apps.accounts.lockout import MAX_FAILURES, WINDOW
from apps.accounts.models import ClientUser, Invite
from apps.billing.models import renewals_within
from apps.clients.models import Client
from apps.connections.models import Connection, Status
from apps.regulatory.models import LawItem



def stat(tag: str, value: int, foot: str, url: str, query: str = '') -> dict:
    return {'tag': tag, 'value': value, 'foot': foot, 'url': reverse(url) + query}


def locked_count(now) -> int:
    failures = AccessEntry.objects.filter(action='sign_in_failed', at__gte=now - WINDOW)
    emails = failures.values_list('object', flat=True).distinct()
    return sum(1 for email in emails if failures.filter(object=email).count() >= MAX_FAILURES)


def rulebook_tile() -> dict:
    """Module 13: rules that change results but still need a decision."""
    from apps.rulebook.health import check
    from apps.rulebook.lookup import NoRulebook
    try:
        data = check()
    except NoRulebook:
        return {'tag': 'Rulebook', 'value': 0, 'foot': 'No Rulebook loaded', 'url': reverse('admin:rulebook_rulevalue_changelist')}
    c = data['counts']
    return {'tag': 'Rules needing a decision', 'value': len(data['pending']),
            'foot': f'Rules that change results and are not decided yet · {sum(c.values())} rules in all',
            'url': reverse('admin:rulebook_rulevalue_check')}


def dashboard(request, context: dict) -> dict:
    now = timezone.now()
    day = AccessEntry.objects.filter(at__gte=now - timedelta(hours=24))
    clients = Client.objects.filter(is_active=True)
    by_stage = dict(Client.objects.filter(deleted_at__isnull=True).values_list('status').annotate(n=Count('id')))
    context.update({
        'stats': [
            stat('Active clients', by_stage.get('active', 0),
                 f'{by_stage.get("onboarding", 0)} onboarding · {by_stage.get("trial", 0)} trial · {by_stage.get("paused", 0)} paused',
                 'admin:clients_client_changelist'),
            # Each tile opens the matching list (2026-10-23), not the plain client list.
            stat('Client users', ClientUser.objects.filter(is_active=True).count(), 'Active accounts · companies by users',
                 'admin:clients_client_changelist', '?o=-7'),
            stat('Open invites', Invite.objects.filter(used_at__isnull=True, expires_at__gt=now).count(), 'Waiting for a password',
                 'admin:clients_client_changelist', '?attention=invites'),
            stat('Connections working', Connection.objects.filter(status=Status.CONNECTED).count(),
                 f'{Connection.objects.filter(status=Status.WAITING).count()} waiting · '
                 f'{Connection.objects.filter(status__in=[Status.FAILED, Status.STALE]).count()} failed or stale',
                 'admin:clients_client_changelist', '?attention=connections'),
            stat('Renewals · 30 days', renewals_within(30).count(), 'Contracts ending or renewing soon',
                 'admin:clients_client_changelist', '?attention=renewals'),
            rulebook_tile(),
            stat('New law items · high priority', LawItem.objects.filter(state='new', level='High').count(),
                 f'{LawItem.objects.filter(state="new").count()} new in total (law watcher)', 'admin:regulatory_lawitem_changelist',
                 '?state__exact=new&level__exact=High'),
            stat('Sign-ins · 24 h', day.filter(action='sign_in').count(),
                 f'{day.filter(action="sign_in_failed").count()} failed · {locked_count(now)} locked now', 'admin:access_log_accessentry_changelist'),
        ],
        'clients': [
            {'name': c.name, 'url': reverse('admin:clients_client_change', args=[c.pk]), 'plan': c.get_plan_display(),
             'users': c.users.filter(is_active=True).count(), 'start': c.start_date,
             'level': c.access_level}
            for c in clients.order_by('-created_at')[:8]
        ],
        'log': [
            {'at': e.at, 'who': who_of(e), 'label': action_label(e.action), 'object': e.object}
            for e in AccessEntry.objects.order_by('-at')[:10]
        ],
        'clients_url': reverse('admin:clients_client_changelist'),
        'log_url': reverse('admin:access_log_accessentry_changelist'),
    })
    return context
