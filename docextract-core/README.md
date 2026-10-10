# docextract-core

Shared substrate for the document-extraction packages ([`word-extract`](https://pypi.org/project/word-extract/)
and its siblings): content hashing, a strict canonical-JSON codec, archive helpers, a
content-addressed `Collection`, the source-side materials and protocols (`Source`,
`FileMaterial`), and a small LLM-client protocol. It has no runtime dependencies.

## Identity

**A document's identity is the sha256 of its raw bytes, defined here once.** `sha256_stream`
is that definition and `content_hash` is its file-shaped form; `archive_raw` / `archive_stream`
key the store by the same digest. A family must not hash a *projection* (a text view, a
rendered form, a container's own summary of itself) under this name — a projection is derived
from the bytes, the identity is the bytes.

## Sources and archives

`Source` yields `SourceItem`s (`material`, `locator`, `provenance`); a `locator` and its
provenance are *claims, never identity*. `archive_stream` hashes a binary stream while it
copies it to the content-addressed store (one read, no temp file), and `archive_raw` is its
path-shaped wrapper.

Most users want `word-extract`, which depends on this package.

Licensed under the Apache License, Version 2.0.
