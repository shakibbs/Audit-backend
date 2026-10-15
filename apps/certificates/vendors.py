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


def claim_trustedform(cert_id: str, key: str, reference: str) -> Facts:
    body = json.dumps({'retain': {'reference': reference}, 'insights': {'properties': ['created_at', 'expires_at', 'page_url']}}).encode()
    auth = base64.b64encode(f'API:{key}'.encode()).decode()
    raw = _send(urllib.request.Request(f'{TRUSTEDFORM}/{cert_id}', data=body, method='POST', headers={
        'Authorization': f'Basic {auth}', 'Content-Type': 'application/json', 'Accept': 'application/json', 'api-version': '4.0'}))
    data = json.loads(raw)
    if str(data.get('outcome', 'success')).lower() == 'failure' and 'not found' in json.dumps(data).lower():
        raise NotFound('certificate not found')
    return Facts(raw=raw,
                 created_at=_when(_first(data, 'insights.properties.created_at', 'created_at', 'cert.created_at')),
                 expires_at=_when(_first(data, 'retain.results.expires_at', 'expires_at', 'cert.expires_at')),
                 page_url=str(_first(data, 'insights.properties.page_url', 'page_url', 'cert.page_url') or ''))


def read_jornaya(token: str, account_code: str, key: str) -> Facts:
    query = urllib.parse.urlencode({'lac': account_code, 'lak': key, 'id': token})
    raw = _send(urllib.request.Request(f'{JORNAYA}?{query}', headers={'Accept': 'application/json'}))
    data = json.loads(raw)
    if not data or str(_first(data, 'authentic', 'found')).lower() in ('0', 'false', 'no'):
        raise NotFound('token not found')
    return Facts(raw=raw, created_at=_when(_first(data, 'creation_time', 'created', 'timestamp')),
                 expires_at=_when(_first(data, 'expires_at', 'expiration')), page_url=str(_first(data, 'url', 'page_url') or ''))


def host_and_path(url: str) -> str:
    """Only where the form was: no query string, which could carry the person's details."""
    parts = urllib.parse.urlsplit(url)
    return f'{parts.netloc}{parts.path}'[:300] if parts.netloc else ''
