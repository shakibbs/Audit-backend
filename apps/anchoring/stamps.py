"""Outside time stamps for a day's root: RFC 3161 (a signed "this existed at this time") and OpenTimestamps (Bitcoin)."""
import hashlib
import urllib.request

from django.conf import settings
from rfc3161_client import HashAlgorithm, TimestampRequestBuilder, decode_timestamp_response


class StampFailed(Exception):
    pass


def _post(url: str, body: bytes, content_type: str) -> bytes:
    request = urllib.request.Request(url, data=body, headers={'Content-Type': content_type, 'Accept': '*/*', 'User-Agent': 'CiV'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def tsa_stamp(root: bytes):
    """Asks each RFC 3161 service in turn; returns (url, signed answer, stamp time) from the first that answers well."""
    for url in settings.ANCHOR_TSA_URLS:
        try:
            query = TimestampRequestBuilder().data(root).hash_algorithm(HashAlgorithm.SHA256).nonce(nonce=True).build()
            answer = _post(url, query.as_bytes(), 'application/timestamp-query')
            if tsa_covers(answer, root):
                return url, answer, decode_timestamp_response(answer).tst_info.gen_time
        except Exception:  # try the next service
            continue
    raise StampFailed('No time-stamp service answered.')


def tsa_covers(answer: bytes, root: bytes) -> bool:
    """True when the signed answer is granted and stamps exactly this root."""
    response = decode_timestamp_response(answer)
    return response.status in (0, 1) and response.tst_info.message_imprint.message == hashlib.sha256(root).digest()


def ots_stamp(root: bytes):
    """Sends the root to an OpenTimestamps calendar; returns (calendar, pending proof)."""
    for calendar in settings.ANCHOR_OTS_CALENDARS:
        try:
            return calendar, _post(f'{calendar}/digest', root, 'application/x-www-form-urlencoded')
        except Exception:
            continue
    raise StampFailed('No OpenTimestamps calendar answered.')
