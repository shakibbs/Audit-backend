"""Module 9 step 4: the AI's exam. Pass = every stop caught and 98 % right; until then AI stops stay on the STOP list
but don't count against the client, and "allowed again" / new owners wait for CiV staff; a reported mistake fails it."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.consent.needs import opt_out_in_force
from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.conversations import ai, exam, readers
from apps.conversations.models import ConversationReview, ExamCase, ExamRun
from apps.conversations.review import approve, report_wrong, review_due
from apps.conversations.tasks import run_exams
from apps.optouts.models import OptOutEvent
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.rulebook.lookup import RuleSet

pytestmark = pytest.mark.django_db
NOW = timezone.now()
WORDS = {}


class Perfect:
    """A pretend AI that knows every exam answer (it peeks at the case by its words)."""
    model = 'pretend-ai'

    def __init__(self, miss=0, wrong=0):
        self.answers = {}
        for channel in ('text', 'call'):
            for case in exam.cases(channel):
                self.answers[repr(case['turns'])] = (case['expected'], case.get('moment'))
        self.miss, self.wrong = miss, wrong

    def __call__(self, turns):
        expected, moment = self.answers.get(repr(turns), (None, None))
        if expected is None:  # a live conversation: decide from the last customer words
            last = max(i for i, t in enumerate(turns) if t['who'] == 'customer')
            words = turns[last]['text'].lower()
            if 'wrong number' in words:
                return 'wrong_number', last, 0.97
            if 'text me again' in words:
                return 'opted_back_in', last, 0.97
            return ('opted_out', last, 0.97) if 'stop' in words or "don't text" in words else ('none', None, 0.95)
        if expected in exam.STOPS and self.miss:
            self.miss -= 1
            return 'none', None, 0.95
        if expected == 'none' and self.wrong:
            self.wrong -= 1
            return 'partial_request', len(turns) - 1, 0.95
        return expected, moment, 0.97


@pytest.fixture(autouse=True)
def setup(company, monkeypatch):
    load(RULEBOOK_DIR / 'v3.0.yaml')
    WORDS.clear()
    Connection.objects.create(client=company, provider='twilio', status=Status.CONNECTED)
    monkeypatch.setitem(readers.READERS, 'twilio', lambda connection, sid: WORDS[sid])
    yield
    ai.use(None)


n = iter(range(10**6))


def text(company, words, inbound=True, minutes_ago=30):
    sid = f'SM{next(n)}'
    WORDS[sid] = words
    at = NOW - timedelta(minutes=minutes_ago)
    return ContactEvent.objects.create(client=company, phone_token='p1', phone_token_kid='k1', source_system='twilio', source_record_id=sid,
                                       source_grade='C', channel='text', direction='inbound' if inbound else 'outbound', occurred_at=at,
                                       epoch=epoch_for(company.pk, 'p1', at))


def test_the_exam_has_enough_questions_with_tricky_ones():
    for channel in ('text', 'call'):
        cases = exam.cases(channel)
        assert len(cases) >= exam.MIN_CASES
        assert {c['expected'] for c in cases} == {'opted_out', 'wrong_number', 'opted_back_in', 'partial_request', 'none'}
        assert any(c['expected'] == 'none' and any(t['who'] == 'business' and 'stop' in t['text'].lower() for t in c['turns']) for c in cases)
        assert all(c['turns'][c['moment']]['who'] == 'customer' for c in cases if c.get('moment') is not None)


def test_all_right_passes():
    run = exam.run('text', Perfect())
    assert run.passed and run.stops_caught == run.stops and run.right == run.cases == 300


def test_missing_one_stop_fails():
    run = exam.run('text', Perfect(miss=1))
    assert not run.passed and run.stops_caught == run.stops - 1 and run.mistakes[0]['got'] == 'none'


def test_below_98_percent_fails_even_with_every_stop():
    assert exam.run('call', Perfect(wrong=5)).passed  # 295 / 300 = 98.3 %
    assert not exam.run('call', Perfect(wrong=7)).passed  # 293 / 300 = 97.7 %


def test_staff_questions_join_the_exam():
    ExamCase.objects.create(channel='text', turns=[{'who': 'customer', 'text': 'stop it with these'}], expected='opted_out', moment=0)
    run = exam.run('text', Perfect())  # Perfect() was built after the case was added
    assert run.cases == 301


def test_before_passing_stops_go_on_the_list_but_do_not_count(company):
    ai.use(Perfect())
    text(company, 'Your quote', inbound=False, minutes_ago=60)
    text(company, 'stop texting me')
    review_due(company)
    stop = OptOutEvent.objects.get()
    assert not ConversationReview.objects.get().trusted and stop.counts is False
    later = text(company, 'One more offer', inbound=False, minutes_ago=5)
    assert opt_out_in_force(later, RuleSet(), 'strict') is None  # not counted against the client


def test_after_passing_stops_count(company):
    exam.run('text', Perfect())
    ai.use(Perfect())
    text(company, 'stop texting me')
    review_due(company)
    assert ConversationReview.objects.get().trusted and OptOutEvent.objects.get().counts is True


def test_allowed_again_waits_for_staff_before_passing(company):
    old = OptOutEvent.objects.create(client=company, phone_token='p1', at=NOW - timedelta(days=5), channel='text', method='keyword',
                                     source_system='twilio', source_record_id='SM-old')
    ai.use(Perfect())
    back = text(company, 'ok you can text me again')
    review_due(company)
    review = ConversationReview.objects.get()
    old.refresh_from_db()
    assert review.approval == 'waiting' and old.lifted_at is None
    approve(review, 'staff@civ', True)
    old.refresh_from_db()
    assert old.lifted_at == back.occurred_at and ConversationReview.objects.get().approval == 'approved'


def test_wrong_number_new_owner_waits_but_the_stop_is_added(company):
    ai.use(Perfect())
    text(company, "wrong number, I'm not Sarah")
    review_due(company)
    review = ConversationReview.objects.get()
    assert review.approval == 'waiting' and OptOutEvent.objects.get().counts is False
    assert not PhoneEpoch.objects.filter(phone_token='p1', reason='wrong_number').exists()
    approve(review, 'staff@civ', True)
    assert PhoneEpoch.objects.filter(phone_token='p1', reason='wrong_number').exists() and OptOutEvent.objects.get().counts is True


def test_a_reported_mistake_fails_the_ai_at_once(company):
    exam.run('text', Perfect())
    ai.use(Perfect())
    text(company, 'stop texting me')
    review_due(company)
    assert exam.trusted('text', ai.active())
    report_wrong(ConversationReview.objects.get(), 'staff@civ')
    assert not exam.trusted('text', ai.active())
    stop = OptOutEvent.objects.get()
    assert stop.counts is False and stop.lifted_at is None  # stays on the STOP list, no longer counted


def test_exam_runs_when_due_and_not_without_an_ai():
    assert run_exams() == 0 and not ExamRun.objects.exists()
    ai.use(Perfect())
    assert run_exams() == 1  # texts only: no speech-to-text chosen yet
    assert run_exams() == 0  # not again until something changes or 30 days pass
    ExamRun.objects.update(ran_at=NOW - timedelta(days=31))
    assert run_exams() == 1


def test_staff_pages_read_approve_and_log(company, client):
    from apps.access_log.models import AccessEntry
    from apps.staff.models import StaffUser
    ai.use(Perfect())
    text(company, 'ok you can text me again')
    review_due(company)
    exam.run('text', Perfect(miss=1))
    review = ConversationReview.objects.get()
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password='a-long-test-password-1'))
    assert 'AI failed the exam' in client.get('/civ-admin/conversations/examrun/').content.decode()
    assert 'Waiting' in client.get('/civ-admin/conversations/conversationreview/').content.decode()
    page = client.get(f'/civ-admin/conversations/conversationreview/{review.pk}/read/')
    assert 'ok you can text me again' in page.content.decode() and 'no-store' in page['Cache-Control']
    client.post('/civ-admin/conversations/conversationreview/', {'action': 'approve', '_selected_action': [review.pk]})
    assert ConversationReview.objects.get().approval == 'approved'
    assert set(AccessEntry.objects.values_list('action', flat=True)) >= {'conversation_read', 'ai_answer_approved'}


def test_client_page_shows_the_ai_tile(company, client):
    from apps.staff.models import StaffUser
    ai.use(Perfect())
    text(company, 'stop texting me')
    review_due(company)
    client.force_login(StaffUser.objects.create_superuser(email='team@complyiv.com', name='Team', password='a-long-test-password-1'))
    page = client.get(f'/civ-admin/clients/client/{company.pk}/change/').content.decode()
    assert 'AI review' in page and '1 stop' in page and 'texts: exam not passed' in page
    assert f'conversationreview/?client__id__exact={company.pk}' in page
