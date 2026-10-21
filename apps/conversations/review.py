"""Reviewing text conversations (spec §8 AI conversation review), the same for every texting tool:
1. due: numbers where the customer wrote, and the thread has been quiet for conv_review_text_quiet_minutes (10), with a
   message newer than the last review;
2. read: the thread's last conv_review_thread_days (30) of texts, re-read by message ID from the tool, in memory only;
3. ask the AI slot; below 90 % sure → unclear;
4. act: asked to stop / wrong number → the STOP list (wrong number also starts a new owner); allowed contact again →
   ends the earlier opt-out; a limit → kept for the client to review; unclear / none → counted.
Calls (step 2): every recorded call, once it has ended. The recording is fetched from the dialer, turned into words by
the speech slot (customer and agent told apart), and the same AI request answers; the moment is the second in the call.
The recording and the words are dropped at once.
Only the result, the deciding message, the confidence, the AI and a fingerprint of the words are kept."""
import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.contacts.epochs import split
from apps.contacts.models import ContactEvent, PhoneEpoch
from apps.optouts.models import OptOutEvent

from apps.consent.keeping import queue

from . import ai, exam, speech
from .models import ConversationReview
from .readers import CannotRead, NoRecording, reader_for, recording_reader_for

QUIET = timedelta(minutes=10)
THREAD_DAYS = 30
R = ConversationReview.Result


def due(client, now=None) -> list[tuple[str, str]]:
    """(phone code, tool) pairs whose conversation is ready to read."""
    now = now or timezone.now()
    texts = ContactEvent.objects.filter(client=client, channel='text', is_primary=True, is_test=False)
    replied = texts.filter(direction='inbound', occurred_at__gte=now - timedelta(days=THREAD_DAYS)).values_list('phone_token', 'source_system').distinct()
    out = []
    for token, system in replied:
        last = texts.filter(phone_token=token, source_system=system).aggregate(m=Max('occurred_at'))['m']
        if last is None or last > now - QUIET:
            continue  # still talking
        if ConversationReview.objects.filter(client=client, channel='text', phone_token=token, thread_end_at__gte=last).exists():
            continue  # already read up to here
        out.append((token, system))
    return out


def thread_of(client, token: str, system: str, read, connection) -> tuple[list[dict], list]:
    since = timezone.now() - timedelta(days=THREAD_DAYS)
    messages = list(ContactEvent.objects.filter(client=client, channel='text', phone_token=token, source_system=system, is_primary=True,
                                                occurred_at__gte=since).order_by('occurred_at', 'pk'))
    thread = [{'who': 'customer' if m.direction == 'inbound' else 'business', 'text': read(connection, m.source_record_id)} for m in messages]
    return thread, messages


def act(client, review: ConversationReview) -> None:
    """Stops always go on the STOP list (counted only when the AI had passed its exam). Before it passes, the new owner
    after a wrong number and "allowed contact again" wait for CiV staff (approve())."""
    if review.result in (R.OPTED_OUT, R.WRONG_NUMBER) and review.moment_at:
        try:
            with transaction.atomic():
                OptOutEvent.objects.create(client=client, phone_token=review.phone_token, at=review.moment_at, channel=review.channel,
                                           method=OptOutEvent.Method.AI, keyword='wrong number' if review.result == R.WRONG_NUMBER else '',
                                           source_system='ai_conversation', source_record_id=f'review-{review.pk}', counts=review.trusted)
        except IntegrityError:
            pass
    if review.result in (R.WRONG_NUMBER, R.OPTED_BACK_IN) and review.moment_at:
        if review.trusted:
            carry_out(client, review)
        else:
            ConversationReview.objects.filter(pk=review.pk).update(approval='waiting')


def carry_out(client, review: ConversationReview) -> None:
    if review.result == R.WRONG_NUMBER:
        split(client.pk, review.phone_token, review.moment_at, PhoneEpoch.Reason.WRONG_NUMBER, source='ai_conversation')
    elif review.result == R.OPTED_BACK_IN:
        OptOutEvent.objects.filter(client=client, phone_token=review.phone_token, at__lt=review.moment_at, lifted_at__isnull=True) \
            .update(lifted_at=review.moment_at)


