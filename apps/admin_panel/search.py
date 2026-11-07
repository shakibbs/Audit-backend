"""The staff panel's search box (owner, 2026-11-07): menu pages under the menu's own section names, plus client
companies, client people, insurers, insurer people and CiV staff by name or email. Each list only for staff who may
see it."""
from django.conf import settings
from django.urls import reverse
from unfold.dataclasses import SearchResult

PER_KIND = 8


def menu(term: str) -> list[SearchResult]:
    out = []
    for section in settings.UNFOLD['SIDEBAR']['navigation']:
        for item in section.get('items', []):
            if term in str(item['title']).lower():
                out.append(SearchResult(title=str(item['title']), description=section['title'], link=str(item['link']), icon=item.get('icon')))
    return out


def records(request, term: str) -> list[SearchResult]:
    from django.db.models import Q

    from apps.accounts.models import ClientUser
    from apps.buyers.models import BuyerOrg, BuyerUser
    from apps.clients.models import Client
    from apps.staff.models import StaffUser
    user, out = request.user, []
    if user.has_perm('clients.view_client'):
        for c in Client.objects.filter(name__icontains=term, deleted_at__isnull=True)[:PER_KIND]:
            out.append(SearchResult(c.name, 'Client company', reverse('admin:clients_client_change', args=[c.pk]), 'apartment'))
        for p in ClientUser.objects.filter(Q(name__icontains=term) | Q(email__icontains=term)).select_related('client')[:PER_KIND]:
            out.append(SearchResult(f'{p.name} <{p.email}>', f'Person at {p.client.name}', reverse('admin:clients_client_change', args=[p.client_id]), 'person'))
    if user.has_perm('buyers.view_buyerorg'):
        for o in BuyerOrg.objects.filter(name__icontains=term, deleted_at__isnull=True)[:PER_KIND]:
            out.append(SearchResult(o.name, 'Insurer or acquirer', reverse('admin:buyers_buyerorg_change', args=[o.pk]), 'shield'))
        for b in BuyerUser.objects.filter(Q(name__icontains=term) | Q(email__icontains=term)).select_related('org')[:PER_KIND]:
            out.append(SearchResult(f'{b.name} <{b.email}>', f'Person at {b.org.name}', reverse('admin:buyers_buyerorg_change', args=[b.org_id]), 'person'))
    if user.has_perm('staff.view_staffuser'):
        for s in StaffUser.objects.filter(Q(name__icontains=term) | Q(email__icontains=term))[:PER_KIND]:
            out.append(SearchResult(f'{s.name} <{s.email}>', 'CiV staff', reverse('admin:staff_staffuser_change', args=[s.pk]), 'badge'))
    return out


def search(request, term: str) -> list[SearchResult]:
    term = (term or '').strip().lower()
    if len(term) < 2:
        return menu(term) if term else []
    return menu(term) + records(request, term)
