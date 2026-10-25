"""Content-addressed hashing primitives (sha256).

**A document's identity is the sha256 of its raw bytes, defined here once**
(platform debate, owner decision 2): :func:`sha256_stream` is that definition and
:func:`content_hash` is its file-shaped form. A family must not hash a *projection*
(a text view, a rendered form, a container's own summary of itself) under this name --
a projection is derived from the bytes, the identity is the bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import BinaryIO


def sha256_stream(stream: BinaryIO, chunk: int = 1 << 20) -> tuple[str, int]:
    """The sha256 hex digest of ``stream``'s bytes and how many bytes were read.

    Reads the stream once, sequentially, in ``chunk``-byte blocks until EOF. This is
    the one definition of a document's identity; :func:`content_hash` and
    :func:`docextract_core.archive.archive_stream` both build on it, so all three can
    never disagree about what a byte string hashes to.
    """
    h = hashlib.sha256()
    total = 0
    while True:
        block = stream.read(chunk)
        if not block:
            break
        h.update(block)
        total += len(block)
    return h.hexdigest(), total


def content_hash(path: str | Path) -> str:
    """sha256 of a file's bytes, streamed in 1 MiB chunks."""
    with open(path, "rb") as fh:
        digest, _ = sha256_stream(fh)
    return digest


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj) -> str:
    """sha256 of the canonical (sorted-key) JSON encoding of ``obj``."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_text(payload)
