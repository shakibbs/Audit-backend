"""Client API: the Settings page (company facts, states contacted, contacts, agreements, usage, alert emails) and the
Revocation Integrity page. A fact CiV does not hold is sent empty and the portal says "Not set"."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientAdmin, IsClientUser
from apps.refs import yes
from apps.alerts.emails import choices
from apps.contacts.models import ContactEvent
from apps.documents.models import ClientDocument
from apps.onboarding.readiness import billed_numbers, usage

AGREEMENTS = [  # (document kind, name shown, what it covers)
    (ClientDocument.Kind.AGREEMENT, 'Service agreement', 'The audit service and its terms'),
    (ClientDocument.Kind.ANNEX_C, 'Annex C · test opt-outs', 'Permission for CiV to send test opt-outs from its own numbers'),
    (ClientDocument.Kind.DPA, 'Data processing agreement', 'How CiV handles personal data for you'),
    (ClientDocument.Kind.STATEMENT, 'Signed statement', 'What you told your insurer'),
]


def agreements(client) -> list[dict]:
    rows = []
    for kind, name, detail in AGREEMENTS:
        doc = ClientDocument.objects.filter(client=client, kind=kind).order_by('-signed_on', '-pk').first()
        signed = bool(doc and doc.signed_on)
        rows.append({'name': name, 'status': 'signed' if signed else 'pending', 'date': doc.signed_on.isoformat() if signed else None,
                     'detail': detail})
    return rows


class SettingsView(APIView):
    permission_classes = [IsClientAdmin]  # Settings is Admin only (owner, 2026-10-23)

    def get(self, request):
        client = request.user.client
        states = sorted(s for s in ContactEvent.objects.filter(client=client).exclude(recipient_state='')
                        .values_list('recipient_state', flat=True).distinct())
        brands = [b.strip() for b in client.brand_names.splitlines() if b.strip()]
        return Response({'company': {'name': client.name, 'vertical': client.industry or '—', 'states': states, 'brands': brands,
                                     'forum': None, 'engaged': client.start_date.isoformat()},
                         'contacts': contacts(client), 'agreements': agreements(client), 'usage': usage(client),
                         'notifications': choices(client)})  # alert emails to Admins (owner, 2026-10-23)


def contacts(client) -> list[dict]:
    """The company's people CiV writes to: its Admins and its lawyers (from Users & Access)."""
    from apps.accounts.models import ClientUser
    rows = ClientUser.objects.filter(client=client, is_active=True).order_by('name')
    return [{'role': ' · '.join(r for r, on in (('Admin', u.is_admin), ('Lawyer', u.is_counsel)) if on), 'name': u.name, 'email': u.email}
            for u in rows if u.is_admin or u.is_counsel]


class BilledNumbersView(APIView):
    """This month's billed numbers as a CSV: masked labels only (D31), first contact, contacts."""
    permission_classes = [IsClientUser]

    def get(self, request):
        import csv
        import io

        from django.http import HttpResponse
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['number (masked)', 'first contact', 'contacts this month'])
        writer.writerows(billed_numbers(request.user.client))
        response = HttpResponse(out.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="billed-numbers.csv"'
        return response


class RevocationView(APIView):
    """Revocation page: M08 / M09, the opt-out matrix, the time-to-stop chart and the stop-word list from the client's
    real opt-outs (Module 9; no paid test lines), and the Annex C signed date (None until signed)."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from apps.optouts.measures import revocation_page
        client = request.user.client
        doc = ClientDocument.objects.filter(client=client, kind=ClientDocument.Kind.ANNEX_C, signed_on__isnull=False).order_by('-signed_on').first()
        page = revocation_page(client)
        page['authorisation'] = {'signedOn': doc.signed_on.isoformat() if doc else None, 'windowFrom': page.pop('windowFrom'),
                                 'windowTo': page.pop('windowTo'), 'channels': page.pop('channels')}
        return Response(page)


class NotificationsView(APIView):
    """PATCH /api/settings/email/notifications {kind, email}: the Admin chooses which alert types are also emailed to
    the company's Admins (owner decision 2026-10-23)."""
    permission_classes = [IsClientAdmin]

    def patch(self, request):
        from apps.alerts.emails import TYPES
        from apps.alerts.models import EmailChoice
        kind = request.data.get('kind')
        if not isinstance(kind, str) or kind not in TYPES:
            return Response({'detail': 'Notification not found.'}, status=404)
        row, _ = EmailChoice.objects.get_or_create(client=request.user.client, kind=kind,
                                                   defaults={'email': True, 'by': request.user.name})
        row.email, row.by = yes(request.data.get('email')), request.user.name
        row.save()
        return Response({'kind': kind, 'label': TYPES[kind][0], 'email': row.email})
