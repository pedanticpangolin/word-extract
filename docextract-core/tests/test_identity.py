"""Identity is defined once: the stream, the file, ``hashlib`` and the archive all agree.

Gate C of hub Turn P2a. ``sha256_stream`` is the definition, ``content_hash`` the
file-shaped form, and ``archive_stream`` keys its record by the same digest. If any two of
them disagreed on any byte string the whole content-addressed design is unsound, so the test
walks the chunk boundaries (empty, one byte, exactly one chunk, one chunk plus one, 3 MiB).
"""
from __future__ import annotations

import hashlib
import io
import random

import pytest

from docextract_core import archive_stream, content_hash, sha256_stream

CHUNK = 1 << 20

#: The known digests pin ``sha256_stream`` to *the real sha256*, so a stream implementation
#: that merely agrees with itself cannot pass. Hand-derived, not copied from the code.
KNOWN = {
    b"": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    b"A": "559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd",
}


def _blob(n: int, seed: int = 20261010) -> bytes:
    """``n`` bytes that do not repeat, deterministic across runs (never ``os.urandom``)."""
    return random.Random(seed).randbytes(n)


CORPUS = {
    "empty": b"",
    "one_byte": b"A",
    "exactly_one_chunk": _blob(CHUNK),
    "one_chunk_plus_one": _blob(CHUNK + 1),
    "three_mib": _blob(3 * CHUNK),
}


def test_the_known_digests_are_the_real_sha256():
    assert sha256_stream(io.BytesIO(b"")) == (KNOWN[b""], 0)
    assert sha256_stream(io.BytesIO(b"A")) == (KNOWN[b"A"], 1)


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_the_four_identities_agree(name, tmp_path):
    data = CORPUS[name]

    digest, count = sha256_stream(io.BytesIO(data))
    assert count == len(data)

    path = tmp_path / f"{name}.bin"
    path.write_bytes(data)
    assert content_hash(path) == digest

    record = archive_stream(
        tmp_path / "store", io.BytesIO(data), original_filename=name, suffix=".bin"
    )
    assert record.content_hash == digest
    assert record.size == len(data)

    assert digest == hashlib.sha256(data).hexdigest()
