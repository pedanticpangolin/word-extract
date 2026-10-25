"""The one-pass archive: the source is read once, and ``archive_raw`` is unchanged.

Gate 1 (one read, with a mutation that trips the same check), gate 2 (a verbatim copy of the
pre-P2a ``archive_raw`` produces a byte-identical ``raw/`` and an equal record), gate 3 (crash
safety: no partial blob, no index entry, leftover temp files swept). Every assertion here can
fail -- the mutation tests prove the gates are not vacuous.
"""
from __future__ import annotations

import builtins
import io
import json
import re
import time
from pathlib import Path

import pytest

from docextract_core.archive import RawArchiveRecord, archive_raw, archive_stream
from docextract_core.hashing import content_hash, sha256_stream
from docextract_core.jsonio import read_json, write_json

TMP_PREFIX = ".incoming-"
FROZEN = "2030-01-01T00:00:00Z"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# --- instrumentation --------------------------------------------------------------


class CountingStream:
    """A binary stream that counts every read/seek and every byte returned."""

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)
        self.reads = 0
        self.bytes_read = 0
        self.seeks = 0

    def read(self, n: int = -1) -> bytes:
        block = self._buf.read(n)
        self.reads += 1
        self.bytes_read += len(block)
        return block

    def seek(self, *args: int) -> int:
        self.seeks += 1
        return self._buf.seek(*args)


def _assert_read_once(stream: CountingStream, size: int) -> None:
    assert stream.bytes_read == size, f"read {stream.bytes_read} bytes for a {size}-byte input"
    assert stream.seeks == 0, "the stream was rewound (read more than once)"


def _source_opens(monkeypatch, target: Path) -> list:
    """Count opens of ``target`` through both the builtin and ``io.open`` (Path.open's route)."""
    real_builtin = builtins.open
    real_io = io.open
    counted: list = []

    def wrap(real):
        def inner(file, *args, **kwargs):
            try:
                same = Path(file) == target
            except TypeError:
                same = False
            if same:
                counted.append(file)
            return real(file, *args, **kwargs)

        return inner

    monkeypatch.setattr(builtins, "open", wrap(real_builtin))
    monkeypatch.setattr(io, "open", wrap(real_io))
    return counted


def _assert_source_opened_once(opens: list, read_bytes_calls: list) -> None:
    assert len(opens) == 1, f"the source was opened {len(opens)} times"
    assert read_bytes_calls == [], "Path.read_bytes was called on the source"


@pytest.fixture
def frozen_clock(monkeypatch):
    """Both implementations record ``ingested_at`` from the same fixed clock."""
    monkeypatch.setattr(time, "gmtime", lambda *_a, **_k: 0)
    monkeypatch.setattr(time, "strftime", lambda *_a, **_k: FROZEN)


# --- the pre-P2a implementations, kept as the reference ---------------------------


def _archive_raw_old(root, path, *, mime: str = "", source_system: str = "local") -> RawArchiveRecord:
    """The pre-P2a ``archive_raw``, copied verbatim: hash (read 1), then ``read_bytes`` (read 2)."""
    root = Path(root)
    path = Path(path)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    chash = content_hash(path)
    index_path = raw_dir / "index.json"
    index = read_json(index_path, {})
    if chash in index:
        return RawArchiveRecord(**index[chash])
    dest = raw_dir / f"{chash}{path.suffix.lower()}"
    if not dest.exists():
        dest.write_bytes(path.read_bytes())
    record = RawArchiveRecord(
        content_hash=chash,
        size=path.stat().st_size,
        mime=mime or path.suffix.lower().lstrip("."),
        original_filename=path.name,
        ingested_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        source_system=source_system,
        storage_ref=str(dest.relative_to(root)),
    )
    index[chash] = {**record.__dict__}
    write_json(index_path, index)
    return record


