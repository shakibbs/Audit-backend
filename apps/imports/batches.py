"""Groups each user's created records into batches (spec §5a creation bursts) and tells uploads from feeds.

- A gap over import_gap_seconds (Rulebook: 120) starts a new batch. n ≥ import_min_batch (20) → bulk import;
  n = 1 → typed by hand; otherwise small batch.
- The tool's own "import" label (HubSpot IMPORT) makes a batch a bulk import whatever its size.
- Feeds are not uploads. Without per-client settings (owner decision), a feed is recognised by itself: the tool says
  INTEGRATION / API, or the user creates records on many days and at many hours (a steady stream), not one burst.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from apps.tenancy.scope import all_clients, tenant

from .models import CrmCreation, ImportBatch

TOOL_IMPORT = {'IMPORT'}
TOOL_FEED = {'INTEGRATION', 'API', 'APP', 'EXTENSION', 'BCC_TO_CRM'}
FEED_DAYS, FEED_HOURS, FEED_LOOKBACK = 5, 10, timedelta(days=14)  # active on ≥5 days and ≥10 hours of the day in 2 weeks


def thresholds() -> tuple[timedelta, int]:
    from apps.rulebook.lookup import NoRulebook, RuleSet
    try:
        rules, today = RuleSet(), timezone.localdate()
        return timedelta(seconds=rules.get('import_gap_seconds', on=today).value or 120), rules.get('import_min_batch', on=today).value or 20
    except NoRulebook:
        return timedelta(seconds=120), 20


def feed_users(client_id, source: str) -> set[str]:
    since = timezone.now() - FEED_LOOKBACK
    rows = CrmCreation.objects.filter(client_id=client_id, source_system=source, created_at__gte=since).exclude(created_by='')
    days = dict(rows.annotate(d=TruncDate('created_at')).values('created_by').annotate(n=Count('d', distinct=True)).values_list('created_by', 'n'))
    hours = dict(rows.annotate(h=ExtractHour('created_at')).values('created_by').annotate(n=Count('h', distinct=True)).values_list('created_by', 'n'))
    return {u for u in days if days[u] >= FEED_DAYS and hours.get(u, 0) >= FEED_HOURS}


def kind_of(records: list[CrmCreation], min_batch: int, feeds: set[str]) -> tuple[str, bool]:
    labels = {r.how for r in records}
    if labels & TOOL_IMPORT:
        return ImportBatch.Kind.BULK, True
    if labels and labels <= TOOL_FEED or (records[0].created_by and records[0].created_by in feeds):
        return ImportBatch.Kind.FEED, bool(labels & TOOL_FEED)
    if len(records) >= min_batch:
        return ImportBatch.Kind.BULK, False
    return (ImportBatch.Kind.HAND if len(records) == 1 else ImportBatch.Kind.SMALL), False


def rebuild(client) -> int:
    """Recomputes the client's batches from its creation records. Returns how many bulk imports there are."""
    gap, min_batch = thresholds()
    with tenant(client), transaction.atomic():
        ImportBatch.objects.filter(client=client, system='crm').delete()
        for source in CrmCreation.objects.filter(client=client).values_list('source_system', flat=True).distinct():
            feeds = feed_users(client.pk, source)
            rows = list(CrmCreation.objects.filter(client=client, source_system=source).order_by('created_by', 'created_at', 'pk'))
            run: list[CrmCreation] = []

            def close():
                if not run:
                    return
                kind, labelled = kind_of(run, min_batch, feeds)
                batch = ImportBatch.objects.create(client=client, source_system=source, created_by=run[0].created_by,
                                                   starts=run[0].created_at, ends=run[-1].created_at, created_count=len(run),
                                                   kind=kind, labelled_by_tool=labelled)
                CrmCreation.objects.filter(pk__in=[r.pk for r in run]).update(batch=batch)

            for r in rows:
                if run and (r.created_by != run[-1].created_by or r.created_at - run[-1].created_at > gap):
                    close()
                    run = []
                run.append(r)
            close()
        return ImportBatch.objects.filter(client=client, kind=ImportBatch.Kind.BULK).count()


def rebuild_all() -> None:
    from apps.clients.models import Client
    with all_clients():
        ids = set(CrmCreation.objects.values_list('client_id', flat=True).distinct())
    from apps.optouts.readded import check_batches
    for client in Client.objects.filter(pk__in=ids):
        rebuild(client)
        with tenant(client):
            check_batches(client)  # M34: opted-out numbers that came back in an upload


def origin(client, phone_token: str, at) -> ImportBatch | None:
    """Where this number came from at a given time: the batch of the latest CRM record created before `at` that holds it."""
    record = (CrmCreation.objects.filter(client=client, phone_tokens__contains=[phone_token], created_at__lte=at, batch__isnull=False)
              .select_related('batch').order_by('-created_at').first())
    return record.batch if record else None
