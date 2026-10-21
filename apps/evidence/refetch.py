"""Module 14 step 2: the re-fetch check (spec §9 evidence file: "Matches / Changed / No longer at source"). CiV asks
the tool for the record again (in memory), fingerprints it, and compares it with every fingerprint it sealed of that
record: equal to one → matches (the record is as CiV saw it then); different → changed; not found → gone. On demand for
a number (before exporting its evidence file) and a weekly sample of 50 call and text records per client (owner
decision 2026-10-22); changed records raise an alert (Module 11)."""
import hashlib
import random

from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.ledger.models import Fingerprint
from apps.sync.connector import connector_for

from .models import RefetchCheck

SAMPLE = 50
R = RefetchCheck.Result
USABLE = [Status.CONNECTED, Status.STALE]


def check(client, tool: str, record_id: str, why: str, tools: dict) -> RefetchCheck:
    connection = tools.get(tool)
    if tool not in tools:
        connection = tools[tool] = Connection.objects.filter(client=client, provider=tool, status__in=USABLE).first()
    adapter = connector_for(connection) if connection else None
    fields = {'client': client, 'source_system': tool, 'source_record_id': record_id, 'why': why}
    if adapter is None:
        return RefetchCheck.objects.create(**fields, result=R.CANNOT)
    try:
        record = adapter.fetch_one(record_id)
    except NotImplementedError:
        return RefetchCheck.objects.create(**fields, result=R.CANNOT)
    except Exception:
        return RefetchCheck.objects.create(**fields, result=R.FAILED)
    if record is None:
        return RefetchCheck.objects.create(**fields, result=R.GONE)
    sha = hashlib.sha256(record.raw).hexdigest()
    del record  # in memory only
    same = Fingerprint.objects.filter(client=client, source_system=tool, source_record_id=record_id, sha256=sha).order_by('-fetched_at').first()
    return RefetchCheck.objects.create(**fields, result=R.MATCHES if same else R.CHANGED, sha256=sha, matched=same)


def check_records(client, records, why: str = 'on_demand') -> list[RefetchCheck]:
    tools: dict = {}
    return [check(client, tool, rid, why, tools) for tool, rid in dict.fromkeys(records)]


def weekly_sample(client, size: int = SAMPLE) -> int:
    ids = list(Fingerprint.objects.filter(client=client, content_kind__in=['call', 'text'], anchor__isnull=False)
               .values_list('source_system', 'source_record_id').distinct()[:5000])
    picked = random.Random(f'{client.pk}|{timezone.now():%G-%V}').sample(ids, min(size, len(ids)))
    return len(check_records(client, picked, 'weekly'))


def latest(client, tool: str, record_id: str) -> RefetchCheck | None:
    return RefetchCheck.objects.filter(client=client, source_system=tool, source_record_id=record_id).first()
