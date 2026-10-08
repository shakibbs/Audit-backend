"""The Users page API. Everyone sees their own company; only an Admin changes anything."""
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.emails import send_invite
from apps.accounts.models import ClientUser, Invite, Role
from apps.accounts.permissions import IsClientAdmin, IsClientUser
from apps.accounts.serializers.invite import InviteSerializer
from apps.accounts.serializers.user import UserChangeSerializer, invite_row, user_row
from apps.accounts.tokens import INVITE_LIFETIME, new_invite_token

LAST_ADMIN = 'A company needs at least one active Admin.'


def log(request, action: str, obj: str) -> None:
    user = request.user
    record(action, request=request, actor_kind='client_user', actor_id=user.pk,
           actor_label=user.email, client_id=user.client_id, object=obj)


def row_pk(row_id: str, prefix: str) -> int | None:
    """'u-12' -> 12; anything else -> None."""
    rest = row_id.removeprefix(prefix)
    return int(rest) if row_id.startswith(prefix) and rest.isdigit() else None


def find_user(request, row_id: str) -> ClientUser | None:
    pk = row_pk(row_id, 'u-')
    return ClientUser.objects.filter(pk=pk, client=request.user.client, is_active=True).first() if pk else None


def other_admins(user: ClientUser) -> bool:
    return ClientUser.objects.filter(client=user.client, role=Role.ADMIN, is_active=True).exclude(pk=user.pk).exists()


class UsersView(APIView):
    def get_permissions(self):
        return [IsClientAdmin()] if self.request.method == 'POST' else [IsClientUser()]

    def get(self, request):
        client = request.user.client
        users = [user_row(u) for u in client.users.filter(is_active=True)]
        invites = [invite_row(i) for i in client.invites.filter(used_at__isnull=True, expires_at__gt=timezone.now())]
        return Response(users + invites)

    def post(self, request):
        form = InviteSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        if ClientUser.objects.filter(email=data['email']).exists():
            return Response({'detail': 'That email already has an account.'}, status=status.HTTP_400_BAD_REQUEST)

        client = request.user.client
        token, token_hash = new_invite_token()
        with transaction.atomic():
            client.invites.filter(email=data['email'], used_at__isnull=True).delete()  # a new invite replaces an old one
            invite = Invite.objects.create(
                client=client, email=data['email'], name=data.get('name') or '', role=data['role'],
                is_counsel=data['isCounsel'], invited_by=request.user, token_hash=token_hash,
                expires_at=timezone.now() + INVITE_LIFETIME,
            )
        send_invite(invite, token)
        log(request, 'invite_sent', invite.email)
        return Response(invite_row(invite), status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [IsClientAdmin]

    def patch(self, request, row_id: str):
        user = find_user(request, row_id)
        if user is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        form = UserChangeSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        if data.get('role') == Role.MEMBER and user.is_admin and not other_admins(user):
            return Response({'detail': LAST_ADMIN}, status=status.HTTP_400_BAD_REQUEST)
        if 'role' in data:
            user.role = data['role']
        if 'isCounsel' in data:
            user.is_counsel = data['isCounsel']
        user.save(update_fields=['role', 'is_counsel'])
        log(request, 'user_changed', f'{user.email} role={user.role} lawyer={user.is_counsel}')
        return Response(user_row(user))

    def delete(self, request, row_id: str):
        client = request.user.client
        if row_id.startswith('inv-'):
            deleted, _ = client.invites.filter(pk=row_pk(row_id, 'inv-'), used_at__isnull=True).delete()
            if not deleted:
                return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
            log(request, 'invite_cancelled', row_id)
            return Response(status=status.HTTP_204_NO_CONTENT)

        user = find_user(request, row_id)
        if user is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if user.pk == request.user.pk:
            return Response({'detail': 'You cannot turn off your own access.'}, status=status.HTTP_400_BAD_REQUEST)
        if user.is_admin and not other_admins(user):
            return Response({'detail': LAST_ADMIN}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = False  # kept for the access log; can no longer sign in
        user.save(update_fields=['is_active'])
        log(request, 'user_turned_off', user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)
