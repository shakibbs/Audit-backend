"""Module 16: what each document reader reads, what it is asked, and where its answers go. Every feature lists its
documents (ref, SHA-256), loads one in memory, and applies trusted answers to the record."""
import mimetypes
from datetime import date

from apps.rulebook.lookup import RuleSet

CONSENT_CHECKS = {
    'names_seller': 'The consent words name the company that will call or text (one of seller_names)',
    'written_consent': 'The person agrees in writing to be contacted (a clear yes, not hidden in terms)',
    'autodialer_or_prerecorded': 'It says calls or texts may use an autodialer, prerecorded or AI voice',
    'not_a_condition': 'It says agreeing is not a condition of buying anything',
    'unchecked_box': 'Consent is given by a separate box that is not ticked in advance',
}
POLICY_KINDS = ('tcpa_policy', 'training_record', 'vendor_contract', 'other')


def _file(f) -> dict:
    f.open('rb')
    try:
        data = f.read()
    finally:
        f.close()
    return {'file': data, 'mime': mimetypes.guess_type(f.name)[0] or 'application/octet-stream', 'name': f.name.rsplit('/', 1)[-1]}


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class ContractClauses:
    """Lead vendor contracts (Module 12): which of the Rulebook's clauses are in it, its end date and dispute window."""
    name = 'contract_clauses'

    def sources(self, client):
        from apps.vendors.models import VendorContract
        for c in VendorContract.objects.filter(client=client, purged_at__isnull=True).exclude(file=''):
            yield f'vendor_contract:{c.pk}', c.sha256

    def load(self, ref: str) -> dict:
        from apps.vendors.models import VendorContract
        return _file(VendorContract.objects.get(pk=ref.split(':')[1]).file)

    def questions(self, client) -> dict:
        clauses = RuleSet().get('vendor_required_clauses', on=date.today()).value
        return {'clauses': [{'id': c['id'], 'name': c['name']} for c in clauses],
                'also': {'ends_on': 'The date the contract ends (YYYY-MM-DD), or null', 'dispute_days': 'Days allowed to return a bad lead, or null'},
                'answer_as': {'clauses': {'<id>': {'found': 'true/false', 'quote': 'the words, short'}}, 'ends_on': '...', 'dispute_days': '...'}}

    def apply(self, ref: str, answers: dict) -> None:
        from apps.vendors.models import VendorContract
        c = VendorContract.objects.get(pk=ref.split(':')[1])
        c.clauses = {k: bool((v or {}).get('found')) for k, v in (answers.get('clauses') or {}).items()}
        if c.ends_on is None and _day(answers.get('ends_on')):
            c.ends_on = _day(answers['ends_on'])  # what the client typed always wins
        if c.dispute_days is None and isinstance(answers.get('dispute_days'), int) and 0 <= answers['dispute_days'] <= 365:
            c.dispute_days = answers['dispute_days']
        c.save()


class ConsentPage:
    """The consent words on each captured page (Module 7): do they really give consent for this company?"""
    name = 'consent_page'

    def sources(self, client):
        from apps.captures.models import PageCapture
        seen = set()
        for cap in PageCapture.objects.filter(client=client, ok=True, purged_at__isnull=True).order_by('-captured_at'):
            if cap.page_id in seen or not (cap.consent_block or cap.text):
                continue
            seen.add(cap.page_id)
            yield f'page_capture:{cap.pk}', cap.consent_block_sha256 or cap.text_sha256

    def load(self, ref: str) -> dict:
        from apps.captures.models import PageCapture
        cap = PageCapture.objects.get(pk=ref.split(':')[1])
        return {'text': cap.consent_block or cap.text}

    def questions(self, client) -> dict:
        names = [n.strip() for n in [client.name, *(client.brand_names or '').splitlines()] if n.strip()]
        return {'seller_names': names, 'checks': CONSENT_CHECKS, 'answer_as': {k: 'true/false' for k in CONSENT_CHECKS}}

    def apply(self, ref: str, answers: dict) -> None:
        pass  # kept on the reading; the consent page card reads it


class PolicyFile:
    """Files uploaded under "Policies, training, contracts": a written TCPA policy, a training record, or else."""
    name = 'policy_file'

    def sources(self, client):
        from apps.uploads.models import Source, UploadedFile
        for u in UploadedFile.objects.filter(client=client, source=Source.POLICIES, purged_at__isnull=True).exclude(file=''):
            if not u.original_name.lower().endswith('.csv'):
                yield f'uploaded_file:{u.pk}', u.sha256

    def load(self, ref: str) -> dict:
        from apps.uploads.models import UploadedFile
        return _file(UploadedFile.objects.get(pk=ref.split(':')[1]).file)

    def questions(self, client) -> dict:
        return {'kind': list(POLICY_KINDS), 'dated': 'The date it was written or the training given (YYYY-MM-DD), or null',
                'people_trained': 'For a training record: how many people, or null',
                'answer_as': {'kind': 'one of kind', 'dated': '...', 'people_trained': '...'}}

    def apply(self, ref: str, answers: dict) -> None:
        pass  # kept on the reading; the attestation reads trusted ones


FEATURES = {f.name: f for f in (ContractClauses(), ConsentPage(), PolicyFile())}
