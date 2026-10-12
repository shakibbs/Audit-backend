"""The nightly seal: each client's fingerprints from each finished day → one root, then outside stamps."""
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client
from apps.ledger.models import Fingerprint
from apps.tenancy.scope import all_clients, tenant

from . import stamps
from .merkle import build, fold, leaf_hash
from .models import MerkleAnchor


def seal_day(client, day) -> MerkleAnchor | None:
    with tenant(client):
        return _seal_day(client, day)


def _seal_day(client, day) -> MerkleAnchor | None:
    rows = list(Fingerprint.objects.filter(client=client, anchor__isnull=True, fetched_at__date=day).order_by('id'))
    if not rows:
        return None
    root, paths = build([leaf_hash(fp) for fp in rows])
    with transaction.atomic():
        anchor = MerkleAnchor.objects.create(client=client, day=day, leaf_count=len(rows), root=root.hex())
        for i, (fp, path) in enumerate(zip(rows, paths)):
            fp.anchor, fp.leaf_index, fp.merkle_path = anchor, i, path
        Fingerprint.objects.bulk_update(rows, ['anchor', 'leaf_index', 'merkle_path'], batch_size=2000)
    stamp(anchor)
    return anchor


def seal_finished_days() -> list[MerkleAnchor]:
    """Every day before today (UTC) that still has unsealed fingerprints, per client. Today is sealed tomorrow."""
    today = timezone.now().date()
    with all_clients():
        pending = list(Fingerprint.objects.filter(anchor__isnull=True, fetched_at__date__lt=today)
                       .values_list('client', 'fetched_at__date').distinct())
    clients = Client.objects.in_bulk({c for c, _ in pending})
    return [a for c, day in sorted(set(pending)) if (a := seal_day(clients[c], day))]


def stamp(anchor: MerkleAnchor) -> None:
    """Adds whichever outside stamps are still missing. A failure is retried later; the root is already kept."""
    root = bytes.fromhex(anchor.root)
    if anchor.tsa_response is None:
        try:
            anchor.tsa_url, anchor.tsa_response, anchor.tsa_time = stamps.tsa_stamp(root)
        except stamps.StampFailed:
            pass
    if anchor.ots_proof is None:
        try:
            anchor.ots_calendar, anchor.ots_proof = stamps.ots_stamp(root)
        except stamps.StampFailed:
            pass
    anchor.save(update_fields=['tsa_url', 'tsa_response', 'tsa_time', 'ots_calendar', 'ots_proof'])


def verify(fp: Fingerprint) -> str:
    """'matches' (unchanged since its seal), 'changed' (the row was altered), or 'not_sealed' (read today)."""
    if fp.anchor_id is None:
        return 'not_sealed'
    with tenant(fp.client_id):
        root = MerkleAnchor.objects.get(pk=fp.anchor_id).root
    return 'matches' if fold(leaf_hash(fp), fp.merkle_path).hex() == root else 'changed'
