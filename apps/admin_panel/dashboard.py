"""Numbers and lists on the admin panel's home page."""
from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from apps.access_log.labels import action_label
from apps.access_log.labels import who as who_of
from apps.access_log.models import AccessEntry
from apps.accounts.models import ClientUser, Invite
from apps.billing.models import renewals_within
from apps.clients.models import Client
from apps.connections.models import Connection, Status
from apps.regulatory.models import LawItem



def stat(tag: str, value: int, foot: str, url: str, query: str = '') -> dict:
    return {'tag': tag, 'value': value, 'foot': foot, 'url': reverse(url) + query}


def locked_count(now) -> int:
    from apps.accounts.lockout import locked_emails
    return len(locked_emails(now=now))


def rulebook_tile() -> dict:
    """Module 13: rules that change results but still need a decision."""
    from apps.rulebook.health import check
    from apps.rulebook.lookup import NoRulebook
    try:
        data = check()
    except NoRulebook:
        return {'tag': 'Rulebook', 'value': 0, 'foot': 'No Rulebook loaded', 'url': reverse('admin:rulebook_rulevalue_changelist')}
    federal, states = sum(data['counts'].values()), sum(data['state_counts'].values())
    return {'tag': 'Rules needing a decision', 'value': len(data['pending']),
            'foot': f'Rules that change results and are not decided yet · {federal + states} rules in all ({federal} federal, {states} state or court)',
            'url': reverse('admin:rulebook_rulevalue_check')}


def dashboard(request, context: dict) -> dict:
    now = timezone.now()
    day = AccessEntry.objects.filter(at__gte=now - timedelta(hours=24))
    clients = Client.objects.filter(is_active=True)
    by_stage = dict(Client.objects.filter(deleted_at__isnull=True).values_list('status').annotate(n=Count('id')))
    users = ClientUser.objects.filter(is_active=True, client__deleted_at__isnull=True)
    invites = Invite.objects.filter(used_at__isnull=True, expires_at__gt=now, client__deleted_at__isnull=True)
    connections = Connection.objects.filter(client__deleted_at__isnull=True)
    working = connections.filter(status=Status.CONNECTED)
    broken = connections.filter(status__in=[Status.FAILED, Status.STALE]).count()
    context.update({
        'stats': [
            stat('Active clients', by_stage.get('active', 0),
                 f'{by_stage.get("onboarding", 0)} onboarding · {by_stage.get("trial", 0)} trial · {by_stage.get("paused", 0)} paused',
                 'admin:clients_client_changelist', '?status__exact=active'),
            # Each tile opens the list of exactly what it counts; deleted companies are left out (2026-10-30).
            stat('Client users', users.count(), f'Active people in {users.values("client").distinct().count()} companies',
                 'admin:clients_client_changelist', '?attention=users'),
            stat('Open invites', invites.count(), f'Waiting for a password · in {invites.values("client").distinct().count()} companies',
                 'admin:clients_client_changelist', '?attention=invites'),
            {**stat('Connections working', working.count(), f'In {working.values("client").distinct().count()} companies · '
                    f'{connections.filter(status=Status.WAITING).count()} waiting',
                    'admin:clients_client_changelist', '?attention=working'),
             'extra': {'text': f'{broken} failed or stale', 'url': reverse('admin:clients_client_changelist') + '?attention=connections'}},
            stat('Renewals · 30 days', renewals_within(30).filter(client__deleted_at__isnull=True).count(), 'Contracts ending or renewing soon',
                 'admin:clients_client_changelist', '?attention=renewals'),
            rulebook_tile(),
            stat('New law items · high priority', LawItem.objects.filter(state='new', level='High').count(),
                 f'{LawItem.objects.filter(state="new").count()} new in total (law watcher)', 'admin:regulatory_lawitem_changelist',
                 '?state__exact=new&level__exact=High'),
            stat('Sign-ins · 24 h', day.filter(action='sign_in').count(),
                 f'{day.filter(action="sign_in_failed").count()} failed · {locked_count(now)} locked now', 'admin:access_log_accessentry_changelist',
                 '?action__exact=sign_in&within=24h'),
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
