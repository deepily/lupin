---
capability: eval-provenance-and-commons-migration
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.eval_provenance.compute_sample_signature@3a3151d3e2
  - scripts.eval_provenance.make_provenance@864e4bb74a
  - scripts.migrate-commons-entry-separator.migrate_directory@3e7fcbc901
  - scripts.migrate-commons-entry-separator.main@0d4ea59a18
---
# Eval provenance and commons separator migration

Two small utilities, one for eval results and one for the commons store.

## Eval provenance
- The provenance stamp an eval arm attaches to its result was moved out of the paired harness. Removing the old harness therefore cannot break the v2 eval at import time. The code was moved verbatim.
- `compute_sample_signature` returns the sha256 of the sorted, deduplicated set of utterance and expected-command pairs. Two arms that measured the same utterances in any order get the same signature. A separator between the two parts keeps different splits distinct.
- `make_provenance` builds the stamp with the seven provenance fields: arm, corpus, seed, per-command count, signature, sampled count and git sha.
- The git sha is a required argument, read back from the server the arm measured, never a constant. An arm that cannot say which tree it ran on must fail at the stamp.

## Commons separator migration
- `migrate_directory` converts the legacy entry separator in commons topic files to the canonical boundary marker, which does not collide with markdown thematic breaks. The old separator once made the store drop everything after the first break inside a body.
- It scans the commons folder and its archive. It replaces a separator only when a valid entry header follows immediately, and leaves front matter and body breaks alone.
- It returns a summary of files scanned and changed and the replacement count. It copies each changed file to a backup folder first, unless backups are off. A dry run writes nothing.
- Re-running on a migrated tree is a no-op. `main` returns 0 on success and 1 on a usage error.
