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
from .who import COLUMNS, lead_sources, marked_by, who_contact


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


class WhoNumbersView(APIView):
    """GET ?source=all|<lead source id>&column=national|state|internal|reassigned[&period=]: the phone numbers behind a count
    on Who You Contact (owner 2026-11-16), masked; at most 100, with the total. Each look is written to the access log."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from apps.access_log.recorder import record

        from .per_source import numbers
        source, column = request.query_params.get('source', 'all'), request.query_params.get('column')
        if column not in COLUMNS or not isinstance(source, str) or len(source) > 40:
            return Response({'detail': 'Choose a list: national, state, internal or reassigned.'}, status=400)
        user = request.user
        found = numbers(user.client, period_of(request), source, column)
        if found is None:
            return Response({'detail': 'Lead source not found.'}, status=404)
        record('who_numbers_viewed', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f"{found['source']} · {column} · {found['total']:,} numbers"[:254])
        return Response(found)


class WhoContactView(APIView):
    """GET the real parts of Who You Contact; PATCH <lead source> {column, checked}: the client's own statement."""
    permission_classes = [IsClientUser]

    def get(self, request, ref=None):
        return Response(who_contact(request.user.client, period_of(request)))

    def patch(self, request, ref=None):
        from apps.access_log.recorder import record
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your company lawyer can change these.'}, status=403)
        row = next((r for r in lead_sources(user.client, found=False) if r['id'] == ref), None)
        column = request.data.get('column')
        if row is None or not isinstance(column, str) or column not in COLUMNS:
            return Response({'detail': 'Lead source not found.'}, status=404)
        checked = yes(request.data.get('checked'))
        mark, _ = LeadSourceCheck.objects.update_or_create(client=user.client, source_key=row['key'], column=column,
                                                           defaults={'checked': checked, 'set_by': user})
        record('lead_source_marked', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f"{row['name']} · {column} · {'checked' if checked else 'not checked'}"[:254])
        row['checked'][column] = checked
        row['markedBy'][column] = marked_by(mark) if checked else None
        return Response(row)