def _archive_stream_two_pass(
    root, stream, *, original_filename, suffix="", mime="", source_system="local"
) -> RawArchiveRecord:
    """A deliberately two-pass stream archive: hash to EOF, then rewind and copy."""
    root = Path(root)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    index_path = raw_dir / "index.json"
    index = read_json(index_path, {})
    chash, size = sha256_stream(stream)
    if chash in index:
        return RawArchiveRecord(**index[chash])
    dest = raw_dir / f"{chash}{suffix.lower()}"
    if not dest.exists():
        stream.seek(0)
        dest.write_bytes(stream.read())
    record = RawArchiveRecord(
        content_hash=chash,
        size=size,
        mime=mime or suffix.lower().lstrip("."),
        original_filename=original_filename,
        ingested_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        source_system=source_system,
        storage_ref=str(dest.relative_to(root)),
    )
    index[chash] = {**record.__dict__}
    write_json(index_path, index)
    return record


# --- gate 1: one read -------------------------------------------------------------


def test_archive_stream_reads_the_source_exactly_once(tmp_path):
    data = b"z" * 5000
    stream = CountingStream(data)
    record = archive_stream(tmp_path / "store", stream, original_filename="a.bin", suffix=".bin")
    assert record.size == len(data)
    _assert_read_once(stream, record.size)
    assert (tmp_path / "store" / record.storage_ref).read_bytes() == data


