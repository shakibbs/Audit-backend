"""Client API: the metrics that are real so far (Contact Conduct: M15–M19, M21, M31) and the Contact Conduct charts.
/api/metrics sends only these; the portal keeps its sample for the others until Module 10."""
import re

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser

from .conduct import conduct_metrics, conduct_page
from .models import LeadSourceCheck
from .overview import overview_metrics
from .who import COLUMNS, lead_sources, who_contact


def period_of(request) -> str | None:
    period = request.query_params.get('period') or ''
    return period if re.fullmatch(r'\d{4}-\d{2}', period) else None


class MetricsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        client, period = request.user.client, period_of(request)
        return Response(conduct_metrics(client, period) + overview_metrics(client, period))


class ConductView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response(conduct_page(request.user.client, period_of(request)))


class WhoContactView(APIView):
    """GET the real parts of Who You Contact; PATCH <lead source> {column, checked}: the client's own statement."""
    permission_classes = [IsClientUser]

    def get(self, request, ref=None):
        return Response(who_contact(request.user.client))

    def patch(self, request, ref=None):
        from apps.access_log.recorder import record
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your company lawyer can change these.'}, status=403)
        row = next((r for r in lead_sources(user.client) if r['id'] == ref), None)
        column = request.data.get('column')
        if row is None or column not in COLUMNS:
            return Response({'detail': 'Lead source not found.'}, status=404)
        checked = bool(request.data.get('checked'))
        LeadSourceCheck.objects.update_or_create(client=user.client, source_key=row['key'], column=column,
                                                 defaults={'checked': checked, 'set_by': user})
        record('lead_source_marked', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f"{row['name']} · {column} · {'checked' if checked else 'not checked'}"[:254])
        row['checked'][column] = checked
        return Response(row)
