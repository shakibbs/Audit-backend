"""The AI slot. Owner decision 2026-10-21: the AI is chosen later; until then the slot is off — nothing is sent anywhere
and nothing is charged. A reviewer gets the thread as [{who: customer|business, text}] and returns
(result, index of the deciding message or None, confidence 0–1). Calls use the same request (turns also carry "at",
seconds into the call). "One listen, one request, several answers": later questions (e.g. disclosures) are added to
this same request, never a second AI call: a reviewer may add a 4th value, extra answers as a dict, now
{"attorney": index of the customer turn that named a lawyer, or None} (M45) and, Module 16,
{"consent": index of the customer turn that gave spoken consent to be called or texted, or None}. Tests plug in a pretend reviewer."""
from django.conf import settings

PROMPT_VERSION = 'v1'
MIN_CONFIDENCE = 0.90  # conv_review_min_confidence: below this a possible stop counts as a stop, anything else "unclear"
RESULTS = ('opted_out', 'partial_request', 'wrong_number', 'opted_back_in', 'none')

_reviewer = None  # set by tests, or by the chosen AI's adapter


def use(reviewer) -> None:
    global _reviewer
    _reviewer = reviewer


def active():
    """The reviewer in use, or None while no AI is chosen: then nothing is sent anywhere. When the owner picks the AI,
    its adapter is plugged in here (read from CONVERSATION_REVIEW_MODEL and its key)."""
    return _reviewer
