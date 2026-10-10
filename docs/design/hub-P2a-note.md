# Hub Turn P2a outcome: `Source`/`FileMaterial` and the one-pass archive stream

Turn: hub Turn P2a, brief at `docs/design/hub-P2a-brief.md`. Built in `docextract-core/` of this
repo (`word-extract`), additive, standard library only, Python 3.11 to 3.14. **Not committed.**

## What shipped

- `docextract-core/docextract_core/source.py` (new): `FileMaterial` (Protocol), `PathMaterial`,
  `MemoryMaterial`, `memory_bytes`, `SourceItem`, `Source` (Protocol), `MemorySource`.
- `docextract-core/docextract_core/archive.py`: `archive_stream` (new) and the pre-existing
  `_sweep_leftovers`; `archive_raw` re-implemented as a thin wrapper over `archive_stream`.
- `docextract-core/docextract_core/hashing.py`: `sha256_stream` (new); `content_hash` now calls it.
- `docextract-core/docextract_core/__init__.py`: new names exported; `CORE_VERSION` 0.1.0 -> 0.2.0.
- `docextract-core/README.md`: the identity rule and a "Sources and archives" paragraph.
- tests (new): `docextract-core/tests/test_source.py`, `test_archive_stream.py`,
  `test_identity.py`, `test_purity.py`.

## A. Materials: what moved from email, what stayed identical

`FileMaterial`, `PathMaterial`, `MemoryMaterial` and `memory_bytes` are a **verbatim copy** of
`email-extract/emailextract/container.py:36-83` (the `FileMaterial` three-method Protocol, the two
concrete classes, and the factory). Nothing was redesigned. `container.py`'s private
`_material_of` helper (lines 86-93) is *not* part of the protocol and was not moved; email is not
changed this turn and still does not import core.

**`open_binary` / `StreamableMaterial`: neither was added.** `archive_stream` takes a
caller-opened binary stream and never needs a material to expose one, so the `FileMaterial`
Protocol is exactly email's three methods and no second protocol exists. (This is the choice the
brief asked to be stated.)

### Gate 4 -- material parity (throwaway script, pasted)

Run with `python .scratch/p2a/parity.py` (scratch, git-ignored; imports the sibling email package
so it is *not* a committed test). Every case compares core's result to email's on the same input:

```
SAME PathMaterial.size                  core=('ok', 6)  email=('ok', 6)
SAME PathMaterial.read_bytes            core=('ok', b'h\xc3\xa9llo')  email=('ok', b'h\xc3\xa9llo')
SAME PathMaterial.open_text             core=('ok', 'héllo')  email=('ok', 'héllo')
SAME PathMaterial strict utf8           core=('UnicodeDecodeError', "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte")  email=(same)
SAME MemoryMaterial.size                core=('ok', 2)  email=('ok', 2)
SAME MemoryMaterial.read_bytes          core=('ok', b'xy')  email=('ok', b'xy')
SAME MemoryMaterial.open_text           core=('ok', 'xy')  email=('ok', 'xy')
SAME MemoryMaterial strict utf8         core=('UnicodeDecodeError', ...)  email=(same)
SAME MemoryMaterial TypeError(str)      core=('TypeError', 'memory material takes bytes, got str')  email=(same)
SAME MemoryMaterial TypeError(bytearray) core=('TypeError', 'memory material takes bytes, got bytearray')  email=(same)
SAME memory_bytes -> type name          core=('ok', 'MemoryMaterial')  email=('ok', 'MemoryMaterial')
material parity: IDENTICAL
core FileMaterial methods: ['open_text', 'read_bytes', 'size']
core PathMaterial isinstance FileMaterial: True
email PathMaterial isinstance email FileMaterial: True
```

Both edges the move must not lose hold: the strict-UTF-8 text view (`UnicodeDecodeError` on an
invalid byte) and the `bytes`-only constructor (`TypeError` on `str`, `bytearray`, `memoryview`).

## B. Gate 1 -- the stream is read exactly once (with a mutation that trips it)

Instrumentation: `CountingStream` counts `read`/`seek` calls and total bytes returned;
`_source_opens` monkeypatches both `builtins.open` and `io.open` to count opens of the target and
`Path.read_bytes` to count `read_bytes` calls.

- `test_archive_stream_reads_the_source_exactly_once`: after `archive_stream`, the stream's
  `bytes_read == size` and `seeks == 0` (never rewound), and the stored blob equals the input.
