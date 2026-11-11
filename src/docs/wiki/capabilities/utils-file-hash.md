---
capability: utils-file-hash
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.file_hash.file_sha256@277971f61d
---
# File content hash

One helper in `cosa.utils.file_hash` reads a file for its sha256. Tools use it to pin an input by its content, and several wiki pages name it.

## What it does
- `file_sha256( path )` returns the 64-character lowercase hex digest of a file's bytes. It accepts a path-like or a string.
- It reads in chunks of `CHUNK_BYTES` (1 MiB), so a large file does not have to fit in memory.

## Don't
- Don't write another file-hashing function. Seven copies were folded into this one.
- Don't hash text with it. For a string, use `cosa.utils.secret_drift.sha256_of`.
- Don't expect a missing file to return None. It raises `OSError`; `attestation.sha256_file` is the wrapper that returns None.

## Invariants
- The digest equals `hashlib.sha256` over the whole file, whatever the chunk size.
- The hook library keeps its own copies, because a hook must not import `cosa`.
