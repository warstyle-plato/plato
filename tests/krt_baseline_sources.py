"""Exact public Git-code fixtures; no ambient Git, network or fallback at runtime."""
from pathlib import Path
import hashlib

_ROOT = Path(__file__).resolve().parent / "fixtures" / "krt_baselines"
_SOURCES = {
    ('e31324f813335157efa97e1e162b7f0c8eecb53d', 'http'): ('http-e31324f8.source', 6655, '4dc23f49946a624df974113de37c3dc5c182c8b466b89f8850129fb7f1c0d957'),
    ('e31324f813335157efa97e1e162b7f0c8eecb53d', 'krt_registry'): ('krt_registry-e31324f8.source', 131522, '4ea9026a6eaf71d2407b5f063893658e9775ec3800110023bd2730225d5fd511'),
    ('8139471534871b4f5142d389e4ed21f0fede7f98', 'http'): ('http-e31324f8.source', 6655, '4dc23f49946a624df974113de37c3dc5c182c8b466b89f8850129fb7f1c0d957'),
    ('8139471534871b4f5142d389e4ed21f0fede7f98', 'krt_registry'): ('krt_registry-81394715.source', 133125, 'ae4033e5550e3be8d2cda24f0d350633e95cd16ca580c5867a8d5694e33672ed'),
}


def source_bytes(revision: str, name: str) -> bytes:
    if type(revision) is not str or type(name) is not str or (revision, name) not in _SOURCES:
        raise ValueError("Unknown pinned public baseline")
    filename, size, expected = _SOURCES[(revision, name)]
    with (_ROOT / filename).open("rb") as source:
        raw = source.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
        raise AssertionError("Pinned public baseline bytes differ")
    return raw
