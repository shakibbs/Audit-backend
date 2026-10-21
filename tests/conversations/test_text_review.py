"""Module 9 step 1: text conversations read by the AI slot (a pretend AI here), the same way for every tool; only the
result is kept; the STOP list, new owners and lifted opt-outs follow."""
from datetime import timedelta

import pytest
from django.db import connection as db
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.consent.needs import opt_out_in_force
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.conversations import ai, readers
from apps.conversations.models import ConversationReview, ExamRun
from apps.conversations.review import due, review_due
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import RuleSet

pytestmark = pytest.mark.django_db
NOW = timezone.now()
WORDS = {}  # pretend Twilio: message ID → words


class Pretend:
    """A pretend AI: decides from the customer's last message."""
    model = 'pretend-ai'

    def __init__(self, confidence=0.97):
        self.confidence, self.seen = confidence, []

    def __call__(self, thread):
        self.seen.append(thread)
        last = max(i for i, m in enumerate(thread) if m['who'] == 'customer')
        text = thread[last]['text'].lower()
        if 'grab a pen' in text:
            return 'none', None, 0.99
        if "don't text" in text or 'stop texting' in text:
            return 'opted_out', last, self.confidence
        if 'wrong number' in text:
            return 'wrong_number', last, self.confidence
        if 'text me again' in text:
            return 'opted_back_in', last, self.confidence
        if 'after 6' in text:
            return 'partial_request', last, self.confidence
        return 'none', None, 0.95


@pytest.fixture(autouse=True)
def setup(company, monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    WORDS.clear()
    Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    monkeypatch.setitem(readers.READERS, 'twilio', lambda connection, sid: WORDS[sid])
    yield
    ai.use(None)


n = iter(range(10**6))


def text(company, words, inbound=True, minutes_ago=30, token='p1'):
    sid = f'SM{next(n)}'
    WORDS[sid] = words
    at = NOW - timedelta(minutes=minutes_ago)
    return ContactEvent.objects.create(client=company, phone_token=token, phone_token_kid='k1', source_system='twilio', source_record_id=sid,
                                       source_grade='C', channel='text', direction='inbound' if inbound else 'outbound', occurred_at=at,
                                       epoch=epoch_for(company.pk, token, at))


def run(company, reviewer=None):
    ai.use(reviewer or Pretend())
    return review_due(company)


def test_no_ai_chosen_means_nothing_is_sent_and_nothing_saved(company):
    text(company, "please don't text me anymore")
    assert review_due(company) == 0 and not ConversationReview.objects.exists()


def test_plain_words_go_on_the_stop_list(company):
    text(company, 'Your solar quote is ready', inbound=False, minutes_ago=40)
    asked = text(company, "please don't text me anymore")
    pretend = Pretend()
    assert run(company, pretend) == 1
    assert pretend.seen[0] == [{'who': 'business', 'text': 'Your solar quote is ready'}, {'who': 'customer', 'text': "please don't text me anymore"}]
    review = ConversationReview.objects.get()
    assert (review.result, review.moment_id, review.messages_read, review.model) == ('opted_out', asked.pk, 2, 'pretend-ai')
    stop = OptOutEvent.objects.get()
    assert (stop.method, stop.at, stop.source_system) == ('ai', asked.occurred_at, 'ai_conversation')


def test_stop_let_me_grab_a_pen_is_not_an_opt_out(company):
    text(company, 'stop, let me grab a pen')
    run(company)
    assert ConversationReview.objects.get().result == 'none' and not OptOutEvent.objects.exists()


def passed_exam():
    ExamRun.objects.create(channel='text', model='pretend-ai', prompt_version=ai.PROMPT_VERSION, cases=300, right=300, passed=True)


def test_wrong_number_stops_and_starts_a_new_owner(company):
    passed_exam()
    text(company, "wrong number, I'm not Sarah")
    run(company)
    assert OptOutEvent.objects.get().keyword == 'wrong number'
    assert PhoneEpoch.objects.filter(phone_token='p1', reason='wrong_number').exists()


def test_allowed_again_lifts_the_earlier_opt_out(company):
    OptOutEvent.objects.create(client=company, phone_token='p1', at=NOW - timedelta(days=5), channel='text', method='keyword',
                               source_system='twilio', source_record_id='SM-old')
    passed_exam()
    back = text(company, 'ok you can text me again')
    run(company)
    assert OptOutEvent.objects.get().lifted_at == back.occurred_at
    later = text(company, 'Great, here is your quote', inbound=False, minutes_ago=5)
    assert opt_out_in_force(later, RuleSet(), 'strict') is None


def test_a_limit_is_kept_for_review_not_a_stop(company):
    text(company, 'only text me after 6pm please')
    run(company)
    assert ConversationReview.objects.get().result == 'partial_request' and not OptOutEvent.objects.exists()


def test_not_sure_of_a_stop_is_treated_as_a_stop(company):
    text(company, "please don't text me anymore")
    run(company, Pretend(confidence=0.7))
    assert ConversationReview.objects.get().result == 'opted_out' and OptOutEvent.objects.exists()


def test_not_sure_of_a_limit_is_unclear(company):
    text(company, 'only text me after 6pm please')
    run(company, Pretend(confidence=0.7))
    assert ConversationReview.objects.get().result == 'unclear' and not OptOutEvent.objects.exists()


def test_only_quiet_threads_where_the_customer_spoke_and_once(company):
    text(company, 'Your quote', inbound=False, token='p2')  # the customer never replied
    text(company, "please don't text me", minutes_ago=3, token='p3')  # still talking
    assert due(company) == []
    text(company, 'hello?', token='p1')
    assert run(company) == 1 and run(company) == 0  # read once
    text(company, 'stop texting me', minutes_ago=15)  # new message: read again
    assert run(company) == 1 and ConversationReview.objects.filter(result='opted_out').count() == 1


def test_a_tool_that_cannot_share_words_is_not_reviewed(company, monkeypatch):
    monkeypatch.delitem(readers.READERS, 'twilio')
    text(company, "please don't text me")
    run(company)
    review = ConversationReview.objects.get()
    assert review.result == 'not_reviewed' and "can't share" in review.note


def test_the_words_are_never_kept(company):
    text(company, "please don't text me anymore, my name is Sarah")
    run(company)
    with db.cursor() as cur:
        for table in ('conversation_review', 'opt_out_event', 'contact_event'):
            cur.execute(f'SELECT * FROM {table}')
            assert 'Sarah' not in repr(cur.fetchall())
    assert len(ConversationReview.objects.get().thread_sha256) == 64
