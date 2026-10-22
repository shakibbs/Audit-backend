"""Client API: the Settings page fields that are real now (company facts, states contacted, agreements) and the Annex C
signed date for Revocation Integrity. Fields not known yet are left out: the portal keeps its sample for them."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientAdmin, IsClientUser
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
        return Response({'company': {'name': client.name, 'vertical': client.industry or '—', 'states': states,
                                     'engaged': client.start_date.isoformat()},
                         'agreements': agreements(client), 'usage': usage(client),
                         'notifications': choices(client)})  # alert emails to Admins (owner, 2026-10-23)


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
    """Revocation page: M08 / M09, the opt-out matrix and the time-to-stop chart from the client's real opt-outs
    (Module 9; no paid test lines), and the Annex C signed date. Wording coverage stays with the sample."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from apps.optouts.measures import revocation_page
        client = request.user.client
        doc = ClientDocument.objects.filter(client=client, kind=ClientDocument.Kind.ANNEX_C, signed_on__isnull=False).order_by('-signed_on').first()
        return Response({**revocation_page(client), 'authorisation': {'signedOn': doc.signed_on.isoformat() if doc else '—'}})


class NotificationsView(APIView):
    """PATCH /api/settings/email/notifications {kind, email}: the Admin chooses which alert types are also emailed to
    the company's Admins (owner decision 2026-10-23)."""
    permission_classes = [IsClientAdmin]

    def patch(self, request):
        from apps.alerts.emails import TYPES
        from apps.alerts.models import EmailChoice
        kind = request.data.get('kind')
        if kind not in TYPES:
            return Response({'detail': 'Notification not found.'}, status=404)
        row, _ = EmailChoice.objects.get_or_create(client=request.user.client, kind=kind,
                                                   defaults={'email': True, 'by': request.user.name})
        row.email, row.by = bool(request.data.get('email')), request.user.name
        row.save()
        return Response({'kind': kind, 'label': TYPES[kind][0], 'email': row.email})
