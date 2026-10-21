"""Module 13 step 1: the law watcher's reader (owner decision 2026-10-15: suggestions only, a CiV admin decides).
Once a day it reads the Federal Register's free official API for FCC rules and proposed rules on the phone rules
(47 CFR part 64) and anything naming the TCPA, keeps those that match calling words, and saves each once with its
link (step 2 sorts them: sorting.py). The FCC's own website refuses automated readers (2026-10-22), and every FCC rule is published in the Federal
Register anyway; courts (CourtListener) and state laws come later."""
import json
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta

from django.db import IntegrityError, transaction

from .models import LawItem

API = 'https://www.federalregister.gov/api/v1/documents.json'
FIELDS = ['title', 'abstract', 'publication_date', 'effective_on', 'document_number', 'html_url', 'type', 'agencies', 'docket_ids', 'raw_text_url']
SEARCHES = [  # (conditions) — both limited to rules and proposed rules
    {'conditions[cfr][title]': '47', 'conditions[cfr][part]': '64'},
    {'conditions[term]': '"Telephone Consumer Protection"'},
]
WORDS = ['telephone consumer protection', 'tcpa', 'robocall', 'robotext', 'telemarket', 'do-not-call', 'do not call', 'autodial',
         'automatic telephone dialing', 'artificial or prerecorded', 'prerecorded', 'text message', 'revocation', 'revoke consent',
         'prior express', 'reassigned number', 'caller id', 'stir/shaken', 'call authentication', 'call blocking', 'one-to-one consent',
         'consent', 'opt-out', 'opt out']
FIRST_LOOK_DAYS = 365  # the first run looks back a year; later runs a week (anything missed is caught again)
AGENT = 'CiV law watcher (Comply iV)'


def fetch(params: dict) -> dict:
    query = urllib.parse.urlencode([*params.items(), *[('fields[]', f) for f in FIELDS]], doseq=True)
    request = urllib.request.Request(f'{API}?{query}', headers={'User-Agent': AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return json.loads(reply.read(5_000_000))


def matches(doc: dict) -> list[str]:
    text = f"{doc.get('title') or ''} {doc.get('abstract') or ''}".lower()
    return [w for w in WORDS if re.search(r'\b' + re.escape(w), text)]


def documents(since: date, get=fetch, pages: int = 5) -> list[dict]:
    found = {}
    for extra in SEARCHES:
        for page in range(1, pages + 1):
            params = {'order': 'newest', 'per_page': 100, 'page': page, 'conditions[type][]': ['RULE', 'PRORULE'],
                      'conditions[publication_date][gte]': since.isoformat(), **extra}
            data = get(params)
            for doc in data.get('results') or []:
                found[doc['document_number']] = doc
            if page >= (data.get('total_pages') or 1):
                break
    return list(found.values())


def refresh(today: date | None = None, get=fetch) -> int:
    """New calling-law items since the last look. Returns how many were added."""
    today = today or date.today()
    first = not LawItem.objects.filter(source='federal_register').exists()
    since = today - timedelta(days=FIRST_LOOK_DAYS if first else 7)
    added = 0
    for doc in documents(since, get):
        words = matches(doc)
        if not words:
            continue  # part 64 also covers relay services and data collection: not calling rules
        agencies = ', '.join(a.get('name') or '' for a in doc.get('agencies') or [] if isinstance(a, dict))
        try:
            with transaction.atomic():
                LawItem.objects.create(source='federal_register', ref=doc['document_number'], kind=doc.get('type') or '',
                                       title=(doc.get('title') or '')[:500], summary=doc.get('abstract') or '', agencies=agencies[:300],
                                       published_on=date.fromisoformat(doc['publication_date']),
                                       effective_on=date.fromisoformat(doc['effective_on']) if doc.get('effective_on') else None,
                                       url=doc.get('html_url') or '', matched=words,
                                       dockets=[d for d in doc.get('docket_ids') or [] if isinstance(d, str)],
                                       text_url=doc.get('raw_text_url') or '')
            added += 1
        except IntegrityError:
            continue  # already saved
    from .drafting import draft_new
    from .sorting import resort
    resort(today)  # step 2: rules touched, how serious, stage, earlier proposal
    draft_new()  # step 3: the AI's draft (nothing happens while no AI is chosen)
    return added
