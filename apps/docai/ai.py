"""Module 16: the document AI slot, shared by every reader (contracts, consent pages, policy and training files). Owner
decision 2026-10-22: the AI is plugged in next (tomorrow); until then the slot is off — nothing is sent anywhere and
documents wait. A reader is called as reader(feature, document, questions) where document is {'text': str} or
{'file': bytes, 'mime': str, 'name': str}, and returns {'answers': {...}, 'confidence': 0–1}. It has a `model` name.
Tests plug in a pretend reader."""
PROMPT_VERSIONS = {'contract_clauses': 'v1', 'consent_page': 'v1', 'policy_file': 'v1'}
MIN_CONFIDENCE = 0.90  # below this an answer is "unclear": kept, never applied

_reader = None


def use(reader) -> None:
    global _reader
    _reader = reader


def active():
    """The reader in use, or None while no AI is chosen."""
    return _reader
