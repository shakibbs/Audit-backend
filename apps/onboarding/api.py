"""Client API: Setup & Readiness (the real parts; the portal keeps its sample for the rest)."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientAdmin, IsClientUser

from .readiness import readiness


class ReadinessView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response(readiness(request.user.client))


class SetupMarkView(APIView):
    """PATCH /api/setup/<item> {done}: the company's Admin ticks a Setup & Readiness checklist row (owner, 2026-10-23)."""
    permission_classes = [IsClientAdmin]

    def patch(self, request, item: str):
        from .models import SetupMark
        from .readiness import SETUP_ITEMS
        if item not in SETUP_ITEMS:
            return Response({'detail': 'Item not found.'}, status=404)
        mark, _ = SetupMark.objects.get_or_create(client=request.user.client, item=item, defaults={'by': request.user.name})
        mark.done, mark.by = bool(request.data.get('done')), request.user.name
        mark.save()
        return Response({'id': item, 'done': mark.done})
