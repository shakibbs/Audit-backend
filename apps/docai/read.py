"""Module 16: queue every document each reader should read, then read the waiting ones with the AI slot. While the
slot is off nothing is sent and documents stay "waiting". A file already read with the same instructions is not read
again. Answers are applied to the record only when the AI passed its exam and is sure enough; the file is held in
memory only while it is read."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import ai, exam
from .features import FEATURES
from .models import DocReading

S = DocReading.Status


def queue(client) -> int:
    made = 0
    for name, feature in FEATURES.items():
        version = ai.PROMPT_VERSIONS[name]
        for ref, sha in feature.sources(client):
            try:
                with transaction.atomic():
                    _, new = DocReading.objects.get_or_create(client=client, feature=name, ref=ref, input_sha256=sha, prompt_version=version)
            except IntegrityError:
                new = False
            made += new
    return made


def read_one(reading: DocReading, reader) -> DocReading:
    feature = FEATURES[reading.feature]
    try:
        document = feature.load(reading.ref)
        reply = reader(reading.feature, document, feature.questions(reading.client)) or {}
    except Exception as error:
        reading.status, reading.note = S.FAILED, f'Could not be read ({type(error).__name__})'
    else:
        del document  # the file leaves memory here
        reading.answers, reading.confidence = reply.get('answers') or {}, reply.get('confidence')
        sure = reading.confidence is not None and reading.confidence >= ai.MIN_CONFIDENCE
        reading.status = S.DONE if sure else S.UNCLEAR
    reading.model, reading.read_at = getattr(reader, 'model', 'unknown'), timezone.now()
    reading.trusted = exam.trusted(reading.feature, reader)
    if reading.status == S.DONE and reading.trusted:
        feature.apply(reading.ref, reading.answers)
        reading.applied = True
    elif reading.status == S.DONE:
        reading.note = 'Read, not applied: the AI has not passed its exam for this yet'
    reading.save()
    return reading


def read_waiting(limit: int = 50) -> int:
    reader = ai.active()
    if reader is None:
        return 0  # no AI chosen: nothing is sent anywhere
    done = 0
    for reading in DocReading.objects.filter(status=S.WAITING).select_related('client').order_by('queued_at')[:limit]:
        read_one(reading, reader)
        done += 1
    return done


def apply_trusted(feature: str, reader) -> int:
    """After the AI passes its exam: apply the answers it gave earlier (sure ones only)."""
    n = 0
    for reading in DocReading.objects.filter(feature=feature, status=S.DONE, applied=False, model=getattr(reader, 'model', 'unknown'),
                                             prompt_version=ai.PROMPT_VERSIONS[feature]):
        FEATURES[feature].apply(reading.ref, reading.answers)
        reading.applied, reading.trusted = True, True
        reading.save(update_fields=['applied', 'trusted'])
        n += 1
    return n


def latest_answers(client, feature: str, trusted_only: bool = True) -> list[DocReading]:
    rows = DocReading.objects.filter(client=client, feature=feature, status=S.DONE)
    return list(rows.filter(applied=True) if trusted_only else rows)
