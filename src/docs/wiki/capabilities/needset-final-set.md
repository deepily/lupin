---
capability: needset-final-set
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.finalize.sample_size@7058a18b07
  - lupin_mcp.reuse_needset.finalize.select_for_labelling@782962f2e6
  - lupin_mcp.reuse_needset.finalize.need_item@b8b759cff3
  - lupin_mcp.reuse_needset.finalize.final_row@d9103e0e5d
  - lupin_mcp.reuse_needset.finalize.file_sha256@263a4ccc40
  - lupin_mcp.reuse_needset.finalize.finalize@1a05cab254
  - lupin_mcp.reuse_needset.finalize.verify_manifest@6b67a39046
  - lupin_mcp.reuse_needset.finalize.check_committed_set@cd3f2fd00f
---
# Need set: labelling choice and final set

Chooses the needs people label, builds the final set and verifies its manifest. The checks that precede it are on [[needset-second-check]].

## Choosing what reviewers see
- `sample_size` is 15 percent of the agreed needs with a half rounded up, so 30 gives 5.
- `select_for_labelling` returns each item with its reason, kept apart. The order is every disputed need, every nothing need not already listed, a seeded sample of the agreed matched needs, then the duplicate-checker pairs. Each group is sorted by id.
- It raises `BAD_NEED` for a need that is not checked or is a smoke need.
- `need_item` builds the item a reviewer sees. It holds the sentence and the key sources, or the sentence with nothing-exists and the hits. It holds no verdict, route, drafter or checker field.

## Final set
- `final_row` joins a checked need with its final label. A matched need labelled with other symbols takes the reviewers' symbols as its key, with the version raised by one.
- A nothing need is confirmed by the proposal as it stands. A label that rejects the need raises `MANIFEST_MISMATCH`.
- `file_sha256` returns the sha256 of a file's bytes.
- `finalize` writes the final file, one row per need sorted by id, then the manifest. It takes the frozen identity of [[needset-freeze]]. The manifest holds the counts, seed, source commit, kappa, the three frozen hashes and the final file's hash.
- `verify_manifest` checks a finished set against the required shape: 400 rows, 300 matched, 100 nothing, 240 TypeScript and 160 Python.
- Every nothing and disputed row needs a human final source. No row is a smoke row, no id repeats, and the hash, kappa and the three frozen hashes must be present.
- `check_committed_set` reads the status file. A pending set with a set file, or a final set that fails verification, raises `MANIFEST_MISMATCH`.
