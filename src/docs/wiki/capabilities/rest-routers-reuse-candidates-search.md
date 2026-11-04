---
capability: rest-routers-reuse-candidates-search
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.reuse_candidates.StageUpload@825f2bbe37
  - cosa.rest.routers.reuse_candidates.data_root@84dd8ed0ba
  - cosa.rest.routers.reuse_candidates.resident@6343112f97
  - cosa.rest.routers.reuse_candidates.failure@0f3434cd0a
  - cosa.rest.routers.reuse_candidates.put_stage@4cce7743ab
  - cosa.rest.routers.reuse_candidates.search@074dc779a6
---
# Reuse candidates search router

The `/api/reuse-candidates` door to the resident candidate search. A client uploads the entries of one index once, then searches by key. See [[reuse-search-tools]].

## What it does
- `put_stage` (`PUT /api/reuse-candidates/stage`) holds one stage. The body is `StageUpload` (`key`, `entries`, optional `purposes` and `fusion`), and the answer is `{ key, entries }`. Uploading a held key replaces it.
- `search` (`POST /api/reuse-candidates/search`) takes a JSON object with `stage_key`, `need` and `K`, and optionally `vectors_dir`, `query_vectors`, `wiki` and `expect_manifest_hash`. It ranks the need against the held stage and returns the shortlist.
- `resident` returns the one `ResidentSearch` of this process, made on first use under a lock.
- `data_root` names the folder a vectors folder must sit under. `LUPIN_REUSE_REVIEW_DATA_ROOT` wins, and otherwise it is the repository's reuse-review data directory.
- `failure` turns a `CandidateError` into `{ error, detail }`. The status is 422 for a bad upload or search and 409 for an unknown stage or a replaced vector set. A refused path is 403, and anything else is 503.
- Both routes accept an API key or a JWT.

## Don't
- Don't search before uploading. An unknown key answers 409, so upload again.

## Invariants
- Held stages live in this process's memory only, shared by every request. A restart or a newer upload pushing one out (the limit is 2) makes search answer 409, so upload again.
