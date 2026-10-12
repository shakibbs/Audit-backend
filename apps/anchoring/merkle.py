"""Merkle tree: many fingerprints → one root hash. Each fingerprint keeps its path to the root, so it can be checked alone.
Leaves and nodes get different prefixes (0x00, 0x01) so a node can never pass as a leaf."""
import hashlib
from datetime import UTC


def leaf_hash(fp) -> bytes:
    """Seals the fingerprint and its details (client, tool, record ID, kind, grade, read time), not only the hash."""
    parts = [str(fp.client_id), fp.source_system, fp.source_record_id, fp.content_kind, fp.source_grade, fp.sha256,
             fp.fetched_at.astimezone(UTC).isoformat(timespec='microseconds')]
    return hashlib.sha256(b'\x00' + '|'.join(parts).encode()).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b'\x01' + left + right).digest()


def build(leaves: list[bytes]) -> tuple[bytes, list[list[list[str]]]]:
    """Returns the root and, for each leaf, its path: [side of the sibling ('L' or 'R'), sibling hash]."""
    paths: list[list[list[str]]] = [[] for _ in leaves]
    level = [(h, [i]) for i, h in enumerate(leaves)]  # (hash, leaves under it)
    while len(level) > 1:
        up = []
        for i in range(0, len(level) - 1, 2):
            (left, under_l), (right, under_r) = level[i], level[i + 1]
            for leaf in under_l:
                paths[leaf].append(['R', right.hex()])
            for leaf in under_r:
                paths[leaf].append(['L', left.hex()])
            up.append((node_hash(left, right), under_l + under_r))
        if len(level) % 2:  # an odd one out moves up unchanged
            up.append(level[-1])
        level = up
    return level[0][0], paths


def fold(leaf: bytes, path: list[list[str]]) -> bytes:
    """Walks a leaf up its path to the root."""
    current = leaf
    for side, sibling in path:
        other = bytes.fromhex(sibling)
        current = node_hash(other, current) if side == 'L' else node_hash(current, other)
    return current
