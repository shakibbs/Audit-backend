"""GET /api/invites/check and POST /api/invites/accept: the invited person sets a password."""
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.models import ClientUser, Invite
from apps.accounts.serializers.invite import AcceptInviteSerializer
from apps.accounts.serializers.session import session_data
from apps.accounts.session import sign_in
from apps.accounts.tokens import hash_invite_token

BAD_LINK = 'This invite has expired or was already used. Ask your Admin for a new one.'


def open_invite(token: str) -> Invite | None:
    return Invite.objects.select_related('client').filter(
        token_hash=hash_invite_token(token), used_at__isnull=True,
        expires_at__gt=timezone.now(), client__is_active=True,
    ).first()


class InviteCheckView(APIView):
    def get(self, request):
        token = request.query_params.get('token', '')
        invite = open_invite(token)
        if invite is None:
            from apps.buyers.invite import open_invite as open_buyer_invite
            if (buyer_invite := open_buyer_invite(token)) is not None:  # Module 15: a person at an insurer or acquirer
                return Response({'email': buyer_invite.email, 'name': buyer_invite.name, 'clientName': buyer_invite.org.name})
            return Response({'detail': BAD_LINK}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'email': invite.email, 'name': invite.name, 'clientName': invite.client.name})


@method_decorator(csrf_protect, name='dispatch')
class AcceptInviteView(APIView):
    def post(self, request):
        invite = open_invite(str(request.data.get('token', '')))
        if invite is None:
            return accept_buyer(request)  # Module 15
        if ClientUser.objects.filter(email=invite.email).exists():
            return Response({'detail': BAD_LINK}, status=status.HTTP_400_BAD_REQUEST)

        form = AcceptInviteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        with transaction.atomic():
            user = ClientUser.objects.create_user(
                client=invite.client, email=invite.email, name=invite.name or invite.email,
                password=form.validated_data['password'], role=invite.role, is_counsel=invite.is_counsel,
            )
            invite.used_at = timezone.now()
            invite.save(update_fields=['used_at'])
        sign_in(request, user)
        record('invite_accepted', request=request, actor_kind='client_user', actor_id=user.pk,
               actor_label=user.email, client_id=user.client_id)
        return Response(session_data(user))


def accept_buyer(request):
    """An insurer or acquirer person sets a password from a client's invite (Module 15) and is signed in."""
    from apps.buyers.invite import accept, open_invite as open_buyer_invite
    from apps.buyers.models import BuyerUser
    from apps.buyers.session import session_data as buyer_data, sign_in as buyer_in
    invite = open_buyer_invite(str(request.data.get('token', '')))
    if invite is None or BuyerUser.objects.filter(email=invite.email).exists() or ClientUser.objects.filter(email__iexact=invite.email).exists():
        return Response({'detail': BAD_LINK}, status=status.HTTP_400_BAD_REQUEST)
    form = AcceptInviteSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    user = accept(invite, form.validated_data['password'])
    buyer_in(request, user)
    record('invite_accepted', request=request, actor_kind='buyer', actor_id=user.pk, actor_label=f'{user.name or user.email} ({user.org.name})',
           client_id=invite.client_id, object=user.email)
    return Response(buyer_data(user))
