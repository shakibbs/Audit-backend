"""Client API: Setup & Readiness (the real parts; the portal keeps its sample for the rest)."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser

from .readiness import readiness


class ReadinessView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response(readiness(request.user.client))
