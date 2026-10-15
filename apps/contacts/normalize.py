"""Hand-off receiver: every synced call or text → one ContactEvent (updated, not doubled, when the tool changes it)."""
import time

from apps.keyring.phones import normalize as clean_number
from apps.keyring.tokens import Tokenizer
from apps.sync.process import connection_grade

from .dedupe import group
from .epochs import attach
from .location import locate
from .models import ContactEvent


def mask(e164: str) -> str:
    """'+19165550001' → '(916) •••-0001'; outside the +1 plan: country code and last 4 only."""
    if e164.startswith('+1') and len(e164) == 12:
        return f'({e164[2:5]}) •••-{e164[-4:]}'
    return f'{e164[:3]} ••• {e164[-4:]}'
from .translators import translate

KEY_SECONDS = 300  # a client's opened phone-code key is reused for a few minutes, not re-opened for every record
_keys: dict[int, tuple[float, Tokenizer]] = {}


def codes_for(client) -> Tokenizer:
    cached = _keys.get(client.pk)
    if cached and time.monotonic() - cached[0] < KEY_SECONDS:
        return cached[1]
    codes = Tokenizer(client)
    _keys[client.pk] = (time.monotonic(), codes)
    return codes


def normalize_record(client, connection, record, phone_tokens) -> None:
    fields = translate(connection.provider, record)
    if fields is None:
        return
    codes = codes_for(client)
    number = clean_number(fields.pop('person'))
    if number is None:
        return  # not a phone number: nothing to check
    person = codes.token(number)
    fields.update(locate(number))  # worked out while the number is in memory; only state / zones / country kept
    fields['masked_label'] = mask(number)
    caller = fields.pop('caller_id', None)
    fields['caller_id_token'] = (codes.token(caller) or '') if caller else ''
    contact, _ = ContactEvent.objects.update_or_create(
        client=client, source_system=connection.provider, source_record_id=record.source_record_id,
        defaults={**fields, 'phone_token': person, 'phone_token_kid': codes.kid, 'source_grade': connection_grade(connection)})
    group(contact)  # the same call or text from another tool is counted once
    attach(contact)  # which owner of the number it reached
