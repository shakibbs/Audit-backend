"""Module 16: the document AI slot. Off: nothing sent, documents wait. On: each document read once per instructions,
kept with the AI's name; applied only after the AI passed its exam for that kind and was sure; contract clauses feed
M07 and the insurer sheet; a written policy fills "Written policy"; spoken consent is only a flag to confirm."""
import json
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.docai import ai, exam
from apps.docai.models import DocExamRun, DocReading
from apps.docai.read import apply_trusted, queue, read_waiting
from apps.rulebook.loader import RULEBOOK_DIR, load
from apps.uploads.models import Source, UploadedFile
from apps.vendors.models import VendorContract

pytestmark = pytest.mark.django_db
FOUND = {'consent': True, 'certificate': True, 'proof_on_request': True, 'optouts_passed': True, 'indemnity': True}


class Pretend:
    """A pretend AI: answers the exam from its examples, and a fixed answer for anything else."""
    model = 'pretend-doc-ai'

    def __init__(self, sure=0.97):
        self.calls, self.sure = [], sure
        self.known = {json.dumps(c['document'], sort_keys=True): c['expected'] for f in ai.PROMPT_VERSIONS for c in exam.cases(f)}

    def __call__(self, feature, document, questions):
        self.calls.append(feature)
        key = json.dumps({'text': document['text']}, sort_keys=True) if 'text' in document else None
        if key in self.known:
            want = self.known[key]
            if feature == 'contract_clauses':
                return {'answers': {**want, 'clauses': {k: {'found': v, 'quote': ''} for k, v in want['clauses'].items()}}, 'confidence': self.sure}
            return {'answers': want, 'confidence': self.sure}
        if feature == 'contract_clauses':
            return {'answers': {'clauses': {k: {'found': v, 'quote': '...'} for k, v in FOUND.items()}, 'ends_on': '2027-01-31', 'dispute_days': 7}, 'confidence': self.sure}
        if feature == 'policy_file':
            return {'answers': {'kind': 'tcpa_policy', 'dated': '2026-03-01', 'people_trained': None}, 'confidence': self.sure}
        return {'answers': {}, 'confidence': self.sure}


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    load(RULEBOOK_DIR / 'v3.0.yaml')
    yield
    ai.use(None)


def contract(company) -> VendorContract:
    return VendorContract.objects.create(client=company, key='leadco', name='LeadCo', file=SimpleUploadedFile('leadco.pdf', b'%PDF contract'),
                                         original_name='leadco.pdf', sha256='a' * 64, uploaded_by='Dana')


def policy(company) -> UploadedFile:
    return UploadedFile.objects.create(client=company, source=Source.POLICIES, file=SimpleUploadedFile('policy.pdf', b'%PDF policy'),
                                       original_name='policy.pdf', sha256='b' * 64)


def passed(feature, reader):
    DocExamRun.objects.create(feature=feature, model=reader.model, prompt_version=ai.PROMPT_VERSIONS[feature], cases=60, right=60, passed=True)


def test_off_means_nothing_is_sent(company):
    contract(company)
    assert queue(company) == 1 and queue(company) == 0  # queued once
    assert read_waiting() == 0 and DocReading.objects.get().status == 'waiting'


def test_read_once_and_applied_only_after_the_exam(company):
    c = contract(company)
    queue(company)
    reader = Pretend()
    ai.use(reader)
    read_waiting()
    r = DocReading.objects.get()
    assert (r.status, r.model, r.applied) == ('done', 'pretend-doc-ai', False) and 'not passed its exam' in r.note
    c.refresh_from_db()
    assert c.clauses == {}  # not trusted yet: nothing written
    passed('contract_clauses', reader)
    assert apply_trusted('contract_clauses', reader) == 1
    c.refresh_from_db()
    assert c.clauses['indemnity'] and c.ends_on == date(2027, 1, 31) and c.dispute_days == 7
    queue(company)
    assert read_waiting() == 0 and reader.calls == ['contract_clauses']  # the same file is not read (or paid for) twice


def test_not_sure_is_kept_not_applied(company):
    c = contract(company)
    reader = Pretend(sure=0.6)
    passed('contract_clauses', reader)
    ai.use(reader)
    queue(company)
    read_waiting()
    assert DocReading.objects.get().status == 'unclear'
    c.refresh_from_db()
    assert c.clauses == {}


def test_trusted_answers_reach_the_insurer_sheet(company):
    from apps.buyers.attestation import build
    contract(company)
    policy(company)
    reader = Pretend()
    for f in ('contract_clauses', 'policy_file'):
        passed(f, reader)
    ai.use(reader)
    queue(company)
    read_waiting()
    sheet = build(company, date(2026, 10, 1))
    assert sheet['controls']['policy'] is True and sheet['frequencyDrivers']['vendorTermsShare']['value'] == 1.0


def test_the_exam_needs_enough_examples(company):
    reader = Pretend()
    run = exam.run('contract_clauses', reader)
    assert run.right == run.cases == len(exam.cases('contract_clauses')) and not run.passed  # all right, but too few examples yet
    wrong = exam.run('consent_page', lambda f, d, q: {'answers': {}, 'confidence': 1.0})
    assert wrong.right == 0


def test_spoken_consent_is_only_a_flag(company):
    from apps.conversations.review import consent_flag
    assert consent_flag(None) == {}
    assert consent_flag('2026-10-22T10:00')['consent_check'] == 'waiting'
