---
capability: repo-tools-candidate-stage-and-resident
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.candidate_stage.Stage@d96b26286b
  - cosa.repo.symindex.candidates.candidate_stage.build_stage@a4a5349bd4
  - cosa.repo.symindex.candidates.candidate_stage.shortlist@e7dd9e8fbb
  - cosa.repo.symindex.candidates.candidate_stage.shortlist_bytes@7871f266ef
  - cosa.repo.symindex.candidates.candidate_stage.replay@defe90f423
  - cosa.repo.symindex.candidates.resident.ResidentSearch@c535d098c7
  - cosa.repo.symindex.candidates.resident.trim_lists@9d506a25fc
---
# Candidate stage and resident search

A stage is the lexical half of one lookup: two BM25 indexes, one over code fields and one over prose fields, plus the fusion constants. Nothing in it reads a clock, a random source or the network.

## Stage
- `build_stage( entries, purposes=None, k=60, depth=512, head=5 )` returns a frozen `Stage`. A purpose line is joined to its entry by `pin`. The input entries are not changed.
- `shortlist( need, stage, K, extra_lists=None )` ranks the need with both indexes, fuses them with any extra ranked lists in sorted source order. It returns `shortlist` (ids sorted), `ranking` (fused order), `lists` and `scores`. An extra list named `code` or `prose` raises `SOURCE_CLASH`.
- `shortlist_bytes( result )` is the one serialisation: sorted-key UTF-8 JSON. `replay( need, stage, K, recorded, extra_lists )` recomputes and returns the sha256 when the bytes match, else raises `REPLAY_MISMATCH`.

## Resident search
- `ResidentSearch( allowed_root, load_vectors, max_stages=2, max_vector_sets=2 )` holds stages and vector sets between lookups so each lookup costs one cosine pass per matrix. It reads no index folder.
- `put_stage( key, entries, purposes=None, fusion=None )` builds and holds a stage and returns `{ key, entries }`. A wrong shape raises `BAD_STAGE_UPLOAD`. The oldest stage is dropped beyond the limit.
- `search( request )` needs `stage_key`, `need` and `K`. It raises `STAGE_UNKNOWN` for an unheld key and `PATH_REFUSED` for a vectors folder outside the allowed root. A held vector set is reloaded when its manifest's size or mtime changes. `expect_manifest_hash` that differs raises `VECTOR_SET_REPLACED`.
- `trim_lists( result, head=20 )` cuts each source's list and scores to the first 20 and adds `list_sizes`. `search` applies it to every answer.
