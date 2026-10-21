"""One small reader per texting tool: given a message's ID in that tool, its words and who wrote them, in memory only.
Everything else in conversation review is the same for every tool. A tool with no reader here (or one that cannot
re-read old messages) gives "not reviewed"; adding a tool's connector adds its reader in the same step."""
from apps.connections.models import Connection, Status

USABLE = [Status.CONNECTED, Status.STALE]


class CannotRead(Exception):
    """The tool does not share this message's words (deleted, too old, refused)."""


def twilio_text(connection, record_id: str) -> str:
    from apps.sync.connectors.twilio import Twilio
    tool = Twilio(connection)
    try:
        row = tool._get(f'/2010-04-01/Accounts/{tool.sid}/Messages/{record_id}.json')
    except Exception as error:
        raise CannotRead(type(error).__name__) from None
    return str(row.get('body') or '')


READERS = {'twilio': twilio_text}


def reader_for(client, source_system: str):
    """(function, connection) for a tool that can re-read its messages, or None."""
    read = READERS.get(source_system)
    connection = Connection.objects.filter(client=client, provider=source_system, status__in=USABLE).first()
    return (read, connection) if read and connection else None


# --- Call recordings: one small reader per dialer. Built from each tool's docs; not yet tried on real accounts. --------

class NoRecording(Exception):
    """The call was not recorded (or the tool keeps no copy CiV can read)."""


MAX_AUDIO = 200 * 1024 * 1024


def _download(url: str, headers: dict | None = None) -> bytes:
    import urllib.request
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=120) as reply:
        return reply.read(MAX_AUDIO)


def twilio_recording(connection, call_sid: str) -> bytes:
    """Twilio: the call's recordings list, then the first recording as audio (Basic auth with the account)."""
    import base64

    from apps.sync.connectors.twilio import API, Twilio
    tool = Twilio(connection)
    try:
        found = tool._get(f'/2010-04-01/Accounts/{tool.sid}/Recordings.json', {'CallSid': call_sid}).get('recordings') or []
    except Exception as error:
        raise CannotRead(type(error).__name__) from None
    if not found:
        raise NoRecording()
    auth = base64.b64encode(f'{tool.sid}:{tool.token}'.encode()).decode()
    return _download(f"{API}/2010-04-01/Accounts/{tool.sid}/Recordings/{found[0]['sid']}.mp3", {'Authorization': f'Basic {auth}'})


def vicidial_recording(connection, record_id: str) -> bytes:
    """Vicidial: recording_log has the file's location for the call (vicidial_id = the call's ID). SELECT only."""
    from apps.sync.connectors.vicidial import Vicidial
    call_id = record_id.split(':', 1)[-1]
    rows = Vicidial(connection).query('SELECT location FROM recording_log WHERE vicidial_id = %s ORDER BY recording_id DESC LIMIT 1', (call_id,))
    if not rows or not rows[0].get('location'):
        raise NoRecording()
    return _download(rows[0]['location'])


def convoso_recording(connection, record_id: str) -> bytes:
    """Convoso: the call log row's recording link (TO CONFIRM on a real account)."""
    from apps.sync.connectors.convoso import Convoso
    try:
        data = Convoso(connection)._get('log/retrieve', {'id': record_id, 'limit': 1, 'offset': 0})
    except Exception as error:
        raise CannotRead(type(error).__name__) from None
    rows = data.get('results') or []
    link = rows[0].get('recording') if rows else None
    if isinstance(link, list):
        link = (link[0] or {}).get('public_url') or (link[0] or {}).get('src') if link else None
    if not link:
        raise NoRecording()
    return _download(str(link))


RECORDINGS = {'twilio': twilio_recording, 'vicidial': vicidial_recording, 'convoso': convoso_recording}  # Five9: to add with its recordings API


def recording_reader_for(client, source_system: str):
    read = RECORDINGS.get(source_system)
    connection = Connection.objects.filter(client=client, provider=source_system, status__in=USABLE).first()
    return (read, connection) if read and connection else None
