"""POST /api/session/sign-out."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser
from apps.accounts.serializers.session import session_data
from apps.accounts.session import sign_out


class SignOutView(APIView):
    def post(self, request):
        from apps.buyers.models import BuyerUser
        from apps.buyers.session import sign_out as buyer_out
        if isinstance(request.user, BuyerUser):  # Module 15
            buyer_out(request)
            request.session.cycle_key()
            return Response(session_data(None))
        if not IsClientUser().has_permission(request, self):
            return Response({'detail': 'Authentication credentials were not provided.'}, status=401)
        user = request.user
        sign_out(request)
        record('sign_out', request=request, actor_kind='client_user', actor_id=user.pk,
               actor_label=user.email, client_id=user.client_id)
        return Response(session_data(None))
