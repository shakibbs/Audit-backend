"""POST /api/session/sign-out."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser
from apps.accounts.serializers.session import session_data
from apps.accounts.session import sign_out


class SignOutView(APIView):
    permission_classes = [IsClientUser]

    def post(self, request):
        user = request.user
        sign_out(request)
        record('sign_out', request=request, actor_kind='client_user', actor_id=user.pk,
               actor_label=user.email, client_id=user.client_id)
        return Response(session_data(None))
