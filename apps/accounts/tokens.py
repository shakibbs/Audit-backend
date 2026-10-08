"""Link tokens: password reset (signed, 1 hour) and invite (random, 7 days, hash kept)."""
import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

INVITE_LIFETIME = timedelta(days=7)


class ClientResetTokenGenerator(PasswordResetTokenGenerator):
    # Own salt, so a staff reset token can never be used for a client account.
    key_salt = 'civ.accounts.ClientResetTokenGenerator'


reset_tokens = ClientResetTokenGenerator()


def encode_uid(pk: int) -> str:
    return urlsafe_base64_encode(force_bytes(pk))


def decode_uid(uid: str) -> int | None:
    try:
        return int(force_str(urlsafe_base64_decode(uid)))
    except (TypeError, ValueError, OverflowError):
        return None


def new_invite_token() -> tuple[str, str]:
    """Returns (token for the email, hash for the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_invite_token(token)


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
