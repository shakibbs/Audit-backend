"""POST /api/session/reset/confirm: a new password from a link CiV staff sent. There is no "forgot password" request
any more (owner, 2026-10-22/23): only staff send password links."""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.models import ClientUser
from apps.accounts.serializers.password_reset import ResetConfirmSerializer
from apps.accounts.tokens import decode_uid, reset_tokens

BAD_LINK = 'This link has expired or was already used. Ask for a new one.'


@method_decorator(csrf_protect, name='dispatch')
class ResetConfirmView(APIView):
    def post(self, request):
        link = str(request.data.get('link', ''))
        if link.startswith('b-'):
            return buyer_confirm(request, link[2:])
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


def buyer_confirm(request, link: str):
    """An insurer or acquirer person's new password, from a link CiV staff sent."""
    from apps.buyers.models import BuyerUser
    from apps.accounts.tokens import buyer_reset_tokens
    uid, _, token = link.partition('.')
    pk = decode_uid(uid)
    user = BuyerUser.objects.select_related('org').filter(pk=pk, is_active=True, org__is_active=True).first() if pk else None
    if user is None or not buyer_reset_tokens.check_token(user, token):
        return Response({'detail': BAD_LINK}, status=status.HTTP_400_BAD_REQUEST)
    form = ResetConfirmSerializer(data=request.data, context={'user': user})
    form.is_valid(raise_exception=True)
    user.set_password(form.validated_data['password'])
    user.save(update_fields=['password'])
    return Response({'done': True})
