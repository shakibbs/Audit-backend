"""Module 9 step 2: every recorded call is listened to (pretend recordings, speech-to-text and AI here); the customer's
words count, the agent's don't; the moment is the second in the call; the recording and the words are not kept."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.conversations import ai, readers, speech
from apps.conversations.models import ConversationReview
from apps.conversations.review import review_due
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load

pytestmark = pytest.mark.django_db
NOW = timezone.now()
CALLS = {}  # pretend dialer: call ID → the conversation the transcriber "hears"


def transcriber(audio):
    return [dict(turn) for turn in CALLS[audio.decode()]]


def reviewer(turns):
    for i, turn in enumerate(turns):
        if 'call me again' in turn['text'].lower() or turn['text'].lower() == 'stop':
            return 'opted_out', i, 0.97
    return 'none', None, 0.95


reviewer.model = 'pretend-ai'


def no_recording(connection, record_id):
    raise readers.NoRecording()


@pytest.fixture(autouse=True)
def setup(company, monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    CALLS.clear()
    Connection.objects.create(client=company, provider='vicidial', status=Status.CONNECTED)
    monkeypatch.setitem(readers.RECORDINGS, 'vicidial', lambda connection, record_id: record_id.encode())
    yield
    ai.use(None)
    speech.use(None)


n = iter(range(10**6))


def call(company, turns, minutes_ago=30, system='vicidial'):
    record = f'vicidial_log:{next(n)}'
    CALLS[record] = turns
    at = NOW - timedelta(minutes=minutes_ago)
    return ContactEvent.objects.create(client=company, phone_token='p1', phone_token_kid='k1', source_system=system, source_record_id=record,
                                       source_grade='B', channel='call', direction='outbound', occurred_at=at, length_seconds=60,
                                       epoch=epoch_for(company.pk, 'p1', at))


def run(company):
    ai.use(reviewer)
    speech.use(transcriber)
    return review_due(company)


def test_customer_stop_goes_on_the_stop_list_at_that_second(company):
    c = call(company, [{'who': 'business', 'text': 'Hi, this is Sam', 'at': 1.0},
                       {'who': 'customer', 'text': "Don't call me again", 'at': 42.5}])
    assert run(company) == 1
    review = ConversationReview.objects.get()
    assert (review.channel, review.result, review.moment_seconds) == ('call', 'opted_out', 42.5)
    assert review.moment_at == c.occurred_at + timedelta(seconds=42.5)
    stop = OptOutEvent.objects.get()
    assert (stop.channel, stop.method, stop.at) == ('call', 'ai', review.moment_at)


def test_agent_saying_stop_is_not_an_opt_out(company):
    call(company, [{'who': 'business', 'text': 'stop', 'at': 3.0}, {'who': 'customer', 'text': 'ok thanks', 'at': 5.0}])
    run(company)
    assert ConversationReview.objects.get().result == 'unclear' and not OptOutEvent.objects.exists()


def test_every_call_is_listened_to_even_short_ones(company):
    short = call(company, [{'who': 'customer', 'text': 'stop', 'at': 2.0}])
    short.length_seconds = 4
    short.save()
    run(company)
    assert ConversationReview.objects.get().result == 'opted_out'


def test_no_recording_is_not_reviewed(company, monkeypatch):
    monkeypatch.setitem(readers.RECORDINGS, 'vicidial', no_recording)
    call(company, [])
    run(company)
    review = ConversationReview.objects.get()
    assert (review.result, review.note) == ('not_reviewed', 'No recording')


def test_tool_without_a_recording_reader_is_not_reviewed(company):
    Connection.objects.create(client=company, provider='five9', status=Status.CONNECTED)
    call(company, [], system='five9')
    run(company)
    assert ConversationReview.objects.get().result == 'not_reviewed'


def test_slots_off_means_nothing_is_fetched_or_saved(company, monkeypatch):
    fetched = []
    monkeypatch.setitem(readers.RECORDINGS, 'vicidial', lambda connection, record_id: fetched.append(record_id) or b'')
    call(company, [{'who': 'customer', 'text': 'stop', 'at': 1.0}])
    assert review_due(company) == 0  # no AI
    ai.use(reviewer)
    review_due(company)  # AI but no speech-to-text
    assert not fetched and not ConversationReview.objects.exists()


def test_a_call_still_going_waits_and_each_call_is_read_once(company):
    call(company, [{'who': 'customer', 'text': 'stop', 'at': 1.0}], minutes_ago=2)
    assert run(company) == 0
    call(company, [{'who': 'customer', 'text': 'hello', 'at': 1.0}])
    assert run(company) == 1 and run(company) == 0


def test_only_the_result_and_a_fingerprint_are_kept(company):
    call(company, [{'who': 'customer', 'text': "Don't call me again", 'at': 9.0}])
    run(company)
    review = ConversationReview.objects.get()
    kept = ' '.join(str(v) for v in review.__dict__.values())
    assert 'call me again' not in kept.lower() and len(review.thread_sha256) == 64


def test_spoken_consent_is_flagged_for_a_person_to_confirm(company):
    """Module 16: the same AI answer marks where the customer said yes; only the customer's words count."""
    c = call(company, [{'who': 'business', 'text': 'May we call you about solar?', 'at': 3.0},
                       {'who': 'customer', 'text': 'Yes, you can call me', 'at': 7.0}])

    def agreeing(turns):
        return 'none', None, 0.95, {'consent': 1}
    agreeing.model = 'pretend-ai'
    ai.use(agreeing)
    speech.use(transcriber)
    review_due(company)
    review = ConversationReview.objects.get()
    assert review.consent_check == 'waiting' and review.consent_at == c.occurred_at + timedelta(seconds=7.0)


def test_an_agent_saying_yes_is_not_consent(company):
    call(company, [{'who': 'business', 'text': 'Yes, we can call you', 'at': 3.0}])

    def wrong(turns):
        return 'none', None, 0.95, {'consent': 0}
    wrong.model = 'pretend-ai'
    ai.use(wrong)
    speech.use(transcriber)
    review_due(company)
    assert ConversationReview.objects.get().consent_check == ''
