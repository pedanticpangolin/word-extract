# Hub Turn P2a: `Source`, `FileMaterial` and the one-pass archive stream, in `docextract-core`

Status: brief for one build turn. Author: reviewer session, 2026-10-10. Builder: hearth, **run from the
`word-extract` repository** (core lives at `docextract-core/` here). This is the hub programme's first and only
turn that changes a shipped sibling; it was approved as owner decisions 2, 4 and 8 of the platform debate
(`docextract-hub/docs/design/platform-router-debate.md` sections 3, 10, 11 and 17; a copy of the debate is at
`../docextract-hub/docs/design/` for reading, do not edit it). The change is **additive** and one existing
function is re-implemented with identical results.

## Why

1. The hub needs a place to promote `Source`/`FileMaterial` so a Drive adapter depends on core only (Q4).
   `FileMaterial`, `PathMaterial`, `MemoryMaterial` and `memory_bytes` exist in `email-extract`
   (`emailextract/container.py:11-45,86-90`) and workbook re-implements the idea as `_as_bytes`
   (`reader/workbook.py`, accepts `str | Path | bytes`).
2. `docextract_core.archive_raw` reads each file **twice**: once to hash (`content_hash(path)`, `archive.py:50`)
   and once to copy (`path.read_bytes()`, `archive.py:57`), and it takes a path, so a non-path source (a Drive
   export, a stream) cannot be archived without a temp file. On a spinning-disk NAS the second read is a real
   cost (Q8).

## What to build

### A. `docextract_core/source.py` (new, standard library only)

- `FileMaterial` (runtime-checkable Protocol: `size()`, `open_text()`, `read_bytes()`), `PathMaterial`,
  `MemoryMaterial`, `memory_bytes(data)`: **the same behaviour as email's**, moved, not redesigned (read the
  email originals; reproduce the UTF-8-strict text view and the `bytes`-only constructor check exactly). Add
  `open_binary()` to the protocol only if you can do it without breaking email's implementations (email does
  not import core yet and is **not** changed this turn); if you need it for Part B, put it on the new classes
  and make the Protocol member optional via a second protocol `StreamableMaterial`; say what you chose.
- `SourceItem`: a frozen dataclass `(material: FileMaterial, locator: str, provenance: Mapping[str, str])`.
  `locator` and `provenance` are **claims, never identity** (debate section 3); say so in the docstring. The
  mapping must be immutable-by-convention and copied on construction.
- `Source`: a runtime-checkable Protocol with `name: str`, `bytes_durable: bool`, `can_reread: bool` and
  `items() -> Iterator[SourceItem]`. `bytes_durable` is the precondition for any future reference mode
  (Q4); `can_reread` is what the router uses to label a citation `resolvable | unresolvable`. No concrete
  `Source` implementation in this turn except a trivial in-memory `MemorySource` used by the tests; the local
  folder source is Turn P4a.
- Export them from `docextract_core/__init__.py` and `__all__`.

### B. `archive_stream` and `archive_raw` (in `archive.py`)

`archive_stream(root, stream, *, original_filename, suffix="", mime="", source_system="local") ->
RawArchiveRecord`: reads `stream` (a binary file object) **once, sequentially**, hashing while writing to a
temp file inside `<root>/raw/` (a name pattern that cannot collide with a `<hash><suffix>` file and that a later
call can recognise as a leftover), counting the bytes, then renaming to `<hash><suffix.lower()>` atomically.
Idempotent exactly as `archive_raw` is: if the hash is already in `raw/index.json`, return the existing record,
discard the temp file, and write nothing else; if the destination exists but is not indexed, behave as
today. A failure at any point (exception, `KeyboardInterrupt`) removes the temp file and leaves `raw/` and the
index untouched. A leftover temp file from a hard kill is removed by the next `archive_stream`/`archive_raw`
call on that root (state the rule in the docstring).

`archive_raw(root, path, *, mime, source_system)` becomes a thin wrapper: open `path` once and call
`archive_stream`, passing `original_filename=path.name` and `suffix=path.suffix`. **Its results must be
identical to today's**: same `RawArchiveRecord` fields (`content_hash`, `size`, `mime` default,
`original_filename`, `source_system`, `storage_ref` as `raw/<hash><suffix.lower()>`, `ingested_at` format), same
index contents, same on-disk bytes, same idempotence. `ingested_at` stays a recorded-only clock value, exactly as
today (do not change it or add a new clock use).

### C. Identity is defined once

