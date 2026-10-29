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

# The pack's texts (owner, 2026-10-30: formal wording, the client's name in every file). {company} is filled in.
HOW_CIV_CAPTURES = """RECORD CAPTURE AND PRESERVATION STATEMENT
Prepared by Comply iV ("CiV") for {company}

1. Source of records. CiV obtains call, text message and customer-relationship records of {company} directly from the
   systems {company} uses (dialers, messaging platforms and CRM systems), through application programming interfaces
   (APIs). Access is read-only, was authorized by {company}, and may be withdrawn by {company} at any time. CiV does not
   create, edit or delete records in those systems.

2. Fingerprinting at the time of capture. When CiV retrieves a record, it computes a SHA-256 cryptographic hash (the
   "fingerprint") of the record exactly as returned by the source system. CiV retains the fingerprint, the name of the
   source system, the record's identifier in that system and the date and time of retrieval (UTC). CiV does not retain
   the content of the record itself; the original remains in the system of {company}.

3. Daily sealing. Each day, CiV combines all fingerprints retrieved that day for {company} into a single Merkle tree.
   The root of that tree (the "daily seal") is time-stamped by an independent RFC 3161 time-stamping authority and is
   additionally anchored to the Bitcoin blockchain through the OpenTimestamps service. Each fingerprint retains its
   path to the daily seal, so that its inclusion can be demonstrated independently.

4. Re-verification. On request, CiV retrieves a record again from the source system, computes a new fingerprint and
   compares it with the sealed fingerprint. The result is recorded as "Matches", "Changed" or "No longer at the source".

5. Telephone numbers. CiV does not store telephone numbers. Each number is converted into a keyed code, and only a
   masked form (area code and last four digits) appears in CiV's records and in this package. Counsel for {company}
   should supply the full numbers from the records of {company}.

6. Access controls. Every access to these records, by personnel of {company} or of CiV, is entered in CiV's access log
   with the person, the action and the date and time (UTC).
"""

HOW_TO_CHECK = """PROCEDURE FOR INDEPENDENT VERIFICATION OF A FINGERPRINT
Records of {company}

This procedure permits any party to confirm, without relying on CiV, that a record is the same record CiV retrieved on
the stated date and that it has not been altered since.

Materials required: (a) the record, obtained from the system of {company}; (b) the fingerprint list in this package
(certification/fingerprint-list.csv); and (c) any standard SHA-256 hashing tool.

Step 1. Compute the SHA-256 hash of the record exactly as the source system provides it. The result must be identical
        to the fingerprint ("sha256") shown for that record in the fingerprint list.
Step 2. Beginning with the leaf value listed for the record, combine it in order with each hash in its listed path,
        applying SHA-256 at each step. The final result must be identical to the daily seal ("seal_root") listed for
        that day.
Step 3. Confirm the time stamp of the daily seal using the public certificate of the RFC 3161 time-stamping authority,
        and its Bitcoin anchor using any OpenTimestamps verification tool.

If each step produces a match, the record is the record CiV retrieved from the system of {company} on that date, and it
has not been modified since that date.
"""

CUSTODIAN_TEMPLATE = """DRAFT · for counsel to review. Not for signature until counsel approves the wording.

DECLARATION OF CUSTODIAN OF RECORDS
In respect of the records of {company}

I, [name], declare as follows:

1. I am the [title] of Comply iV ("CiV"). I am a custodian of the records described in this declaration, and I am
   familiar with the manner in which CiV receives, fingerprints, seals and preserves the records of {company}.

2. The fingerprints, daily seals and evidence files contained in this package were made at or near the time of the
   events they describe, by an automated process that CiV carries out in the regular course of its business, as
   described in the Record Capture and Preservation Statement included in this package.

3. It is the regular practice of CiV to make and preserve such records.

4. The fingerprint list contained in this package is a true and correct copy of the fingerprints held by CiV for the
   telephone numbers identified in this package.

I declare under penalty of perjury under the laws of [state / the United States] that the foregoing is true and
correct.

Executed on [date] at [place].


____________________________
[name]
[title], Comply iV
"""


def filled(template: str, client) -> str:
    return template.replace('{company}', client.name)


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
            z.writestr('not-found.txt', f'TELEPHONE NUMBERS WITH NO RECORDS\nRecords of {client.name}\n\n'
                       f'CiV holds no records of {client.name} for the following telephone numbers (last four digits shown):\n\n'
                       + '\n'.join(f'- ••• {m}' for m in missing) + '\n')
        if pack:
            rows = io.StringIO()
            w = csv.writer(rows)
            w.writerow(['company', 'number', 'record', 'tool', 'record_id', 'read_at_utc', 'sha256', 'seal_day', 'seal_root', 'leaf', 'path', 'seal_check', 'at_source'])
            for data in files:
                for f in data['fingerprints']:
                    seal = f['seal'] or {}
                    w.writerow([client.name, data['number'], f['what'], f['tool'], f['record'], f['fetchedAt'], f['sha256'], seal.get('day', ''), seal.get('root', ''),
                                seal.get('leaf', ''), json.dumps(seal.get('path')) if seal else '', f['check'],
                                (f.get('atSource') or {}).get('result', 'Not asked again')])
            z.writestr('certification/fingerprint-list.csv', rows.getvalue())
            z.writestr('certification/how-civ-captures-records.txt', filled(HOW_CIV_CAPTURES, client))
            z.writestr('certification/how-to-check-a-fingerprint.txt', filled(HOW_TO_CHECK, client))
            z.writestr('certification/custodian-declaration-DRAFT.txt', filled(CUSTODIAN_TEMPLATE, client))
            z.writestr('certification/made.txt', f'Prepared by Comply iV for {client.name} on {timezone.now():%d %B %Y at %H:%M} UTC. '
                       f'Contains {len(files)} evidence file(s).\n')
    return out.getvalue()
