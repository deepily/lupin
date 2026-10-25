---
capability: repo-tools-candidate-vector-freshness
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.freshness.index_manifest@10c4b1733b
  - cosa.repo.symindex.candidates.freshness.utc_now@469c33c8eb
  - cosa.repo.symindex.candidates.freshness.write_build_info@0a830f02bf
  - cosa.repo.symindex.candidates.freshness.read_build_info@53135f9eb5
  - cosa.repo.symindex.candidates.freshness.read_manifest@ab056170b8
  - cosa.repo.symindex.candidates.freshness.refresh_lock@66437fa2a3
---
# Candidate vector freshness and build lock

A vector set remembers which index it was built from in `build-info.json`, a side file inside the set's folder. It is not one of the hashed files, so a new time stamp never changes the manifest hash. It travels with the set through the rename swap.

## Build info
- `index_manifest( header )` is the sha256 of the canonical JSON of an index header's manifest. Two generations of the same tree state give the same value.
- `utc_now()` is the current UTC time as an ISO string to the second, ending `+00:00`.
- `write_build_info( set_dir, header, built_at, unwritten_pins=() )` writes `index_manifest`, `symbols_sha`, `built_at` and the sorted `unwritten_pins`, and returns that dict. A pin listed there is settled for this index manifest and is asked for again only after the index changes.
- `read_build_info( live_dir )` returns the dict, or None when the file is absent, unreadable, not a JSON object or lacks `index_manifest` or `built_at`. A set made before this file existed therefore reads as unknown, never as fresh.
- `read_manifest( live_dir )` parses `manifest.json` without hashing the matrices, and returns None when it is absent, unreadable or not an object.

## Build lock
- `refresh_lock( path )` is a context manager that holds an exclusive, non-blocking file lock for one build. A second holder gets `BUILD_LOCK_HELD`. The operating system drops the lock when its process ends, so a killed build leaves no stale lock.