Add `sha256_stream(stream, chunk=1 << 20) -> tuple[str, int]` (hex digest and byte count) and make
`content_hash(path)` call it; `content_hash`'s output is unchanged. In the module docstring and the core README
state the rule from the platform debate: **a document's identity is the sha256 of its raw bytes, defined here
once; a family must not hash a projection under this name.** Add a test that `sha256_stream`,
`content_hash(path)`, `hashlib.sha256(bytes)` and `archive_stream`'s record agree on a corpus of byte strings
(empty, one byte, exactly one chunk, one chunk plus one, 3 MiB of non-repeating bytes).

## Gates (each must be able to fail; write the falsifiability case)

1. **One read.** Instrument the stream (a wrapper counting `read`/`readinto` calls and total bytes returned)
   and `Path.read_bytes`/`builtins.open` for the archive call: `archive_stream` consumes the stream **exactly
   once to EOF** (total bytes read == size), and `archive_raw(path)` opens the file **once** and never calls
   `read_bytes`. A mutation test (monkeypatched old implementation, or a copy of the old function under a test
   name) must fail the same assertion, proving the gate can fail.
2. **`archive_raw` is unchanged.** Run the old implementation (copied verbatim into the test as a reference)
   and the new one over the same files in two scratch roots: the returned records match field for field (except
   `ingested_at`, compared by format only), the two `raw/` directories are byte-identical, and the two
   `index.json` files are equal. Include the idempotent second call and a zero-byte file and a file with an
   upper-case suffix.
3. **Crash safety.** A stream that raises after N bytes leaves no file and no index entry; a simulated hard kill
   (create the temp file and stop) is cleaned by the next call; two different files archived in sequence leave
   no temp files; two identical files archived twice leave one stored copy.
4. **Material parity.** `PathMaterial`/`MemoryMaterial`/`memory_bytes` behave as email's do on the same inputs
   (import email's module in a throwaway script, not in a committed test; paste the comparison result into the
   note) including the strict UTF-8 error on an invalid byte and the `TypeError` on non-bytes.
5. **Purity.** `docextract_core` still imports only the standard library (add or extend the existing contract
   test if one exists), has no network, subprocess or clock use beyond today's `ingested_at`.

## Versions and ledger

`CORE_VERSION` moves `"0.1.0"` -> `"0.2.0"` (additive API). Run word-extract's
`python tools/update_behavior_ledger.py --check` before and after: report whether the `contracts` fingerprint
moves (it covers `SCHEMA_VERSION`, the core records and the codec envelope). `source.py`'s `SourceItem` is a new
core record: decide whether it belongs in `CORE_RECORDS`, defend it, and if the fingerprint moves record exactly
the line the updater predicts and explain why; if the updater wants any other line, **stop and explain before
accepting it**. `SCHEMA_VERSION` must not move.

## Stop line

Touch only: `docextract-core/docextract_core/` (`source.py` new, `archive.py`, `hashing.py`, `__init__.py`),
`docextract-core/tests/` (new files; existing only where a version literal forces it, each justified),
`docextract-core/README.md`, `tools/behavior_ledger.py` / `tests/ledger/**` **only** via the updater and only if
the fingerprint moves, `docs/design/hub-P2a-note.md` (the outcome note, new). **Do not touch:** any family module
(`wordextract/**`), `form-extract`, `email-extract`, `workbook-extract`, `docextract-hub`, `docextract-core/build/`
(untracked build output), `CLAUDE.md`, any fixture or sidecar. No network. Python 3.11 to 3.14. No new
dependency. Do not commit.

## Running it

Use the interpreter and layout this repo documents (`pip install -e docextract-core -e ".[dev]"` in a venv
outside the repo, or `PYTHONPATH="docextract-core;."`). Core's tests alone first, then word-extract's full
suite (about 40 s) on 3.14 and 3.11. Then prove the other families are unaffected: run `workbook-extract`'s
`python tools/check_suite.py` (it uses core's codec) with `OPENPYXL_LXML` unset, using that repo's documented
interpreter, and report the result; do not edit anything there. `email-extract` and `form-extract` do not import
core's archive today: confirm by `grep` and say so.

## Deliverable

The code and tests, and `docs/design/hub-P2a-note.md`: what moved from email and what was kept identical; the
one-read instrumentation and its mutation; the `archive_raw` equivalence evidence; the crash cases; the
version/ledger outcome; the material-parity comparison pasted; and anything not covered that needs a decision.
If anything needs a decision, write it in the note and stop.
