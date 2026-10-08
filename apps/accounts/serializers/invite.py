"""Shapes of sending an invite and accepting one."""
from rest_framework import serializers

from apps.accounts.models import Role
from apps.accounts.serializers.password_reset import NewPasswordSerializer


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=Role.choices, default=Role.MEMBER)
    isCounsel = serializers.BooleanField(default=False)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class AcceptInviteSerializer(NewPasswordSerializer):
    token = serializers.CharField(max_length=128)
