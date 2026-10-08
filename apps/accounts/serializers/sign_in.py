"""Checks the shape of a sign-in request."""
from rest_framework import serializers


class SignInSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, max_length=256)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()
