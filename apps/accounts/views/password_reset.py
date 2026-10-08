"""POST /api/session/reset and /api/session/reset/confirm."""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.emails import send_reset
from apps.accounts.models import ClientUser
from apps.accounts.serializers.password_reset import ResetConfirmSerializer, ResetRequestSerializer
from apps.accounts.tokens import decode_uid, encode_uid, reset_tokens

BAD_LINK = 'This link has expired or was already used. Ask for a new one.'


@method_decorator(csrf_protect, name='dispatch')
class ResetRequestView(APIView):
    # Always answers "sent", so nobody can learn which emails have accounts.
    def post(self, request):
        form = ResetRequestSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        email = form.validated_data['email']
        user = ClientUser.objects.select_related('client').filter(email=email, is_active=True, client__is_active=True).first()
        if user is not None:
            send_reset(user, encode_uid(user.pk), reset_tokens.make_token(user))
        record('password_reset_requested', request=request, actor_kind='anonymous', object=email,
               client_id=user.client_id if user else None)
        return Response({'sent': True})


@method_decorator(csrf_protect, name='dispatch')
class ResetConfirmView(APIView):
    def post(self, request):
        link = str(request.data.get('link', ''))
        uid, _, token = link.partition('.')
        pk = decode_uid(uid)
        user = ClientUser.objects.filter(pk=pk, is_active=True).first() if pk else None
        if user is None or not reset_tokens.check_token(user, token):
            return Response({'detail': BAD_LINK}, status=status.HTTP_400_BAD_REQUEST)

        form = ResetConfirmSerializer(data=request.data, context={'user': user})
        form.is_valid(raise_exception=True)
        user.set_password(form.validated_data['password'])  # also ends every old session
        user.save(update_fields=['password'])
        record('password_reset_done', request=request, actor_kind='client_user', actor_id=user.pk,
               actor_label=user.email, client_id=user.client_id)
        return Response({'done': True})
