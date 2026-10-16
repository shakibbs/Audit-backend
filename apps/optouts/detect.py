"""Hand-off receiver: STOP texts (whole message is a Rulebook stop word, read in memory only) and CRM "do not call"
boxes. The tool's own result codes (e.g. "DNC") are not used here: the AI judges them (Module 9)."""
import json
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.contacts.normalize import codes_for
from apps.keyring.phones import normalize as clean_number

from .models import OptOutEvent

DEFAULT_KEYWORDS = ['STOP', 'QUIT', 'END', 'REVOKE', 'OPT OUT', 'OPTOUT', 'CANCEL', 'UNSUBSCRIBE']


def keywords() -> list[str]:
    from apps.rulebook.lookup import NoRulebook, RuleSet
    try:
        return RuleSet().get('optout_keywords', on=timezone.localdate()).value or DEFAULT_KEYWORDS
    except NoRulebook:
        return DEFAULT_KEYWORDS


def stop_word(body: str) -> str:
    """The stop word when the WHOLE message is one ("Stop", "STOP!", " unsubscribe "); '' for normal sentences."""
    text = re.sub(r'[\s.!]+$', '', (body or '').strip()).upper()
    text = re.sub(r'\s+', ' ', text)
    return next((k for k in keywords() if text == k.upper()), '')


def _save(**fields) -> None:
    try:
        with transaction.atomic():
            OptOutEvent.objects.create(**fields)
    except IntegrityError:
        pass  # already on the list


def optout_seen(client, connection, record, phone_tokens) -> None:
    try:
        row = json.loads(record.raw)
    except ValueError:
        return
    provider = connection.provider
    if provider == 'twilio' and record.content_kind == 'text' and str(row.get('direction', '')).startswith('inbound'):
        word = stop_word(row.get('body', ''))
        number = clean_number(row.get('from', ''))
        if word and number:
            _save(client=client, phone_token=codes_for(client).token(number), at=record.changed_at, channel='text',
                  method=OptOutEvent.Method.KEYWORD, keyword=word, source_system=provider, source_record_id=record.source_record_id)
    elif provider == 'salesforce' and record.content_kind in ('lead', 'crm_record') and row.get('DoNotCall') is True:
        for token in phone_tokens:
            _save(client=client, phone_token=token, at=record.changed_at, channel='crm', method=OptOutEvent.Method.CRM_FLAG,
                  source_system=provider, source_record_id=record.source_record_id)
