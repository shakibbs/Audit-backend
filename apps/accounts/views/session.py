"""GET /api/session: who is signed in. Also hands the browser its CSRF cookie."""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ClientUser
from apps.accounts.serializers.session import session_data


@method_decorator(ensure_csrf_cookie, name='dispatch')
class SessionView(APIView):
    def get(self, request):
        user = request.user if isinstance(request.user, ClientUser) else None
        return Response(session_data(user))
