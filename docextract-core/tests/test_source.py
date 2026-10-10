"""Source-side materials: behaviour parity with email's originals, and the Source protocol.

``FileMaterial``/``PathMaterial``/``MemoryMaterial``/``memory_bytes`` were moved here from
``emailextract/container.py`` unchanged (hub Turn P2a). These assert the behaviour, including
the two edges the move must not lose: the strict-UTF-8 text view and the ``bytes``-only
constructor. (The byte-for-byte *parity* with the email originals is a throwaway script whose
comparison is pasted into ``docs/design/hub-P2a-note.md``; importing email here would make a
committed test depend on a sibling repo.)
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from docextract_core import (
    FileMaterial,
    MemoryMaterial,
    MemorySource,
    PathMaterial,
    Source,
    SourceItem,
    memory_bytes,
)


def test_path_material_reads_bytes_and_a_strict_utf8_text_view(tmp_path):
    path = tmp_path / "a.txt"
    raw = "h\u00e9llo".encode("utf-8")
    path.write_bytes(raw)

    material = PathMaterial(path)
    assert material.size() == len(raw)
    assert material.read_bytes() == raw
    assert material.open_text().read() == "h\u00e9llo"


def test_path_material_text_view_is_strict_utf8(tmp_path):
    path = tmp_path / "bad.bin"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(UnicodeDecodeError):
        PathMaterial(path).open_text().read()


def test_memory_material_matches_the_documented_shape():
    data = b"payload"
    material = memory_bytes(data)
    assert isinstance(material, MemoryMaterial)
    assert isinstance(material, FileMaterial)
    assert material.size() == len(data)
    assert material.read_bytes() == data
    assert material.open_text().read() == "payload"


def test_memory_material_text_view_is_strict_utf8():
    with pytest.raises(UnicodeDecodeError):
        MemoryMaterial(b"\xff\xfe").open_text()


def test_memory_material_rejects_a_non_bytes_constructor_arg():
    with pytest.raises(TypeError, match="memory material takes bytes, got str"):
        MemoryMaterial("a string")
    with pytest.raises(TypeError, match="memory material takes bytes, got bytearray"):
        MemoryMaterial(bytearray(b"x"))
    with pytest.raises(TypeError):
        MemoryMaterial(memoryview(b"x"))


def test_file_material_is_a_runtime_checkable_protocol(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"x")
    assert isinstance(PathMaterial(path), FileMaterial)
    assert isinstance(memory_bytes(b"x"), FileMaterial)
    assert not isinstance(object(), FileMaterial)


def test_source_item_copies_its_provenance_and_is_frozen():
    provenance = {"revisionId": "r1", "produced_by": "local"}
    item = SourceItem(material=memory_bytes(b"x"), locator="drive://fid", provenance=provenance)

    provenance["revisionId"] = "mutated-by-the-caller"
    assert dict(item.provenance) == {"revisionId": "r1", "produced_by": "local"}
    assert item.provenance is not provenance
    assert item.locator == "drive://fid"

    with pytest.raises(FrozenInstanceError):
        item.locator = "somewhere-else"


def test_memory_source_is_a_source_and_yields_its_items():
    item = SourceItem(material=memory_bytes(b"x"), locator="L", provenance={})
    source = MemorySource("mem", [item])
    assert isinstance(source, Source)
    assert (source.name, source.bytes_durable, source.can_reread) == ("mem", True, True)
    assert list(source.items()) == [item]