def test_archive_raw_opens_the_source_once_and_never_read_bytes(tmp_path, monkeypatch):
    src = tmp_path / "doc.docx"
    src.write_bytes(b"hello world")

    opens = _source_opens(monkeypatch, src)
    read_bytes_calls: list = []
    real_read_bytes = Path.read_bytes

    def counting_read_bytes(self):
        read_bytes_calls.append(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

    record = archive_raw(tmp_path / "store", src)
    assert record.size == 11
    _assert_source_opened_once(opens, read_bytes_calls)


def test_the_stream_gate_can_fail(tmp_path):
    data = b"z" * 5000
    stream = CountingStream(data)
    record = _archive_stream_two_pass(
        tmp_path / "store", stream, original_filename="a.bin", suffix=".bin"
    )
    assert record.size == len(data)
    with pytest.raises(AssertionError):
        _assert_read_once(stream, record.size)


def test_the_open_gate_can_fail(tmp_path, monkeypatch):
    src = tmp_path / "doc.docx"
    src.write_bytes(b"hello world")

    opens = _source_opens(monkeypatch, src)
    read_bytes_calls: list = []
    real_read_bytes = Path.read_bytes

    def counting_read_bytes(self):
        read_bytes_calls.append(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

    _archive_raw_old(tmp_path / "store", src)
    assert len(opens) == 2
    assert len(read_bytes_calls) == 1
    with pytest.raises(AssertionError):
        _assert_source_opened_once(opens, read_bytes_calls)


# --- gate 2: archive_raw is unchanged ---------------------------------------------


_FILES = {
    "doc.docx": b"hello world",
    "empty.bin": b"",
    "Report.DOCX": b"upper case suffix bytes",
}


def _raw_tree(root: Path) -> dict[str, bytes]:
    raw = root / "raw"
    return {
        path.relative_to(raw).as_posix(): path.read_bytes()
        for path in sorted(raw.rglob("*"))
        if path.is_file()
    }


def test_archive_raw_matches_the_old_implementation(tmp_path, frozen_clock):
    new_root = tmp_path / "new"
    old_root = tmp_path / "old"
    sources = {}
    for name, data in _FILES.items():
        src = tmp_path / name
        src.write_bytes(data)
        sources[name] = src

    for name, src in sources.items():
        new_first = archive_raw(new_root, src)
        old_first = _archive_raw_old(old_root, src)
        assert new_first == old_first, name
        assert ISO.match(new_first.ingested_at), new_first.ingested_at

        new_second = archive_raw(new_root, src)  # idempotent second call
        old_second = _archive_raw_old(old_root, src)
        assert new_second == old_first, name
        assert old_second == old_first, name

    assert _raw_tree(new_root) == _raw_tree(old_root)
    assert (new_root / "raw" / "index.json").read_bytes() == (
        old_root / "raw" / "index.json"
    ).read_bytes()

    index = json.loads((new_root / "raw" / "index.json").read_text(encoding="utf-8"))
    assert len(index) == len(_FILES)
    by_name = {entry["original_filename"]: entry for entry in index.values()}
    assert by_name["empty.bin"]["size"] == 0
    assert by_name["Report.DOCX"]["storage_ref"].endswith(".docx")


def test_an_existing_unindexed_destination_is_left_alone(tmp_path):
    src = tmp_path / "doc.docx"
    src.write_bytes(b"hello world")
    root = tmp_path / "store"

    first = archive_raw(root, src)
    (root / first.storage_ref).write_bytes(b"tampered")
    (root / "raw" / "index.json").unlink()  # the blob exists but is not indexed

    again = archive_raw(root, src)
    assert again.content_hash == first.content_hash
    assert (root / again.storage_ref).read_bytes() == b"tampered"


# --- gate 3: crash safety ---------------------------------------------------------


class FailsAfter:
    """A stream that yields ``limit`` bytes and then raises (an I/O fault mid-file)."""

    def __init__(self, data: bytes, limit: int) -> None:
        self._data = data
        self._limit = limit
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if self._pos >= self._limit:
            raise RuntimeError("the source failed mid-stream")
        end = min(self._pos + (n if n >= 0 else len(self._data)), self._limit)
        block = self._data[self._pos : end]
        self._pos = end
        return block


def test_a_raising_stream_leaves_no_file_and_no_index_entry(tmp_path):
    root = tmp_path / "store"
    stream = FailsAfter(b"x" * 100, 50)

    with pytest.raises(RuntimeError):
        archive_stream(root, stream, original_filename="a.bin", suffix=".bin")

    raw = root / "raw"
    assert list(raw.iterdir()) == []
    assert not (raw / "index.json").exists()


def test_a_leftover_temp_file_is_swept_by_the_next_call(tmp_path):
    root = tmp_path / "store"
    raw = root / "raw"
    raw.mkdir(parents=True)
    dead = raw / f"{TMP_PREFIX}deadbeefdeadbeef"
    dead.write_bytes(b"partial bytes from a hard kill")

    src = tmp_path / "a.bin"
    src.write_bytes(b"payload")
    record = archive_raw(root, src)

    assert not dead.exists()
    assert (root / record.storage_ref).read_bytes() == b"payload"


def test_two_archives_leave_no_temp_file(tmp_path):
    root = tmp_path / "store"
    for name, data in {"a.bin": b"one", "b.bin": b"two"}.items():
        src = tmp_path / name
        src.write_bytes(data)
        archive_raw(root, src)

    raw = root / "raw"
    assert list(raw.glob(f"{TMP_PREFIX}*")) == []
    blobs = [path for path in raw.iterdir() if path.name != "index.json"]
    assert len(blobs) == 2


def test_two_identical_files_leave_one_stored_copy(tmp_path):
    root = tmp_path / "store"
    a = tmp_path / "a.bin"
    a.write_bytes(b"same bytes")
    b = tmp_path / "b.bin"
    b.write_bytes(b"same bytes")

    first = archive_raw(root, a)
    second = archive_raw(root, b)

    assert second == first  # the second call returns the existing record
    raw = root / "raw"
    index = json.loads((raw / "index.json").read_text(encoding="utf-8"))
    assert len(index) == 1
    blobs = [path for path in raw.iterdir() if path.name != "index.json"]
    assert len(blobs) == 1
    assert blobs[0].read_bytes() == b"same bytes"


def test_archive_stream_is_idempotent_and_discards_its_temp(tmp_path):
    root = tmp_path / "store"
    first = archive_stream(root, io.BytesIO(b"data"), original_filename="a", suffix=".bin")
    index_before = (root / "raw" / "index.json").read_bytes()

    second = archive_stream(root, io.BytesIO(b"data"), original_filename="a", suffix=".bin")

    assert second == first
    assert (root / "raw" / "index.json").read_bytes() == index_before
    assert list((root / "raw").glob(f"{TMP_PREFIX}*")) == []
