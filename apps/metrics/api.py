"""Client API: every metric (catalog.py words; values from the engines, "Not measured" where none runs yet) and the
Contact Conduct charts. A month with a saved copy (Module 10) is read from it."""

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.refs import yes

from .catalog import complete
from .conduct import conduct_metrics, conduct_page
from .models import LeadSourceCheck
from .overview import overview_metrics
from .who import COLUMNS, lead_sources, who_contact


def period_of(request) -> str | None:
    from apps.refs import month
    return month(request.query_params.get('period'))


class MetricsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        client, period = request.user.client, period_of(request)
        if period:
            from apps.scoring.snapshots import saved_metrics
            saved = saved_metrics(client, period)
            if saved is not None:
                return Response(complete(saved))  # the month's saved copy (Module 10)
        return Response(complete(conduct_metrics(client, period) + overview_metrics(client, period)))


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
        if row is None or not isinstance(column, str) or column not in COLUMNS:
            return Response({'detail': 'Lead source not found.'}, status=404)
        checked = yes(request.data.get('checked'))
        LeadSourceCheck.objects.update_or_create(client=user.client, source_key=row['key'], column=column,
                                                 defaults={'checked': checked, 'set_by': user})
        record('lead_source_marked', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f"{row['name']} · {column} · {'checked' if checked else 'not checked'}"[:254])
        row['checked'][column] = checked
        return Response(row)
