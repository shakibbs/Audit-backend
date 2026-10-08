"""POST /api/session/sign-in: email + password for client users only."""
from django.contrib.auth.hashers import make_password
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.lockout import is_locked
from apps.accounts.models import ClientUser
from apps.accounts.serializers.session import session_data
from apps.accounts.serializers.sign_in import SignInSerializer
from apps.accounts.session import sign_in

WRONG = 'That email and password do not match an account.'
LOCKED = 'Too many tries. Wait 15 minutes, then try again.'


@method_decorator(csrf_protect, name='dispatch')
class SignInView(APIView):
    def post(self, request):
        form = SignInSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        email, password = form.validated_data['email'], form.validated_data['password']

        if is_locked(email):
            record('sign_in_locked', request=request, actor_kind='anonymous', object=email)
            return Response({'detail': LOCKED}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        user = ClientUser.objects.select_related('client').filter(email=email).first()
        if user is None:
            make_password(password)  # same work as a real check, so timing does not reveal unknown emails
        ok = user is not None and user.check_password(password) and user.is_active and user.client.is_active
        if not ok:
            record('sign_in_failed', request=request, actor_kind='anonymous', object=email,
                   client_id=user.client_id if user else None)
            return Response({'detail': WRONG}, status=status.HTTP_400_BAD_REQUEST)

        sign_in(request, user)
        record('sign_in', request=request, actor_kind='client_user', actor_id=user.pk,
               actor_label=user.email, client_id=user.client_id)
        return Response(session_data(user))
