"""Fingerprint record: hash of the exact bytes, no content kept, and a failed job leaves nothing half-done."""
import hashlib

import pytest

from apps.ledger.models import ContentKind, Fingerprint, PurgeLog, SourceGrade
from apps.ledger.record import ledger_job

MESSAGE = b'{"sid":"SM8a71","to":"+19165554471","body":"Hi Sarah, your solar quote is ready"}'


def twilio_text(job, raw=MESSAGE, record_id='SM8a71'):
    return job.record(source_system='twilio', source_record_id=record_id, raw=raw,
                      content_kind=ContentKind.TEXT, source_grade=SourceGrade.C)


@pytest.mark.django_db
def test_fingerprint_is_the_hash_of_the_exact_bytes(company):
    with ledger_job(company, 'twilio sync') as job:
        row = twilio_text(job)
    assert row.sha256 == hashlib.sha256(MESSAGE).hexdigest()
    assert row.client == company and row.job_id == job.id and row.fetched_at is not None


@pytest.mark.django_db
def test_same_record_same_fingerprint_one_letter_changed_different(company):
    with ledger_job(company, 'twilio sync') as job:
        a, b = twilio_text(job), twilio_text(job)
        c = twilio_text(job, raw=MESSAGE.replace(b'Sarah', b'Sara'))
    assert a.sha256 == b.sha256 != c.sha256


@pytest.mark.django_db
def test_raw_bytes_only(company):
    with pytest.raises(TypeError), ledger_job(company, 'twilio sync') as job:
        twilio_text(job, raw=MESSAGE.decode())
    assert PurgeLog.objects.filter(reason='TypeError').exists()


@pytest.mark.django_db
def test_no_record_content_is_kept(company):
    with ledger_job(company, 'twilio sync') as job:
        twilio_text(job)
    saved = ' '.join(str(v) for v in Fingerprint.objects.values().first().values())
    for piece in ['9165554471', 'Sarah', 'solar quote']:
        assert piece not in saved


@pytest.mark.django_db
def test_failed_job_leaves_no_rows_and_one_purge_line(company):
    with ledger_job(company, 'twilio sync') as good:
        twilio_text(good)
    with pytest.raises(TimeoutError), ledger_job(company, 'twilio sync') as bad:
        for n in range(5):
            twilio_text(bad, record_id=f'SM{n}')
        raise TimeoutError('Twilio did not answer for +19165554471')
    assert Fingerprint.objects.filter(job_id=bad.id).count() == 0
    assert Fingerprint.objects.filter(job_id=good.id).count() == 1  # other jobs untouched
    purge = PurgeLog.objects.get(job_id=bad.id)
    assert purge.rows_removed == 5 and purge.reason == 'TimeoutError' and purge.job_name == 'twilio sync'
    assert '9165554471' not in purge.reason  # the error's message is never kept
