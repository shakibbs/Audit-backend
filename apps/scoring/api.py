"""Client API (Module 10 step 5): GET /api/score and /api/domains for a month (latest saved month when none is
asked). Partly real pages: the portal keeps its sample for what is not sent."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.metrics.api import period_of

from .portal import domains_page, score_page


class ScoreView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response(score_page(request.user.client, period_of(request)))


class DomainsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response(domains_page(request.user.client, period_of(request)))
