"""Daily seal: one root per client per day, every fingerprint checkable alone, any change detected. No network in tests."""
import datetime
import hashlib
from pathlib import Path

import pytest
from django.utils import timezone

from apps.anchoring import stamps
from apps.anchoring.merkle import build, fold
from apps.anchoring.models import MerkleAnchor
from apps.anchoring.seal import seal_day, seal_finished_days, verify
from apps.anchoring.tasks import stamp_missing
from apps.ledger.models import ContentKind, Fingerprint, SourceGrade
from apps.ledger.record import ledger_job

YESTERDAY = timezone.now() - datetime.timedelta(days=1)
FIXTURE_ROOT = hashlib.sha256(b'civ fixture root').digest()
FREETSA_ANSWER = (Path(__file__).parent / 'freetsa_answer.der').read_bytes()  # a real answer, saved once


@pytest.fixture(autouse=True)
def stamps_answer(monkeypatch):
    monkeypatch.setattr(stamps, 'tsa_stamp', lambda root: ('https://tsa.test', b'signed', YESTERDAY))
    monkeypatch.setattr(stamps, 'ots_stamp', lambda root: ('https://ots.test', b'pending'))


def read(client, n, when=YESTERDAY):
    with ledger_job(client, 'twilio sync') as job:
        for i in range(n):
            job.record(source_system='twilio', source_record_id=f'SM{i}', raw=f'message {i}'.encode(),
                       content_kind=ContentKind.TEXT, source_grade=SourceGrade.C)
    Fingerprint.objects.filter(job_id=job.id).update(fetched_at=when)
    return job


@pytest.mark.parametrize('n', [1, 2, 3, 5, 8, 13])
def test_every_path_leads_to_the_root(n):
    leaves = [hashlib.sha256(bytes([i])).digest() for i in range(n)]
    root, paths = build(leaves)
    assert all(fold(leaf, path) == root for leaf, path in zip(leaves, paths))
    changed = leaves.copy()
    changed[n // 2] = hashlib.sha256(b'other').digest()
    assert build(changed)[0] != root


@pytest.mark.django_db
def test_nightly_seal_makes_one_stamped_root_per_client_per_day(company, other_company):
    read(company, 5)
    read(other_company, 3)
    read(company, 2, when=timezone.now())  # today: sealed tomorrow
    anchors = seal_finished_days()
    assert sorted(a.leaf_count for a in anchors) == [3, 5]
    mine = MerkleAnchor.objects.get(client=company)
    assert mine.tsa_url == 'https://tsa.test' and bytes(mine.tsa_response) == b'signed' and bytes(mine.ots_proof) == b'pending'
    assert Fingerprint.objects.filter(client=company, anchor__isnull=True).count() == 2
    assert seal_finished_days() == []  # nothing left to seal


@pytest.mark.django_db
def test_verify_matches_then_detects_any_change(company):
    read(company, 4)
    seal_day(company, YESTERDAY.date())
    fp = Fingerprint.objects.filter(client=company).first()
    assert verify(fp) == 'matches'
    Fingerprint.objects.filter(pk=fp.pk).update(sha256='0' * 64)
    assert verify(Fingerprint.objects.get(pk=fp.pk)) == 'changed'
    other = Fingerprint.objects.filter(client=company).exclude(pk=fp.pk).first()
    Fingerprint.objects.filter(pk=other.pk).update(fetched_at=YESTERDAY - datetime.timedelta(hours=2))
    assert verify(Fingerprint.objects.get(pk=other.pk)) == 'changed'  # the read time is sealed too


@pytest.mark.django_db
def test_today_is_not_sealed_yet(company):
    read(company, 1, when=timezone.now())
    assert verify(Fingerprint.objects.get(client=company)) == 'not_sealed'


@pytest.mark.django_db
def test_a_service_down_keeps_the_root_and_retries_later(company, monkeypatch):
    def down(root):
        raise stamps.StampFailed('down')
    monkeypatch.setattr(stamps, 'tsa_stamp', down)
    read(company, 2)
    anchor = seal_day(company, YESTERDAY.date())
    anchor.refresh_from_db()
    assert anchor.root and anchor.tsa_response is None and bytes(anchor.ots_proof) == b'pending'
    monkeypatch.setattr(stamps, 'tsa_stamp', lambda root: ('https://tsa.test', b'signed', YESTERDAY))
    stamp_missing()
    anchor.refresh_from_db()
    assert bytes(anchor.tsa_response) == b'signed'


def test_a_real_time_stamp_covers_only_its_root():
    assert stamps.tsa_covers(FREETSA_ANSWER, FIXTURE_ROOT)
    assert not stamps.tsa_covers(FREETSA_ANSWER, hashlib.sha256(b'another root').digest())
