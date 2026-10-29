"""Email to CiV staff when a client asks for a quote for the litigation evidence package (2026-10-30)."""
from django.conf import settings
from django.urls import reverse

from apps.accounts.mailer import send


def quote_requested(q) -> int:
    """Emails every active CiV staff member who can see quote requests; returns how many were emailed."""
    from apps.staff.models import StaffUser
    to = [s.email for s in StaffUser.objects.filter(is_active=True) if s.has_perm('reports.view_quoterequest')]
    if to:
        send(to, f'Quote request: {q.name} for {q.client.name}', name='CiV team', heading='A client asked for a quote',
             lines=[f'{q.client.name} asked for a quote for the {q.name}.',
                    f'Asked by {q.asked_by} ({q.asked_by_email or "no email"}) on {q.asked_at:%d %b %Y at %H:%M} UTC.',
                    'Please contact them, then mark the request done in the staff panel.'],
             button='Open the request', link=f"{settings.ADMIN_URL}{reverse('admin:reports_quoterequest_change', args=[q.pk])}")
    return len(to)


def package_made(q) -> int:
    """Tells CiV staff a litigation package is waiting to be checked."""
    from apps.staff.models import StaffUser
    to = [s.email for s in StaffUser.objects.filter(is_active=True) if s.has_perm('reports.change_quoterequest')]
    if to:
        send(to, f'Check the litigation package for {q.client.name}', name='CiV team', heading='A package is ready to check',
             lines=[f'{q.client.name} sent the numbers and CiV made the {q.name}: {q.package_files} number(s) found, {q.package_missing} not found.',
                    'Download it, check it, fill in the custodian name and title, then press Release.'],
             button='Open the request', link=f"{settings.ADMIN_URL}{reverse('admin:reports_quoterequest_change', args=[q.pk])}")
    return len(to)


def to_client(q, heading: str, line: str) -> int:
    """Tells the person who asked (accepted: send the numbers; released: download it)."""
    if not q.asked_by_email:
        return 0
    send(q.asked_by_email, f'{heading}: {q.name}', name=q.asked_by, heading=heading,
         lines=[line, 'It is in your CiV portal under Reports & Exports.'], button='Open Reports & Exports', link=f'{settings.PORTAL_URL}/reports')
    return 1
