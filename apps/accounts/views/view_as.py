"""POST /api/session/view-as {view}: a client user switches their OWN view between Owner and Underwriter (owner decision
2026-10-22). Saved per person; nobody else's screen changes. Insurers are always on the Underwriter view and cannot
switch."""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ClientUser
from apps.accounts.serializers.session import session_data


@method_decorator(csrf_protect, name='dispatch')
class ViewAsView(APIView):
    def post(self, request):
        user = request.user
        if not isinstance(user, ClientUser):
            return Response({'detail': 'Only a client user can switch views.'}, status=status.HTTP_403_FORBIDDEN)
        view = request.data.get('view')
        if view not in ('owner', 'underwriter'):
            return Response({'detail': 'Choose Owner or Underwriter.'}, status=status.HTTP_400_BAD_REQUEST)
        user.view = view
        user.save(update_fields=['view'])
        return Response(session_data(user))
