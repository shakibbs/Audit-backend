"""Rows of the Users page: people with access, then pending invites."""
from rest_framework import serializers

from apps.accounts.models import ClientUser, Invite, Role


def user_row(user: ClientUser) -> dict:
    return {
        'id': f'u-{user.pk}', 'name': user.name, 'email': user.email, 'role': user.role,
        'isCounsel': user.is_counsel, 'status': 'active' if user.is_active else 'off',
        'lastSeen': user.last_login.isoformat() if user.last_login else None,
    }


def invite_row(invite: Invite) -> dict:
    return {
        'id': f'inv-{invite.pk}', 'name': invite.name, 'email': invite.email, 'role': invite.role,
        'isCounsel': invite.is_counsel, 'status': 'invited', 'lastSeen': None,
    }


class UserChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices, required=False)
    isCounsel = serializers.BooleanField(required=False)
