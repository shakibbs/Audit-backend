"""Shapes of the reset request and the new-password step."""
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


class ResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class NewPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(trim_whitespace=False, max_length=256)

    def validate_password(self, value: str) -> str:
        validate_password(value, self.context.get('user'))
        return value


class ResetConfirmSerializer(NewPasswordSerializer):
    link = serializers.CharField(max_length=512)  # "<uid>.<token>" from the email link
