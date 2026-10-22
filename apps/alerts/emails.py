"""Alert emails (owner decision 2026-10-23): when an alert first appears, or comes back after being resolved, the
company's active Admins get one email, if the company chose email for that type (Settings → Notifications). Same
words as the portal, numbers masked; the alert itself stays in the portal."""
from django.conf import settings
from django.utils import timezone

# The portal's notification types (Settings → Notifications), the alert kinds each covers, and the default choice.
TYPES = {
    'after-optout': ('Contacts after opt-out', ('Contacts after opt-out', 'Opted-out numbers re-added'), True),
    'page-change': ('Consent page changed', ('Consent page changed',), True),
    'cert-expiry': ('Certificates nearing expiry', ('Certificate expiry',), True),
    'test-deadline': ('Opt-out past its deadline', ('Opt-out not marked',), True),
    'source-stale': ('Source stale', ('Source stale', 'Incomplete data', 'Records changed at the source'), True),
    'vendor-drop': ('Vendor score drop', ('Vendor score drop',), False),
    'rule-change': ('Rule change that affects your settings', (), True),
}
KIND_TO_TYPE = {kind: key for key, (_, kinds, _) in TYPES.items() for kind in kinds}


def choices(client) -> list[dict]:
    from .models import EmailChoice
    saved = dict(EmailChoice.objects.filter(client=client).values_list('kind', 'email'))
    return [{'kind': key, 'label': label, 'email': saved.get(key, default)} for key, (label, _, default) in TYPES.items()]


def wanted(client, alert_kind: str) -> bool:
    key = KIND_TO_TYPE.get(alert_kind)
    return bool(key) and next(c['email'] for c in choices(client) if c['kind'] == key)


def send(alert) -> int:
    """Emails the company's active Admins about one alert; returns how many were emailed."""
    from apps.accounts.mailer import send as mail
    from apps.accounts.models import ClientUser, Role
    if not wanted(alert.client, alert.kind):
        return 0
    admins = list(ClientUser.objects.filter(client=alert.client, role=Role.ADMIN, is_active=True).values_list('email', flat=True))
    if admins:
        mail(admins, f'[{alert.severity}] {alert.title}', name=f'{alert.client.name} team', heading=alert.title,
             lines=[alert.detail, f'Severity: {alert.severity}. It is also in your CiV portal under Alerts.'],
             button='Open Alerts', link=f'{settings.PORTAL_URL}/alerts',
             note='You get this because an Admin chose email for this alert type in Settings → Notifications.')
    alert.emailed_at = timezone.now()
    alert.save(update_fields=['emailed_at'])
    return len(admins)
