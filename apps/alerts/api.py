"""Client API: GET /api/alerts and POST /api/alerts/<id>/review. In lawyer-only mode (counsel-directed) alerts reach
only Admins and users marked as the company's lawyer (same rule as the portal); anyone who can see an alert can mark it
reviewed. Reviewed and resolved alerts stay in the history."""
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .models import Alert


def can_see(user) -> bool:
    return not user.client.counsel_directed or user.is_admin or user.is_counsel


def row(a: Alert) -> dict:
    detail = a.detail + (f' Resolved {a.resolved_at:%-d %b}.' if a.resolved_at else '')
    return {'id': f'al-{a.pk}', 'severity': a.severity, 'kind': a.kind, 'title': a.title, 'detail': detail, 'at': a.at,
            'domain': a.domain, 'reviewed': a.reviewed, 'routedTo': 'legal' if a.client.counsel_directed else 'all',
            'resolved': a.resolved_at is not None, 'reviewedBy': a.reviewed_by or None}


class AlertsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        if not can_see(request.user):
            return Response([])
        return Response([row(a) for a in Alert.objects.filter(client=request.user.client).select_related('client')[:500]])


class ReviewView(APIView):
    permission_classes = [IsClientUser]

    def post(self, request, ref: str):
        user = request.user
        pk = ref.removeprefix('al-')
        alert = Alert.objects.filter(client=user.client, pk=int(pk) if pk.isdigit() else 0).first()
        if alert is None or not can_see(user):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not alert.reviewed:
            alert.reviewed, alert.reviewed_by, alert.reviewed_at = True, user.name, timezone.now()
            alert.save(update_fields=['reviewed', 'reviewed_by', 'reviewed_at'])
            record('alert_reviewed', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
                   client_id=user.client_id, object=alert.title[:254])
        return Response(row(alert))
