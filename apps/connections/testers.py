"""'Test connection': one read-only call per tool. Tools without a tester yet stay 'Saved, not tested'."""
import base64
import json
import urllib.error
import urllib.request

from apps.connections.models import Connection, Status

TIMEOUT_SECONDS = 10


def _get(url: str, user: str, password: str) -> dict:
    token = base64.b64encode(f'{user}:{password}'.encode()).decode()
    request = urllib.request.Request(url, headers={'Authorization': f'Basic {token}', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
        return json.loads(reply.read())


def test_twilio(creds: dict) -> tuple[str, str]:
    sid, token = creds.get('account', ''), creds.get('key', '')
    try:
        account = _get(f'https://api.twilio.com/2010-04-01/Accounts/{sid}.json', sid, token)
    except urllib.error.HTTPError as error:
        return Status.FAILED, f'Twilio said {error.code}: check the Account SID and auth token.'
    except (urllib.error.URLError, TimeoutError):
        return Status.FAILED, 'Could not reach Twilio. Try again in a minute.'
    return Status.CONNECTED, f'Read access works for account "{account.get("friendly_name", sid)}".'


TESTERS = {'twilio': test_twilio}


def run_test(connection: Connection) -> tuple[str, str]:
    """Returns (status, message). Never changes anything at the tool."""
    if connection.tool.auth == 'oauth':
        return connection.status, 'Connects when the client clicks Allow; nothing to test here yet.'
    if not connection.has_credentials:
        return Status.NOT_CONNECTED, 'No key saved yet.'
    tester = TESTERS.get(connection.provider)
    if tester is None:
        return Status.UNTESTED, f'Key saved. A live test for {connection.tool.name} comes with its connector.'
    return tester(connection.get_credentials())