- `test_archive_raw_opens_the_source_once_and_never_read_bytes`: `archive_raw` opens the file
  **once** and calls `read_bytes` **zero** times.
- Mutation proof (the check can fail): `_archive_stream_two_pass` (a deliberately two-pass archive
  that hashes to EOF then rewinds) makes `_assert_read_once` raise
  (`test_the_stream_gate_can_fail`); `_archive_raw_old` (the pre-P2a `archive_raw`, verbatim)
  shows 2 opens and 1 `read_bytes` (`test_the_open_gate_can_fail`).

## Gate 2 -- `archive_raw` is unchanged

`_archive_raw_old` is the pre-P2a implementation copied verbatim into the test as the reference.
`test_archive_raw_matches_the_old_implementation` runs the old and new code over three files
(`doc.docx` = `b"hello world"`, `empty.bin` = `b""`, `Report.DOCX` = an upper-case suffix) in two
scratch roots, with both implementations reading the same frozen clock, and asserts:

- the returned records are equal field for field (`ingested_at` pinned to `2030-01-01T00:00:00Z`
  by a monkeypatched `time`, and separately matched against a strict ISO-8601 regexp);
- the idempotent **second** call returns the same record for both;
- the whole `raw/` tree is byte-identical between the two roots, and the two `index.json` files
  are byte-equal;
- the index holds exactly one entry per file, the zero-byte file records `size == 0`, and the
  upper-case-suffix file's `storage_ref` ends in the lower-cased `.docx`.

`test_an_existing_unindexed_destination_is_left_alone` covers the "blob exists but is not indexed"
path: the tampered bytes are left as they are and the record is added to the index, exactly as the
old code did.

## Gate 3 -- crash safety

- `test_a_raising_stream_leaves_no_file_and_no_index_entry`: a `FailsAfter` stream that raises
  after 50 bytes leaves `raw/` empty and no `index.json`. (The temp file is removed in a
  `finally`.)
- `test_a_leftover_temp_file_is_swept_by_the_next_call`: a hand-placed `.incoming-*` file (a
  hard-kill leftover) is removed by the next `archive_raw` on that root, and the new blob lands.
- `test_two_archives_leave_no_temp_file`: two sequential archives leave no `.incoming-*` file.
- `test_two_identical_files_leave_one_stored_copy`: two identical files archived twice leave one
  blob and one index entry.

## C. Identity is defined once

`sha256_stream(stream, chunk=1 << 20) -> (hex_digest, byte_count)` is the definition;
`content_hash(path)` is its file-shaped form; `archive_stream`'s record carries the same digest.
The rule is stated in `hashing.py`'s module docstring, `source.py`'s docstring and the core README.

`test_identity.py` walks the chunk boundaries (empty, one byte, exactly one chunk, one chunk plus
one, 3 MiB of non-repeating bytes) and asserts `sha256_stream`, `content_hash(path)`,
`hashlib.sha256(bytes)` and `archive_stream`'s record all agree. Two hand-derived known digests
(`sha256(b"")`, `sha256(b"A")`) pin `sha256_stream` to the *real* sha256, so an implementation that
merely agrees with itself cannot pass.

## Gate 5 -- purity

`test_purity.py` AST-parses every `docextract_core/*.py`:
`test_only_standard_library_imports` (roots must be in `sys.stdlib_module_names`),
`test_no_network_module_is_imported` (no `socket`/`ssl`/`urllib`/`http`/`asyncio`/...), and
`test_the_clock_and_subprocess_stay_where_they_already_were` (the only `time` import is
`archive.py`; the only `subprocess` import is `__init__.py`). No new dependency, no new clock use.

## Versions and ledger

- `CORE_VERSION` `"0.1.0"` -> `"0.2.0"` in `docextract_core/__init__.py`. `SCHEMA_VERSION` is
  untouched (`"7"`) — no persisted codec shape changed, and the codec itself is untouched.
- **`SourceItem` is NOT added to `CORE_RECORDS`.** `SourceItem` is an in-flight object a `Source`
  yields; it is never persisted, so it is not part of the stored contract. The empirical check (in
  `.scratch/p2a/parity.py`):

  ```
  contracts fingerprint now          : 6d81904a9ffdcb11fda9f6542dac968e5e26cd43d452e2d02a4ea28adeb8944f
  contracts fingerprint + SourceItem : 358f71d5d372807b1134fcbb47911ae090b057a96da37beacf4a100f2dfb759e
  would move: True
  updater with SourceItem added: REFUSED -> contracts: '7' is already recorded with fingerprint
  6d81904a... but the code now computes 358f71d5... Bump docextract_core.SCHEMA_VERSION and record
  the new version -- an existing key is never overwritten.
  ```

  i.e. adding it would move the fingerprint and the updater would demand a `SCHEMA_VERSION` bump,
  which the brief forbids. So the fingerprint does **not** move and no ledger line changes.

