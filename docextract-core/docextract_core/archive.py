"""Content-addressed archives for raw inputs and LLM I/O (no rewrite on hit)."""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from .hashing import sha256_text
from .jsonio import read_json, write_json

#: Prefix of the temp file the archive streams into before its hash is known. A stored
#: blob is ``<content_hash><suffix>`` and always begins with a hex digit, so a name that
#: begins with ``.`` cannot be one -- the prefix is both collision-proof and the marker a
#: later call recognises to sweep a leftover.
_TMP_PREFIX = ".incoming-"


@dataclass
class RawArchiveRecord:
    content_hash: str
    size: int
    mime: str
    original_filename: str
    ingested_at: str
    source_system: str = "local"
    storage_ref: str = ""


@dataclass
class LLMCall:
    call_id: str
    purpose: str
    model: str
    params: dict[str, Any]
    prompt_hash: str
    prompt_ref: str
    response_ref: str
    tokens: int | None = None
    latency_ms: int | None = None


def _sweep_leftovers(raw_dir: Path) -> None:
    """Remove ``.incoming-*`` temp files a previous call left behind.

    A hard kill (power loss, SIGKILL) between creating the temp file and renaming it into
    place leaves one behind; the next archive call on the same root removes it. This is a
    single-writer rule: a *concurrent* archive on the same root would delete another call's
    in-progress temp file, so v1 archives one root from one process (the router's
    single-user v1, debate section 4).
    """
    for leftover in raw_dir.glob(f"{_TMP_PREFIX}*"):
        try:
            leftover.unlink()
        except FileNotFoundError:
            pass


def archive_stream(
    root: str | Path,
    stream: BinaryIO,
    *,
    original_filename: str,
    suffix: str = "",
    mime: str = "",
    source_system: str = "local",
) -> RawArchiveRecord:
    """Copy a binary ``stream`` under ``<root>/raw/<content_hash><suffix.lower()>``.

    Reads ``stream`` **once, sequentially**, hashing while it writes to a temp file inside
    ``<root>/raw/``, counting the bytes, then renaming the temp file to the destination
    atomically. This is what fixes the double read of :func:`archive_raw`'s old path form:
    a non-path source (a Drive export, an already-open stream) can be archived without a
    temp file, and a path is read once.

    Idempotent exactly as :func:`archive_raw` is: if the hash is already in
    ``raw/index.json`` the existing record is returned, the temp file is discarded and
    nothing else is written; if the destination exists but is not indexed, its bytes are
    left alone and the record is added to the index.

    A failure at any point (an exception, a ``KeyboardInterrupt``) removes the temp file
    and leaves the index untouched. A leftover temp file from a hard kill is removed by the
    next :func:`archive_stream` / :func:`archive_raw` call on that root (see
    :func:`_sweep_leftovers`).
    """
    root = Path(root)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    _sweep_leftovers(raw_dir)
    index_path = raw_dir / "index.json"
    index = read_json(index_path, {})
    tmp = raw_dir / f"{_TMP_PREFIX}{uuid.uuid4().hex}"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                block = stream.read(1 << 20)
                if not block:
                    break
                digest.update(block)
                out.write(block)
                size += len(block)
        chash = digest.hexdigest()
        if chash in index:
            return RawArchiveRecord(**index[chash])
        dest = raw_dir / f"{chash}{suffix.lower()}"
        if not dest.exists():
            os.replace(tmp, dest)
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
    finally:
        if tmp.exists():
            tmp.unlink()


def archive_raw(
    root: str | Path,
    path: str | Path,
    *,
    mime: str = "",
    source_system: str = "local",
) -> RawArchiveRecord:
    """Copy ``path`` under ``<root>/raw/<content_hash><suffix>``; idempotent.

    A thin wrapper over :func:`archive_stream`: it opens ``path`` exactly once and streams
    it, so the file is read once, not twice (the old form hashed it, then read it again).
    """
    path = Path(path)
    with open(path, "rb") as stream:
        return archive_stream(
            root,
            stream,
            original_filename=path.name,
            suffix=path.suffix,
            mime=mime,
            source_system=source_system,
        )


def archive_llm_call(
    root: str | Path,
    *,
    purpose: str,
    model: str,
    params: dict[str, Any],
    prompt: str,
    response: str,
    tokens: int | None = None,
    latency_ms: int | None = None,
) -> LLMCall:
    """Write prompt/response under content-addressed paths; existing files are left alone."""
    root = Path(root)
    llm_dir = root / "llm"
    prompt_dir = llm_dir / "prompts"
    response_dir = llm_dir / "responses"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    response_dir.mkdir(parents=True, exist_ok=True)
    prompt_hash = sha256_text(prompt)
    response_hash = sha256_text(response)
    prompt_path = prompt_dir / f"{prompt_hash}.txt"
    response_path = response_dir / f"{response_hash}.txt"
    if not prompt_path.exists():
        prompt_path.write_text(prompt, encoding="utf-8")
    if not response_path.exists():
        response_path.write_text(response, encoding="utf-8")
    return LLMCall(
        call_id=uuid.uuid4().hex,
        purpose=purpose,
        model=model,
        params=dict(params),
        prompt_hash=prompt_hash,
        prompt_ref=str(prompt_path.relative_to(root)),
        response_ref=str(response_path.relative_to(root)),
        tokens=tokens,
        latency_ms=latency_ms,
    )
