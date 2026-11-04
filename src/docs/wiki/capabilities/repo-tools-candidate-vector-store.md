---
capability: repo-tools-candidate-vector-store
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.vector_store.canonical@335bf66db1
  - cosa.repo.symindex.candidates.vector_store.file_sha256@ae79b421e0
  - cosa.repo.symindex.candidates.vector_store.manifest_hash@d6e63509e6
  - cosa.repo.symindex.candidates.vector_store.text_hash@3afe6b4a27
  - cosa.repo.symindex.candidates.vector_store.write_row_texts@1d8056b5ce
  - cosa.repo.symindex.candidates.vector_store.read_row_texts@871ffe4a8b
  - cosa.repo.symindex.candidates.vector_store.seal@ecdbc8da53
  - cosa.repo.symindex.candidates.vector_store.swap_in@ba2c83d2c8
  - cosa.repo.symindex.candidates.vector_store.VectorSet@cf61f941ba
  - cosa.repo.symindex.candidates.vector_store.load_vectors@33ff293bd9
---
# Candidate vector store

One vector set holds the current state of the repo: three float32 matrices (`prose.f32`, `code.f32`, `concat.f32`), `ids.txt`, `manifest.json` and the optional `row_texts.jsonl`. A rebuild writes a new folder and swaps it in. A missing or damaged set is a named error, never a recomputed answer.

## Hashes
- `canonical( obj )` is JSON with sorted keys and no spaces. `file_sha256( path )` hashes a file in chunks. `text_hash( text )` hashes one embedded text.
- `manifest_hash( manifest )` ignores a stored `manifest_hash` key, so a sealed manifest hashes to its own value. It changes when any other field does.

## Writing a set
- `write_row_texts( out_dir, ids, hashes )` writes one line per id naming the text hash of each matrix row. The next build uses it to reuse rows.
- `seal( out_dir, ids, manifest )` writes `ids.txt`, then `manifest.json` with every file's hash and its own `manifest_hash`. It returns the sealed manifest.
- `swap_in( new_dir, live_dir )` renames the live folder aside, renames the new one in, then removes the old. A lookup between the renames finds no set, never half of one. If the second rename fails, the old set is renamed back and the error is raised.

## Reading a set
- `load_vectors( live_dir )` rechecks the manifest hash and every file hash, then returns a `VectorSet` with `manifest`, `ids`, `matrices` (memory maps) and `row_texts`. It raises `VECTOR_SET_UNAVAILABLE` without a manifest, `VECTOR_SET_CORRUPT` for a hash or size that disagrees, and `DEPENDENCY_MISSING` without numpy.
- `read_row_texts( live, ids )` reads the sidecar. It raises `VECTOR_SET_CORRUPT` for a line that is not JSON, ids that differ from `ids.txt`, or a hash that is not 64 hex characters.
