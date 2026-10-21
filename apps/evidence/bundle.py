"""Module 14 step 3: the bulk evidence export and the certification pack (owner decisions 2026-10-22).
- Bulk: up to 25 typed numbers; each is turned into its phone code in memory (never stored) and gets its evidence file
  (PDF + JSON) in one ZIP; numbers CiV has never seen are listed as not found.
- Certification pack: the fingerprint list of those files with their seals, how CiV captures records, how to check a
  fingerprint against its seal, and a custodian statement template labelled a draft for counsel to review."""
import csv
import io
import json
import zipfile

from django.utils import timezone

from apps.contacts.api import number_ref
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.keyring.phones import normalize

from .file import build
from .pdf import render

MAX_NUMBERS = 25

HOW_CIV_CAPTURES = """How Comply iV captures records

1. Comply iV reads each call, text and CRM record from the company's own tools through their APIs, with read-only access
   the company granted and can revoke.
2. As it reads a record, Comply iV computes its SHA-256 fingerprint and keeps the fingerprint, the tool's name, the
   record's ID in that tool and the time it was read. It does not keep the record itself; the company's tool keeps it.
3. Every night, Comply iV builds one Merkle tree over all fingerprints read that day for the company. Its root
   ("the day's seal") is stamped by an independent RFC 3161 timestamp service and submitted to the Bitcoin blockchain
   through OpenTimestamps. Each fingerprint keeps its path to the root.
4. When asked, Comply iV fetches a record from the tool again and compares a new fingerprint with the sealed one:
   Matches, Changed, or No longer at the source.
5. Phone numbers are never stored: each number becomes a keyed phone code; only a masked label (area code and last 4
   digits) is shown.
"""

HOW_TO_CHECK = """How to check a fingerprint against its seal

You need: the record (from the company's own tool), the fingerprint list in this pack, and a SHA-256 tool.

1. Compute the SHA-256 of the record exactly as the tool returns it. It must equal the fingerprint in the list.
2. Starting from the leaf (the fingerprint, the tool, the record ID and the read time, as listed), combine it with each
   hash in its path, in order, with SHA-256. The result must equal the day's root in the list.
3. The root's timestamp can be checked with the timestamp service's public certificate, and its Bitcoin stamp with any
   OpenTimestamps verifier.
If every step matches, the record is the one Comply iV saw on that day and has not changed since.
"""

CUSTODIAN_TEMPLATE = """DRAFT · for counsel to review. Not for signature until counsel approves the wording.

DECLARATION OF RECORDS CUSTODIAN

I, [name], declare:

1. I am [title] at Comply iV and I am familiar with how Comply iV receives and keeps records of [company].
2. The fingerprints, seals and evidence files in this pack were made at or near the time of the events they describe,
   by an automated process Comply iV runs in the regular course of its business, as described in
   "How Comply iV captures records" in this pack.
3. It is the regular practice of Comply iV to make and keep these records.
4. The fingerprint list in this pack is a true copy of the fingerprints Comply iV holds for the numbers listed.

I declare under penalty of perjury under the laws of [state / the United States] that the foregoing is true and correct.

Executed on [date] at [place].

____________________
[name]
"""


def resolve(client, typed: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """([(masked, ref)], [not found]) — numbers become phone codes in memory and are never stored."""
    codes, found, missing = codes_for(client), [], []
    for text in typed[:MAX_NUMBERS]:
        number = normalize(text)
        token = codes.token(number) if number else None
        contact = ContactEvent.objects.filter(client=client, phone_token=token).order_by('-occurred_at').first() if token else None
        if contact:
            found.append((contact.masked_label or 'Number hidden', number_ref(token)))
        else:
            missing.append(text.strip()[-4:].rjust(4, '•') if text.strip() else '')
    return found, missing


def files_for(client, refs: list[tuple[str, str]]) -> list[dict]:
    return [d for d in (build(client, ref) for _, ref in refs) if d]


def zip_bundle(client, files: list[dict], missing: list[str], pack: bool) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, data in enumerate(files, 1):
            stem = f'{i:02d}-{data["ref"][2:10]}'
            z.writestr(f'evidence-files/{stem}.pdf', render(data))
            z.writestr(f'evidence-files/{stem}.json', json.dumps(data, default=str, indent=1, ensure_ascii=False))
        if missing:
            z.writestr('not-found.txt', 'Numbers CiV holds no records for (last 4 digits):\n' + '\n'.join(missing) + '\n')
        if pack:
            rows = io.StringIO()
            w = csv.writer(rows)
            w.writerow(['number', 'record', 'tool', 'record_id', 'read_at_utc', 'sha256', 'seal_day', 'seal_root', 'leaf', 'path', 'seal_check', 'at_source'])
            for data in files:
                for f in data['fingerprints']:
                    seal = f['seal'] or {}
                    w.writerow([data['number'], f['what'], f['tool'], f['record'], f['fetchedAt'], f['sha256'], seal.get('day', ''), seal.get('root', ''),
                                seal.get('leaf', ''), json.dumps(seal.get('path')) if seal else '', f['check'],
                                (f.get('atSource') or {}).get('result', 'Not asked again')])
            z.writestr('certification/fingerprint-list.csv', rows.getvalue())
            z.writestr('certification/how-civ-captures-records.txt', HOW_CIV_CAPTURES)
            z.writestr('certification/how-to-check-a-fingerprint.txt', HOW_TO_CHECK)
            z.writestr('certification/custodian-declaration-DRAFT.txt', CUSTODIAN_TEMPLATE.replace('[company]', client.name))
            z.writestr('certification/made.txt', f'Made {timezone.now():%Y-%m-%d %H:%M} UTC for {client.name}; {len(files)} evidence file(s).\n')
    return out.getvalue()
