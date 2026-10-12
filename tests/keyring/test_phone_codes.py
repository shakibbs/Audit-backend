"""Phone codes: same number → same code; different client → different code; the number is never saved."""
import base64
import hashlib
import hmac

import pytest

from apps.access_log.models import AccessEntry
from apps.connections.crypto import unlock
from apps.keyring.models import ClientKey
from apps.keyring.phones import normalize
from apps.keyring.tokens import KeyDestroyed, Tokenizer, destroy_key


def test_every_way_of_writing_a_number_is_cleaned_the_same():
    for raw in ['(916) 555-4471', '916.555.4471', '+1 916 555 4471', '19165554471', '9165554471']:
        assert normalize(raw) == '+19165554471'
    assert normalize('+44 20 7946 0958') == '+442079460958'  # non-US numbers keep their country
    assert normalize('12') is None and normalize('not a number') is None


@pytest.mark.django_db
def test_same_number_same_code_for_one_client(company):
    codes = Tokenizer(company)
    assert codes.token('(916) 555-4471') == codes.token('+1 916 555 4471')
    assert codes.token('(916) 555-4471') != codes.token('(916) 555-4472')
    assert codes.token('12') is None


@pytest.mark.django_db
def test_two_clients_get_different_codes(company, other_company):
    assert Tokenizer(company).token('9165554471') != Tokenizer(other_company).token('9165554471')


@pytest.mark.django_db
def test_code_is_hmac_of_the_number_and_the_key_is_stored_locked(company):
    codes = Tokenizer(company)
    key = ClientKey.objects.get(client=company)
    secret = base64.b64decode(unlock(key.locked_key)['k'])
    assert codes.token('9165554471') == hmac.new(secret, b'+19165554471', hashlib.sha256).hexdigest()
    assert codes.kid == 'k1' and len(secret) == 32
    assert base64.b64encode(secret).decode() not in key.locked_key  # never saved in the clear
    assert '9165554471' not in codes.token('9165554471')


@pytest.mark.django_db
def test_key_is_made_once_and_logged(company):
    Tokenizer(company)
    Tokenizer(company)
    assert ClientKey.objects.filter(client=company).count() == 1
    assert AccessEntry.objects.filter(action='client_key_created', client_id=company.pk).count() == 1


@pytest.mark.django_db
def test_destroyed_key_makes_no_more_codes(company):
    Tokenizer(company)
    destroy_key(company, actor_label='team@complyiv.com')
    key = ClientKey.objects.get(client=company)
    assert key.locked_key == '' and key.destroyed_at is not None
    assert AccessEntry.objects.filter(action='client_key_destroyed', client_id=company.pk).exists()
    with pytest.raises(KeyDestroyed):
        Tokenizer(company)