def approve(review: ConversationReview, by: str, yes: bool) -> None:
    """CiV staff decide a waiting answer. Approved: carried out, and a wrong-number stop now counts."""
    if review.approval != 'waiting':
        return
    ConversationReview.objects.filter(pk=review.pk).update(approval='approved' if yes else 'rejected', approved_by=by, approved_at=timezone.now())
    if yes:
        carry_out(review.client, review)
        recount(review, True)


def recount(review: ConversationReview, counts: bool) -> None:
    for event in OptOutEvent.objects.filter(client=review.client, source_system='ai_conversation', source_record_id=f'review-{review.pk}'):
        if event.counts != counts:
            OptOutEvent.objects.filter(pk=event.pk).update(counts=counts)
            queue(event.client_id, event.phone_token, event.at, 'late_opt_out')


def report_wrong(review: ConversationReview, by: str) -> None:
    """CiV staff found this answer wrong: the AI fails its exam at once; a wrong "allowed again" is undone, a wrong stop
    stays on the STOP list (safe side) but no longer counts against the client."""
    from . import exam
    ConversationReview.objects.filter(pk=review.pk).update(reported_wrong=True)
    if review.result == R.OPTED_BACK_IN and review.approval != 'waiting':
        OptOutEvent.objects.filter(client=review.client, phone_token=review.phone_token, lifted_at=review.moment_at).update(lifted_at=None)
        queue(review.client_id, review.phone_token, review.moment_at, 'late_opt_out')
    if review.result in (R.OPTED_OUT, R.WRONG_NUMBER):
        recount(review, False)
    if review.approval == 'waiting':
        ConversationReview.objects.filter(pk=review.pk).update(approval='rejected', approved_by=by, approved_at=timezone.now())
    reviewer = ai.active()
    if reviewer is not None and getattr(reviewer, 'model', None) == review.model:
        exam.fail_now(review.channel, reviewer, f'Real mistake reported by {by} (review {review.pk})')


def judge(thread: list[dict], reviewer) -> tuple[str, int | None, float | None, dict]:
    """Ask the AI. A stop, wrong number or "allowed again" not said by the customer (an agent saying "stop") is unclear.
    Not sure enough (below 90 %): a possible stop or wrong number is treated as a stop (the safe side, owner decision
    2026-10-21); anything else is unclear. Extra answers (4th value) are kept only when they point at the customer."""
    answer = reviewer(thread)
    result, index, confidence = answer[:3]
    extras = {k: v for k, v in (answer[3] if len(answer) > 3 and isinstance(answer[3], dict) else {}).items() if said_by_customer(thread, v)}
    if result not in ai.RESULTS:
        return R.UNCLEAR, index, confidence, extras
    if result in (R.OPTED_OUT, R.WRONG_NUMBER, R.OPTED_BACK_IN) and not said_by_customer(thread, index):
        return R.UNCLEAR, index, confidence, extras
    if confidence is not None and confidence < ai.MIN_CONFIDENCE and result != R.NONE:
        result = R.OPTED_OUT if result in (R.OPTED_OUT, R.WRONG_NUMBER) else R.UNCLEAR
    return result, index, confidence, extras


def said_by_customer(thread: list[dict], index) -> bool:
    return isinstance(index, int) and 0 <= index < len(thread) and thread[index].get('who') == 'customer'


