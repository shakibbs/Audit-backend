"""Claiming and reading one certificate at TrustedForm or Jornaya with the client's own key.

TrustedForm: built from its public API docs (Retain + Insights, api-version 4.0, POST https://cert.trustedform.com/<id>,
Basic auth "API" + key). Jornaya: its API docs are shared with customers only; the request below follows what is
public about LeadiD lookups and is MARKED TO CONFIRM on a real account. Answers are read loosely for both.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

TIMEOUT_SECONDS = 20
TRUSTEDFORM = 'https://cert.trustedform.com'
JORNAYA = 'https://api.leadid.com/SingleQuery'  # to confirm


class NotFound(Exception):
    """The certificate does not exist any more (expired) or never did."""


class Refused(Exception):
    """The vendor refused the key."""


@dataclass
class Facts:
    raw: bytes  # the vendor's answer, fingerprinted then dropped
    created_at: datetime | None
    expires_at: datetime | None
    page_url: str
    phone_match: bool | None = None  # was this phone typed into the form? None = not asked or no answer


def _found(data: dict, *paths: str):
    """Like _first, but False counts as an answer."""
    for path in paths:
        node = data
        for part in path.split('.'):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            return node
    return None


def lead_phone(number: str) -> str:
    """The phone as TrustedForm's lead matching takes it: digits, no leading +1 for US numbers (to confirm)."""
    digits = ''.join(ch for ch in number if ch.isdigit())
    return digits[1:] if len(digits) == 11 and digits.startswith('1') else digits


def phone_answer(data: dict) -> bool | None:
    value = _found(data, 'match_lead.result.phone_match', 'match_lead.phone_match', 'match_lead.result.phone', 'phone_match')
    return value if isinstance(value, bool) else None


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _first(data: dict, *paths: str):
    for path in paths:
        node = data
        for part in path.split('.'):
            node = node.get(part) if isinstance(node, dict) else None
        if node:
            return node
    return None


def _vendor_error(data) -> None:
    """Some vendors answer "OK" with the problem written inside, e.g. Jornaya's {"error": {"code": 2001,
    "message": "Malformed account code"}} (QA 2026-10-23). Such an answer is never a success: "not found" in it is
    NotFound, anything else is a refused key."""
    if not isinstance(data, dict):
        return
    problem = data.get('error') or data.get('errors')
    if not problem:
        return
    text = json.dumps(problem).lower()
    if 'not found' in text or 'not_found' in text:
        raise NotFound(text[:200])
    raise Refused(text[:200])


def _send(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            return reply.read()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise Refused(f'HTTP {error.code}') from None
        if error.code in (404, 410):
            raise NotFound(f'HTTP {error.code}') from None
        raise  # 5xx and others: try again later


def claim_trustedform(cert_id: str, key: str, reference: str, phone: str | None = None) -> Facts:
    """Claims (retains) the certificate; with a phone, TrustedForm also says whether it was typed into the form. The
    phone goes only into this request: it is never stored (lead matching, built from the docs, to confirm)."""
    request = {'retain': {'reference': reference}, 'insights': {'properties': ['created_at', 'expires_at', 'page_url']}}
    if phone:
        request['match_lead'] = {'phone': lead_phone(phone)}
    body = json.dumps(request).encode()
    auth = base64.b64encode(f'API:{key}'.encode()).decode()
    raw = _send(urllib.request.Request(f'{TRUSTEDFORM}/{cert_id}', data=body, method='POST', headers={
        'Authorization': f'Basic {auth}', 'Content-Type': 'application/json', 'Accept': 'application/json', 'api-version': '4.0'}))
    data = json.loads(raw)
    _vendor_error(data)
    if str(data.get('outcome', 'success')).lower() == 'failure' and 'not found' in json.dumps(data).lower():
        raise NotFound('certificate not found')
    return Facts(raw=raw,
                 created_at=_when(_first(data, 'insights.properties.created_at', 'created_at', 'cert.created_at')),
                 expires_at=_when(_first(data, 'retain.results.expires_at', 'expires_at', 'cert.expires_at')),
                 page_url=str(_first(data, 'insights.properties.page_url', 'page_url', 'cert.page_url') or ''),
                 phone_match=phone_answer(data) if phone else None)


def match_trustedform(cert_id: str, key: str, phone: str) -> bool | None:
    """An already claimed certificate seen with another phone: lead matching only (to confirm on a real account)."""
    auth = base64.b64encode(f'API:{key}'.encode()).decode()
    raw = _send(urllib.request.Request(f'{TRUSTEDFORM}/{cert_id}', data=json.dumps({'match_lead': {'phone': lead_phone(phone)}}).encode(),
                                       method='POST', headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/json',
                                                               'Accept': 'application/json', 'api-version': '4.0'}))
    return phone_answer(json.loads(raw))


def read_jornaya(token: str, account_code: str, key: str) -> Facts:
    query = urllib.parse.urlencode({'lac': account_code, 'lak': key, 'id': token})
    raw = _send(urllib.request.Request(f'{JORNAYA}?{query}', headers={'Accept': 'application/json'}))
    data = json.loads(raw)
    _vendor_error(data)
    if not data or str(_first(data, 'authentic', 'found')).lower() in ('0', 'false', 'no'):
        raise NotFound('token not found')
    return Facts(raw=raw, created_at=_when(_first(data, 'creation_time', 'created', 'timestamp')),
                 expires_at=_when(_first(data, 'expires_at', 'expiration')), page_url=str(_first(data, 'url', 'page_url') or ''))


def host_and_path(url: str) -> str:
    """Only where the form was: no query string, which could carry the person's details."""
    parts = urllib.parse.urlsplit(url)
    return f'{parts.netloc}{parts.path}'[:300] if parts.netloc else ''
