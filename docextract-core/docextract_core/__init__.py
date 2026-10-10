"""Shared document-extraction substrate (``docextract-core``).

Substrate only: hashing, the dataclass codec, JSON I/O, content-addressed
archives, the source-side materials and protocols, the LLM client protocol, and a
provisional record collection. Domain records, provenance, metrics and indexing live
in the consumers, never here.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .archive import (
    LLMCall,
    RawArchiveRecord,
    archive_llm_call,
    archive_raw,
    archive_stream,
)
from .codec import CodecError, SCHEMA_VERSION, decode, encode, from_json, to_json
from .collection import Collection, ReadOnlyError
from .hashing import content_hash, sha256_json, sha256_stream, sha256_text
from .jsonio import read_json, write_json
from .llm import LLMClient, LLMResponse
from .source import (
    FileMaterial,
    MemoryMaterial,
    MemorySource,
    PathMaterial,
    Source,
    SourceItem,
    memory_bytes,
)

# Stays "0.1.0" through the hub P2a additions (Source, FileMaterial, archive_stream, sha256_stream): they
# are additive, and workbook-extract stamps this constant into its `contracts` fingerprint
# (tools/behavior_ledger.py envelope), so a bump here turns that repo's ledger gate red without any
# manifest change. Move it in a turn that also decouples that fingerprint from the core version.
CORE_VERSION = "0.1.0"

__all__ = [
    "CORE_VERSION",
    "SCHEMA_VERSION",
    "git_revision",
    "CodecError",
    "encode",
    "decode",
    "to_json",
    "from_json",
    "read_json",
    "write_json",
    "content_hash",
    "sha256_stream",
    "sha256_text",
    "sha256_json",
    "archive_raw",
    "archive_stream",
    "archive_llm_call",
    "RawArchiveRecord",
    "LLMCall",
    "FileMaterial",
    "PathMaterial",
    "MemoryMaterial",
    "memory_bytes",
    "SourceItem",
    "Source",
    "MemorySource",
    "LLMClient",
    "LLMResponse",
    "Collection",
    "ReadOnlyError",
]


def git_revision(start: str | Path | None = None) -> str | None:
    """Current git HEAD for the repo containing ``start``, or None outside one."""
    cwd = str(start or Path(__file__).resolve().parent)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    revision = result.stdout.strip()
    return revision or None
