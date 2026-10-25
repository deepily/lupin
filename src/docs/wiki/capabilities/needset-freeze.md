---
capability: needset-freeze
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.freeze.freeze@d0c03c4411
  - lupin_mcp.reuse_needset.freeze.identity@5a91505214
  - lupin_mcp.reuse_needset.freeze.require_same@d529bea0af
---
# Need set: freeze

The need keys name symbols of one index at one commit. A scoring run on a rebuilt index or a refreshed vector set would blame the checker for what the data changed. So the set records three hashes, and each arm checks them before it makes a call.

## What it does
- `identity( index_gen, vectors_dir )` returns `index_manifest`, `symbols_sha` and `vector_build_info_sha`. The first two come from the generation's header. The third is the sha256 of the vector set's build-info file.
- It raises `FREEZE_INCOMPLETE` for an unreadable header or build info, and `VECTORS_NOT_FROM_INDEX` when the vector set was built from another index.
- `freeze( index_gen, vectors_dir, dest )` copies both into `dest/index` and `dest/vectors` with `needset-frozen.json`, then makes everything read-only. It returns the identity read back from the copies.
- A second call over the same source changes nothing. A `dest` that holds other hashes, or is not a frozen copy, raises `FROZEN_COPY_EXISTS`.
- `require_same( manifest, live, arm )` returns `None` when all three hashes match. It raises `FREEZE_INCOMPLETE` for a missing key, `INDEX_DIFFERS` when the index hashes differ, and `VECTORS_DIFFER` when the vector hash differs.

## Who calls it
- `run_needset` freezes before the draw ([[needset-drafting-run]]). `finalize` writes the three hashes into the manifest ([[needset-final-set]]). `trace_all` calls `require_same` before it makes a call ([[needset-loss-trace]]).
- Re-checking a frozen set against a newer index is on [[needset-revalidation]].
