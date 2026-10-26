"""'Test connection': one read-only call per tool. Tools without a tester yet stay 'Saved, not tested'."""
import logging
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from apps.connections.models import Connection, Status

log = logging.getLogger('civ.connections')

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


def test_convoso(creds: dict) -> tuple[str, str]:
    """Reads one call from the last hour; also checks the account time zone, which every call time depends on."""
    from datetime import UTC, datetime, timedelta

    from apps.sync.connectors.convoso import WHEN, ConvosoError, zone
    try:  # the Time zone box (2026-10-23); connections saved before it kept the zone in "API secret"
        tz = zone(creds.get('setting') or creds.get('secret', ''))
    except ConvosoError:
        return Status.FAILED, 'Choose the Convoso account time zone in the "Time zone or region" box.'
    now = datetime.now(UTC).astimezone(tz)
    body = {'auth_token': creds.get('key', ''), 'start_time': (now - timedelta(hours=1)).strftime(WHEN), 'end_time': now.strftime(WHEN), 'limit': 1}
    try:
        request = urllib.request.Request('https://api.convoso.com/v1/log/retrieve', data=urllib.parse.urlencode(body).encode(), headers={'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            answer = json.loads(reply.read())
    except urllib.error.HTTPError as error:  # a refusal is an answer, not "could not reach"
        if error.code in (401, 403):
            return Status.FAILED, 'Convoso refused the auth token: check it in Convoso → Admin → API.'
        return Status.FAILED, f'Convoso answered with an error (HTTP {error.code}). Try again in a minute.'
    except (urllib.error.URLError, TimeoutError):
        return Status.FAILED, 'Could not reach Convoso. Try again in a minute.'
    if not answer.get('success'):
        return Status.FAILED, 'Convoso refused the auth token: check it in Convoso → Admin → API.'
    return Status.CONNECTED, f'Read access works (call log, times in {tz.key}).'


def test_five9(creds: dict) -> tuple[str, str]:
    """Runs the Call Log report for the last minute: proves the login works and the user may run reports."""
    from datetime import UTC, datetime, timedelta

    from apps.sync.connectors.five9 import Five9, Five9Error, zone
    try:
        zone(creds.get('setting') or creds.get('secret', ''))
    except Five9Error:
        return Status.FAILED, 'Enter the Five9 report time zone in "Time zone or region", e.g. America/New_York.'

    class Probe:  # just enough of a connection for the adapter
        setting = creds.get('setting', '')

        def get_credentials(self):
            return creds
    try:
        adapter = Five9(Probe())
        now = datetime.now(UTC)
        adapter.report_csv(now - timedelta(minutes=1), now)
    except Five9Error as error:
        return Status.FAILED, f'Five9 said: {error}. Check the username, password and that the user may run the Call Log report.'
    except (urllib.error.URLError, TimeoutError):
        return Status.FAILED, 'Could not reach Five9, or the report took too long. Try again in a minute.'
    return Status.CONNECTED, 'Read access works (Call Log report).'


def test_vicidial(creds: dict) -> tuple[str, str]:
    """Connects to the client's Vicidial database and reads one row from each call log table (read-only)."""
    import pymysql

    from apps.sync.connector import AccessRemoved
    from apps.sync.connectors.vicidial import TABLES, BadAddress, Vicidial

    class Probe:
        def get_credentials(self):
            return creds
    adapter = Vicidial(Probe())
    try:
        for table in TABLES:
            adapter.query(f'SELECT {table.id_column} FROM {table.table} LIMIT 1', ())
    except BadAddress as problem:
        return Status.FAILED, str(problem)
    except AccessRemoved:
        return Status.FAILED, 'Vicidial refused the database user or password.'
    except pymysql.err.OperationalError as error:
        code = error.args[0] if error.args else 0
        if code == 1045:
            return Status.FAILED, 'Vicidial refused the database user or password.'
        return Status.FAILED, ('Could not reach the Vicidial database securely: check the server address and port, that it '
                               'accepts CiV, and that it offers an encrypted (TLS) connection with a valid certificate.')
    except pymysql.err.ProgrammingError:
        return Status.FAILED, 'Connected, but the call log tables could not be read: give the user SELECT on vicidial_log and vicidial_closer_log.'
    return Status.CONNECTED, 'Read access works (outbound and inbound call logs).'


def _certificate_probe(ask) -> tuple[str, str]:
    """Asks about a made-up certificate: "not found" proves the key works; "refused" means it does not."""
    from apps.certificates import vendors
    try:
        ask()
    except vendors.NotFound:
        return Status.CONNECTED, 'The key works (asked about a test certificate; nothing was claimed).'
    except vendors.Refused:
        return Status.FAILED, 'The account code or key was refused: check them in the vendor account.'
    except (urllib.error.URLError, TimeoutError):
        return Status.FAILED, 'Could not reach the vendor. Try again in a minute.'
    return Status.CONNECTED, 'The key works.'


def test_trustedform(creds: dict) -> tuple[str, str]:
    from apps.certificates import vendors
    return _certificate_probe(lambda: vendors.claim_trustedform('0' * 40, creds.get('key', ''), 'civ-key-test'))


def test_jornaya(creds: dict) -> tuple[str, str]:
    from apps.certificates import vendors
    if not creds.get('account'):
        return Status.FAILED, 'Enter the Jornaya account code (LAC) in "Account ID".'
    return _certificate_probe(lambda: vendors.read_jornaya('00000000-0000-0000-0000-000000000000', creds['account'], creds.get('key', '')))


TESTERS = {'twilio': test_twilio, 'convoso': test_convoso, 'five9': test_five9, 'vicidial': test_vicidial,
           'trustedform': test_trustedform, 'jornaya': test_jornaya}


def run_test(connection: Connection) -> tuple[str, str]:
    """Returns (status, message). Never changes anything at the tool."""
    if connection.tool.auth == 'oauth':
        return connection.status, 'Connects when the client clicks Allow; nothing to test here yet.'
    if not connection.has_credentials:
        return Status.NOT_CONNECTED, 'No key saved yet.'
    tester = TESTERS.get(connection.provider)
    if tester is None:
        return Status.UNTESTED, f'Key saved. A live test for {connection.tool.name} comes with its connector.'
    # The visible Time zone / region box goes along with the keys (never stored with them).
    try:
        status, message = tester({**connection.get_credentials(), 'setting': connection.setting})
    except Exception as problem:  # an odd reply (bad JSON, a web page, a bad port) is a failed test, never a crash
        log.warning('Tester for %s failed: %r', connection.provider, problem)
        return Status.FAILED, f'{connection.tool.name} gave an answer CiV could not read. Check the address and keys.'
    return status, ' '.join(str(message).split())[:290]  # the status box holds 300 characters
