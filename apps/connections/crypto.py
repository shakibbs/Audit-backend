"""Locks and unlocks client API keys. Keys come from CIV_SECRETS_KEYS; the first one locks, any one unlocks."""
import json
import os

from cryptography.fernet import Fernet, MultiFernet
from django.core.exceptions import ImproperlyConfigured


def _box() -> MultiFernet:
    keys = [k.strip() for k in os.environ.get('CIV_SECRETS_KEYS', '').split(',') if k.strip()]
    if not keys:
        raise ImproperlyConfigured('CIV_SECRETS_KEYS is not set; client API keys cannot be stored.')
    return MultiFernet([Fernet(k) for k in keys])


def lock(values: dict) -> str:
    return _box().encrypt(json.dumps(values).encode()).decode()


def unlock(token: str) -> dict:
    return json.loads(_box().decrypt(token.encode())) if token else {}