- `python tools/update_behavior_ledger.py --check` is **exit 0 both before and after**. "Before" was
  run in a `git worktree` pinned at the pre-P2a `HEAD` (`137af7c`, outside the repo), "after" in the
  working tree. No `tools/behavior_ledger.py` or `tests/ledger/**` edit was needed or made.

## Checks run

| Command | Result |
| --- | --- |
| core suite, CPython 3.14.4 | `49 passed, 1 skipped in 2.50s` |
| core suite, CPython 3.11.15 | `49 passed, 1 skipped in 1.07s` |
| `python tools/update_behavior_ledger.py --check`, before (HEAD worktree) | exit 0 |
| `python tools/update_behavior_ledger.py --check`, after | exit 0 |
| word-extract full suite, CPython 3.14.3 | `4881 passed in 156.19s` |
| word-extract full suite, CPython 3.11.15 | `4869 passed, 1 skipped in 59.21s` |
| `workbook-extract`, `OPENPYXL_LXML` unset, `python tools/check_suite.py` | chunk A **FAILED** (14 failed, 4765 passed), chunk B ok (76 passed); wall 220 s — see the decision below |
| `email-extract` / `form-extract` import core's **archive**? | no — see below |

- **email-extract** imports core's `Collection` and `CodecError` / `codec` only
  (`emailextract/ingest.py`, `model.py`, `parse.py`, `seam.py`, `siblings.py`, `store.py`); it does
  **not** import core's archive. **form-extract** imports nothing from core at all. Neither is
  affected by moving the archive.
- **email-extract**'s ledger keys `contracts` off its own `OUTPUT_SCHEMA_VERSION` (re-keyed away
  from core's `SCHEMA_VERSION` in its Turn 0.5) and does not include `CORE_VERSION`; it is
  unaffected. **form-extract** has no ledger.
- **workbook-extract**'s ledger keys `contracts` off `MANIFEST_SCHEMA_VERSION` **and** stamps the
  core envelope `{"schema_version": SCHEMA_VERSION, "core_version": CORE_VERSION}`
  (`tools/behavior_ledger.py:282`). So the `CORE_VERSION` bump moves that fingerprint — see the
  decision.

## Needs a decision (stopping here)

1. **The `CORE_VERSION` bump turns `workbook-extract`'s behavior-ledger gate red.** Its `contracts`
   fingerprint includes core's `CORE_VERSION`. Proof: with `CORE_VERSION` monkeypatched back to
   `"0.1.0"`, `workbookextract`'s `contracts_fingerprint()` is exactly the recorded
   `1e56f964...`; with the shipped `"0.2.0"` it is `335f51b7...`. That is the sole cause of the 14
   `tests/test_behavior_ledger.py` failures (`MANIFEST_SCHEMA_VERSION is still 6 and its recorded
   fingerprint moved`). The workbook manifest did not change, so bumping its
   `MANIFEST_SCHEMA_VERSION` would be a false record; the honest fixes are (a) drop `core_version`
   from the workbook's contracts payload in a workbook turn, or (b) do not bump `CORE_VERSION`
   here. This repo (`word-extract`) and `workbook-extract` are both outside the P2a change surface,
   so the owner decides.
2. **`CORE_VERSION` now diverges from the distribution version.** `docextract_core.__version__` /
   `pyproject.toml` `version` is still `"0.1.0"` while `CORE_VERSION` is `"0.2.0"` (the brief scoped
   the bump to `CORE_VERSION`; `word-extract`'s pin is `docextract-core>=0.1.0,<0.2`, which a
   distribution bump to `0.2.0` would break). Confirm whether the two are meant to track each other
   and, if so, when `pyproject`/the pin move.
3. **Housekeeping (not done, so you can see it).** The parity script lives at
   `word-extract/.scratch/p2a/` (inside the repo, contrary to "scratch belongs outside the repo"),
   and `docextract-core/build/` is stale untracked build output still holding `CORE_VERSION =
   "0.1.0"`. Both are untracked and neither is imported, but they should not be committed.
