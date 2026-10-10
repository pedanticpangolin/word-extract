"""Source-side materials: the bytes, where they came from, and how to read them.

Promoted from ``emailextract/container.py`` (hub Turn P2a): ``FileMaterial``,
``PathMaterial``, ``MemoryMaterial`` and ``memory_bytes`` are moved here, behaviour
unchanged, so a source adapter (a local folder, a Drive export) depends on core only
and never on an extractor.

**Identity is the sha256 of the raw bytes** (:func:`docextract_core.hashing.content_hash`,
defined once in this package). A :class:`SourceItem`'s ``locator`` and ``provenance``
are **claims, never identity**: a path, a name, a Drive revision id or a container's own
summary of itself may say where bytes were found, but none of them stands in for the
sha256 a family must not re-derive from a projection.
"""
from __future__ import annotations

import io
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "FileMaterial",
    "MemoryMaterial",
    "MemorySource",
    "PathMaterial",
    "Source",
    "SourceItem",
    "memory_bytes",
]


@runtime_checkable
class FileMaterial(Protocol):
    """The input protocol: a file's bytes, never its meaning."""

    def size(self) -> int: ...

    def open_text(self) -> io.TextIOBase: ...

    def read_bytes(self) -> bytes: ...


class PathMaterial:
    """A file on disk, read as bytes; the text view decodes UTF-8 strictly."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def size(self) -> int:
        return self.path.stat().st_size

    def open_text(self) -> io.TextIOBase:
        return self.path.open("r", encoding="utf-8", newline="")

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


class MemoryMaterial:
    """Bytes held in memory -- the second route every input test also takes."""

    def __init__(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError(f"memory material takes bytes, got {type(data).__name__}")
        self._data = data

    def size(self) -> int:
        return len(self._data)

    def open_text(self) -> io.TextIOBase:
        return io.StringIO(self._data.decode("utf-8"))

    def read_bytes(self) -> bytes:
        return self._data


def memory_bytes(data: bytes) -> MemoryMaterial:
    """The in-memory FileMaterial, named the way tests call it."""
    return MemoryMaterial(data)


@dataclass(frozen=True)
class SourceItem:
    """One thing a :class:`Source` yielded: its bytes and two *claims* about them.

    ``locator`` (a path, a URL, a Drive file id) and ``provenance`` (``modifiedTime``,
    ``revisionId``, ``produced_by``, ...) are recorded-only: they say where the bytes
    were found, never what they are. Identity is the sha256 of the raw bytes. The
    mapping is copied on construction and is immutable by convention -- mutate the
    mapping you passed in, not the item's private copy of it.
    """

    material: FileMaterial
    locator: str
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", dict(self.provenance))


@runtime_checkable
class Source(Protocol):
    """A place documents come from: a local folder (Turn P4a), a Drive export, or a double.

    ``bytes_durable`` is the precondition for any future reference mode -- a citation may
    be resolved later only if the bytes are durable; ``can_reread`` is what the router uses
    to label a citation ``resolvable | unresolvable``. Neither is identity.
    """

    name: str
    bytes_durable: bool
    can_reread: bool

    def items(self) -> Iterator[SourceItem]: ...


class MemorySource:
    """A trivial in-memory :class:`Source`: the protocol's test double (no I/O, durable)."""

    bytes_durable = True
    can_reread = True

    def __init__(self, name: str, items: Iterable[SourceItem] = ()) -> None:
        self.name = name
        self._items = list(items)

    def items(self) -> Iterator[SourceItem]:
        return iter(self._items)
