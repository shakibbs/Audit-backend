"""Module 15: sending a company's attestation sheet to an insurer's own pricing software ("rating engine"). One
adapter per kind of software; today one standard kind: the sheet as JSON over HTTPS with the key as a bearer token and
an HMAC-SHA256 signature of the body, so the insurer can check it came from CiV unchanged. The address must be a
public HTTPS address (no private or local networks, no redirects), so the server can never be pointed inside."""
import hashlib
import hmac
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

TIMEOUT = 15


def check_address(url: str) -> str | None:
    """None when the address is fine, else a short reason for the insurer."""
    parts = urlparse(url)
    if parts.scheme != 'https' or not parts.hostname:
        return 'Use an https:// address.'
    try:
        found = {a[4][0] for a in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return 'That address could not be found.'
    for address in found:
        ip = ipaddress.ip_address(address.split('%')[0])
        if not ip.is_global or ip.is_multicast:
            return 'That address is not on the public internet.'
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect is refused, so it cannot lead somewhere unchecked


def _post(url: str, body: bytes, headers: dict) -> tuple[int, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with opener.open(request, timeout=TIMEOUT) as reply:
            return reply.status, reply.read(300).decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read(300).decode(errors='replace')


class JsonPost:
    name = 'json_post'

    def send(self, url: str, key: str, sheet: dict) -> tuple[bool, int | None, str]:
        problem = check_address(url)
        if problem:
            return False, None, problem
        body = json.dumps(sheet, sort_keys=True, default=str).encode()
        signature = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
        headers = {'Content-Type': 'application/json', 'User-Agent': 'CiV attestation sender', 'Authorization': f'Bearer {key}',
                   'X-CiV-Signature': f'sha256={signature}', 'X-CiV-Sheet-Sha256': sheet.get('sha256', '')}
        try:
            status, text = _post(url, body, headers)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return False, None, 'Your rating engine could not be reached. Check the address, or try again later.'
        if 200 <= status < 300:
            return True, status, 'Accepted by the rating engine'
        return False, status, plain(status, text)


def plain(status: int, text: str) -> str:
    """A short message the insurer understands (2026-10-23), never the other server's web page; a cleaned, short copy
    of its answer is kept for their IT team."""
    import re
    if status in (401, 403):
        message = 'Your rating engine refused the key. Check the key you saved.'
    elif status == 404:
        message = 'Nothing was found at that address. Check the address you saved.'
    elif status == 405:
        message = 'That address does not accept the sheet. Use the receiving address from your rating engine\'s settings.'
    elif status >= 500:
        message = f'Your rating engine had a problem (error {status}). Try again later.'
    else:
        message = f'Your rating engine did not accept the sheet (error {status}).'
    words = re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', text or '')).strip()
    return message + (f' Technical answer: {words[:120]}' if words else '')


ADAPTERS = {JsonPost.name: JsonPost()}


def sheet_of(snapshot) -> dict:
    """What leaves CiV: the stored sheet, its version and fingerprint. No contact-level data is in it."""
    return {**snapshot.payload, 'companyId': f'c-{snapshot.client_id}', 'version': snapshot.version, 'sha256': snapshot.sha256,
            'madeAt': snapshot.made_at.isoformat()}


def send(engine, snapshot, by: str):
    """Sends one sheet and keeps a record; the company's access log shows it went."""
    from apps.access_log.recorder import record
    from apps.connections.crypto import unlock

    from .models import RatingSend
    key = unlock(engine.key).get('key', '')
    ok, status, detail = ADAPTERS[engine.adapter].send(engine.url, key, sheet_of(snapshot))
    row = RatingSend.objects.create(org=engine.org, client_id=snapshot.client_id, snapshot=snapshot, company=snapshot.payload.get('company', ''), by=by, ok=ok, status=status, detail=detail)
    record('attestation_sent' if ok else 'attestation_send_failed', actor_kind='buyer', actor_label=f'{by} ({engine.org.name})',
           client_id=snapshot.client_id, object=f'Risk Attestation {snapshot.period:%b %Y} v{snapshot.version}')
    return row