def review_one(client, token: str, system: str, reviewer) -> ConversationReview | None:
    found = reader_for(client, system)
    last = ContactEvent.objects.filter(client=client, channel='text', phone_token=token, source_system=system, is_primary=True) \
        .order_by('-occurred_at', '-pk').first()
    base = {'client': client, 'phone_token': token, 'channel': 'text', 'source_system': system, 'thread_end': last,
            'thread_end_at': last.occurred_at}
    if found is None:
        return save({**base, 'result': R.NOT_REVIEWED, 'note': "This tool can't share message text"})
    try:
        thread, messages = thread_of(client, token, system, *found)
    except CannotRead as error:
        return save({**base, 'result': R.NOT_REVIEWED, 'note': f'The tool did not share a message ({error})'})
    words = json.dumps(thread, sort_keys=True).encode()
    result, index, confidence, extras = judge(thread, reviewer)
    del thread  # the words are dropped here; only their fingerprint stays
    moment = messages[index] if index is not None and 0 <= index < len(messages) else None
    attorney = messages[extras['attorney']].occurred_at if 'attorney' in extras else None
    review = save({**base, 'messages_read': len(messages), 'result': result, 'confidence': confidence, 'moment': moment,
                   'moment_at': moment.occurred_at if moment else None, 'model': getattr(reviewer, 'model', 'unknown'),
                   'prompt_version': ai.PROMPT_VERSION, 'thread_sha256': hashlib.sha256(words).hexdigest(),
                   'trusted': exam.trusted('text', reviewer), 'attorney_at': attorney})
    if review:
        act(client, review)
    return review


def save(fields: dict) -> ConversationReview | None:
    try:
        with transaction.atomic():
            return ConversationReview.objects.create(**fields)
    except IntegrityError:
        return None  # read by a parallel run


def calls_due(client, now=None):
    """Every call that has ended (quiet for QUIET) in the last THREAD_DAYS days and is not reviewed yet."""
    now = now or timezone.now()
    reviewed = ConversationReview.objects.filter(client=client, channel='call').values('thread_end')
    return (ContactEvent.objects.filter(client=client, channel='call', is_primary=True, is_test=False,
                                        occurred_at__gte=now - timedelta(days=THREAD_DAYS), occurred_at__lte=now - QUIET)
            .exclude(pk__in=reviewed).order_by('occurred_at'))


def review_call(client, call: ContactEvent, transcriber, reviewer) -> ConversationReview | None:
    base = {'client': client, 'phone_token': call.phone_token, 'channel': 'call', 'source_system': call.source_system,
            'thread_end': call, 'thread_end_at': call.occurred_at}
    found = recording_reader_for(client, call.source_system)
    if found is None:
        return save({**base, 'result': R.NOT_REVIEWED, 'note': "This tool can't share call recordings yet"})
    read, connection = found
    try:
        audio = read(connection, call.source_record_id)
    except NoRecording:
        return save({**base, 'result': R.NOT_REVIEWED, 'note': 'No recording'})
    except CannotRead as error:
        return save({**base, 'result': R.NOT_REVIEWED, 'note': f'The tool did not share the recording ({error})'})
    except Exception as error:
        return save({**base, 'result': R.NOT_REVIEWED, 'note': f'The recording could not be fetched ({type(error).__name__})'})
    turns = transcriber(audio)
    del audio  # the recording is dropped here
    words = json.dumps(turns, sort_keys=True).encode()
    result, index, confidence, extras = judge(turns, reviewer)
    at = turns[index].get('at') if index is not None and 0 <= index < len(turns) else None
    lawyer = turns[extras['attorney']].get('at') if 'attorney' in extras else None
    count = len(turns)
    del turns  # the words are dropped here; only their fingerprint stays
    review = save({**base, 'messages_read': count, 'result': result, 'confidence': confidence,
                   'moment_seconds': at, 'moment_at': call.occurred_at + timedelta(seconds=at) if at is not None else None,
                   'model': getattr(reviewer, 'model', 'unknown'), 'prompt_version': ai.PROMPT_VERSION,
                   'thread_sha256': hashlib.sha256(words).hexdigest(), 'trusted': exam.trusted('call', reviewer),
                   'attorney_at': call.occurred_at + timedelta(seconds=lawyer) if lawyer is not None else None})
    if review:
        act(client, review)
    return review


def review_due(client, limit: int = 200) -> int:
    reviewer = ai.active()
    if reviewer is None:
        return 0  # no AI chosen yet: nothing is sent anywhere, nothing is saved
    done = 0
    for token, system in due(client)[:limit]:
        done += review_one(client, token, system, reviewer) is not None
    transcriber = speech.active()
    if transcriber is None:
        return done  # no speech-to-text chosen yet: calls wait, nothing is fetched
    for call in calls_due(client)[:limit]:
        done += review_call(client, call, transcriber, reviewer) is not None
    return done
