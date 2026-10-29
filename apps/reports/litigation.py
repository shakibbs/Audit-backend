"""The litigation evidence package (2026-10-30): the bulk evidence files and certification pack for up to 25 numbers the
client types, plus a chain-of-custody report for each number. Made when the client sends the numbers (CiV never keeps
them), checked by CiV staff, then released with the custodian declaration naming the CiV person who checked it."""
import hashlib
import io
import zipfile

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.evidence.bundle import CUSTODIAN_TEMPLATE, filled, files_for, resolve, zip_bundle

from .models import QuoteRequest


def custody(client, data: dict) -> str:
    """The chain-of-custody report for one number: each record retrieved from the client's systems with its fingerprint
    and seal, then every access-log entry naming this masked number, oldest first."""
    from apps.access_log.models import AccessEntry
    lines = ['CHAIN OF CUSTODY REPORT', f'Records of {client.name} · telephone number {data["number"]}',
             f'Prepared by Comply iV ("CiV") on {timezone.now():%d %B %Y at %H:%M} UTC', '',
             'Part 1. Records retrieved from the systems of ' + client.name,
             f'Each record below was retrieved by CiV, through read-only API access authorized by {client.name}, from the system',
             'named. CiV retained its fingerprint (SHA-256), not its content; the original remains with ' + client.name + '.', '']
    prints = sorted(data['fingerprints'], key=lambda f: str(f['fetchedAt']))
    for n, f in enumerate(prints, 1):
        seal = f['seal'] or {}
        lines += [f'{n}. Retrieved {f["fetchedAt"]} UTC from {f["tool"]}: {f["what"]}, record {f["record"]}',
                  f'   Fingerprint (SHA-256): {f["sha256"]}',
                  f'   Daily seal: {"sealed on " + seal["day"] + ", root " + seal["root"] if seal else "not yet sealed"}',
                  f'   Seal check: {f["check"]}. Re-verification at the source: {(f.get("atSource") or {}).get("result", "not requested")}.']
    if not prints:
        lines.append('No records retrieved.')
    lines += ['', 'Part 2. Access to these records',
              f'Every access by personnel of {client.name} or of CiV, as entered in CiV\'s access log:', '']
    entries = AccessEntry.objects.filter(client_id=client.pk, object__startswith=data['number']).order_by('at')
    lines += [f'{e.at:%Y-%m-%d %H:%M} UTC · {e.action.replace("_", " ")} · by {e.actor_label or e.actor_kind}' for e in entries] or ['No access entries.']
    lines += ['', 'Note. CiV does not store telephone numbers. Entries are matched by the masked number (area code and last four',
              'digits); counsel should confirm the full number from the records of ' + client.name + '.']
    return '\n'.join(lines) + '\n'


def index(client, files: list[dict], missing: list[str]) -> str:
    """The package's first page: what it is for and what each part holds."""
    return f"""LITIGATION EVIDENCE PACKAGE
Prepared by Comply iV ("CiV") for {client.name}
Date prepared: {timezone.now():%d %B %Y} · Telephone numbers with records: {len(files)} · Without records: {len(missing)}

This package contains the evidence CiV holds for the telephone numbers identified by {client.name}. It is provided
to {client.name} and its counsel. CiV measures and records; it does not provide legal advice.

Contents
1. evidence-files/       One evidence file per telephone number (PDF and JSON): each contact, the consent decision,
                         proof elements, opt-out records and fingerprints.
2. chain-of-custody/     One chain of custody report per telephone number.
3. certification/        fingerprint-list.csv (every fingerprint with its daily seal), the Record Capture and
                         Preservation Statement, the Procedure for Independent Verification of a Fingerprint and the
                         Declaration of Custodian of Records (added when CiV releases the package).
4. not-found.txt         Telephone numbers for which CiV holds no records of {client.name} (if any).
"""


def make(q: QuoteRequest, typed: list[str], by: str) -> tuple[list[dict], list[str]]:
    """Builds the package from the typed numbers and keeps it for staff to check. Returns (files, not found)."""
    found, missing = resolve(q.client, typed)
    files = files_for(q.client, found)
    out = io.BytesIO(zip_bundle(q.client, files, missing, pack=True))
    with zipfile.ZipFile(out, 'a', zipfile.ZIP_DEFLATED) as z:
        z.writestr('00-package-contents.txt', index(q.client, files, missing))
        for i, data in enumerate(files, 1):
            z.writestr(f'chain-of-custody/{i:02d}-{data["ref"][2:10]}.txt', custody(q.client, data))
    if q.package:
        q.package.delete(save=False)
    q.package.save('package.zip', ContentFile(out.getvalue()), save=False)
    q.package_sha256 = hashlib.sha256(out.getvalue()).hexdigest()
    q.package_files, q.package_missing = len(files), len(missing)
    q.made_at, q.made_by, q.status = timezone.now(), by, QuoteRequest.Status.CHECKING
    q.save()
    return files, missing


def release(q: QuoteRequest, staff_email: str) -> None:
    """Adds the custodian declaration with the checking CiV person's name, then lets the client download it."""
    now = timezone.now()
    declaration = (filled(CUSTODIAN_TEMPLATE, q.client).replace('DRAFT · for counsel to review. Not for signature until counsel approves the wording.\n\n', '')
                   .replace('[name]', q.custodian_name).replace('[title]', q.custodian_title).replace('[date]', f'{now:%d %B %Y}'))
    with q.package.open('rb') as f:
        out = io.BytesIO(f.read())
    with zipfile.ZipFile(out, 'a', zipfile.ZIP_DEFLATED) as z:
        z.writestr('certification/custodian-declaration.txt', declaration)
        z.writestr('certification/released.txt', f'RELEASE RECORD\nLitigation evidence package for {q.client.name}\n\n'
                   f'Reviewed and released by {q.custodian_name}, {q.custodian_title}, Comply iV ({staff_email}), on {now:%d %B %Y at %H:%M} UTC.\n'
                   f'Requested by {q.asked_by} of {q.client.name} on {q.asked_at:%d %B %Y}.\n')
    old = q.package.name
    q.package.save('package.zip', ContentFile(out.getvalue()), save=False)
    q.package.storage.delete(old)
    q.package_sha256 = hashlib.sha256(out.getvalue()).hexdigest()
    q.released_at, q.released_by, q.status = now, staff_email, QuoteRequest.Status.RELEASED
    q.save()
