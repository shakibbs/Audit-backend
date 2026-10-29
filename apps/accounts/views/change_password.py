"""POST /api/session/password: any signed-in person (client user, lawyer, insurer or acquirer) changes their own
password with their current one (owner decision 2026-10-22). Other devices are signed out; this one stays in."""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.lockout import is_locked
from apps.accounts.models import ClientUser
from apps.accounts.serializers.password_reset import NewPasswordSerializer

WRONG = 'Your current password is not right.'
SAME = 'Your new password must be different from your current one.'


@method_decorator(csrf_protect, name='dispatch')
class ChangePasswordView(APIView):
    def post(self, request):
        from apps.buyers.models import BuyerUser
        user = request.user
        if not isinstance(user, (ClientUser, BuyerUser)):
            return Response({'detail': 'Sign in to continue.'}, status=status.HTTP_401_UNAUTHORIZED)
        client_id = user.client_id if isinstance(user, ClientUser) else None
        if is_locked(user.email, request=request):
            return Response({'detail': 'Too many wrong tries. Wait 15 minutes and try again.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if not user.check_password(str(request.data.get('current', ''))):
            # counts toward the same 5-tries lock as sign-in
            # the person is signed in: logged as who they are, and it counts toward the same 5-tries lock as sign-in
            record('wrong_current_password', request=request, actor_kind='client_user' if client_id else 'buyer', actor_id=user.pk,
                   actor_label=user.email if client_id else f'{user.name or user.email} ({user.org.name})', object=user.email, client_id=client_id)
            return Response({'detail': WRONG}, status=status.HTTP_400_BAD_REQUEST)
        form = NewPasswordSerializer(data=request.data, context={'user': user})
        form.is_valid(raise_exception=True)
        if user.check_password(form.validated_data['password']):  # owner, 2026-10-23
            return Response({'detail': SAME}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(form.validated_data['password'])
        user.save(update_fields=['password'])
        if isinstance(user, ClientUser):
            from apps.accounts.session import HASH_KEY
            record('password_changed', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email, client_id=client_id)
        else:
            from apps.buyers.session import HASH_KEY
        request.session[HASH_KEY] = user.get_session_auth_hash()  # keep this device signed in
        return Response({'done': True})
