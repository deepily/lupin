---
capability: repo-tools-candidate-arms-run-inputs
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.arm_run.real_env@18a45ad171
  - cosa.repo.symindex.candidates.arm_run.sha256_of@684acd39fd
  - cosa.repo.symindex.candidates.arm_run.load_needs@bc2c5f5cac
  - cosa.repo.symindex.candidates.arm_run.snapshot_entries@6060881749
  - cosa.repo.symindex.candidates.arm_run.pick_snapshot@3dc71c97c8
  - cosa.repo.symindex.candidates.arm_run.load_answers@eab2da3551
  - cosa.repo.symindex.candidates.arm_run.hash_answers@9aacd3d8ea
---
# Candidate arms: run inputs

`arm_run.py` reads what a measurement needs: the needs, the stored snapshot and the cached judge answers. The index and cache readers are passed in as an environment, so a test can hand it small cases. The measuring half is on [[repo-tools-candidate-arms-measure]].

## Environment and files
- `real_env( data_dir )` builds the real readers as a namespace: `sendable`, `entry_text`, `pair_key`, `model` and a `JevCache` over `data_dir`.
- `sha256_of( path )` returns the hex digest of a file's bytes. It is how a page names the needs file and manifest it read.
- `load_needs( path, fresh_sha )` returns `{ need id: record }` from `{ "needs": [ { id, need, exclude } ] }`. It calls `refuse_fresh_needs`, so a reserved id or file raises `FRESH_NEEDS_REFUSED`.

## Snapshot
- `snapshot_entries( path, sendable )` reads a gzip snapshot, parses its `symbols_jsonl` lines and returns the entries the sweep would send.
- `pick_snapshot( paths, hits_for )` returns `( hits, path )` for the snapshot where `hits_for` counts most cached answers. The first path in sorted order wins a tie.

## Cached answers
- `load_answers( needs, entries, env )` reads, for every need and each of five repeats, the cached `provides` and `coverage` of every entry. It returns `( answers, misses )`. The entry a need excludes is not asked, and an entry with no cached answer counts as a miss.
- `hash_answers( answers )` returns a sha256 of the answers read, so a page names exactly what it replayed.
