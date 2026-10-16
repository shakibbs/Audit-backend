"""Independent totals from the tools' own billing. Twilio: Usage Records (Daily), built from Twilio's docs (not yet
tried on a real account). Dialers and vendor invoices have no billing API here yet: "not available"."""
import base64
import json
import urllib.parse
import urllib.request
from datetime import date

TWILIO_CATEGORY = {'texts': 'sms-outbound', 'calls': 'calls-outbound'}
TIMEOUT_SECONDS = 20


def twilio_billed(connection, measure: str, start: date, end: date) -> int:
    """How many outbound texts or calls Twilio billed between start and end (inclusive)."""
    creds = connection.get_credentials()
    sid, token = creds.get('account', ''), creds.get('key', '')
    auth = base64.b64encode(f'{sid}:{token}'.encode()).decode()
    url = (f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Usage/Records/Daily.json?'
           + urllib.parse.urlencode({'Category': TWILIO_CATEGORY[measure], 'StartDate': start.isoformat(), 'EndDate': end.isoformat(), 'PageSize': 1000}))
    total = 0
    while url:
        request = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
            page = json.loads(reply.read())
        total += sum(int(float(r.get('count') or 0)) for r in page.get('usage_records', []))
        nxt = page.get('next_page_uri')
        url = f'https://api.twilio.com{nxt}' if nxt else ''
    return total
