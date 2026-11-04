---
capability: rest-data-v2-cache-and-sources
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.v2.cache.V2Cache@d502acc688
  - cosa.rest.v2.trace.StageTrace@b0560e06c6
  - cosa.rest.v2.near_match_guard.has_number@42f372c372
  - cosa.rest.v2.near_match_guard.quantity_tokens@ab6a7d088b
  - cosa.rest.v2.source_document.parse_source_documents@7dcb02650b
  - cosa.rest.v2.source_document.resolve_within_root@b5b2b4635b
  - cosa.rest.v2.source_document.split_scope@e48fe37056
  - cosa.rest.v2.source_document.validate_source_documents@d812cb8a46
---
# V2 cache, trace and source documents

The pieces around a v2 request that remember, measure and vet input. The flow is in [[v2-ask-flow]]; this page names what the flow leans on.

## What it does
- `V2Cache` subclasses `TwoTierQuestionSearch` and inherits `lookup`. Tier 1 is an exact match on the verbatim or normalized question, plus a gist probe. Tier 2 is the nearest neighbour, whose best score is recorded but never marks a replay.
- `snapshot_from_result` builds a replay-shaped snapshot from a flow result. `gist` and `normalize` use the store's own normalizers.
- `write_back( snapshot, writeback_enabled=True )` is the only place the write-back switch is read. Off returns `None`. On, it tags `runtime_stats` as `v2`, upserts the row, registers one canonical synonym and fills the embedding cache. It returns the id hash.
- `StageTrace` records a clock mark per named stage and free-form fields. `timings_ms` gives each mark's offset from the anchor `t_recv`, or from the earliest mark when that is absent. `write` appends one JSON line to `trace-YYYY-MM-DD.jsonl`, in `io/v2-flow` by default.
- `quantity_tokens( text )` lists a question's numbers and content words in order. `has_number` tells whether a number is present. `quantities_differ`, in the same module, is the near-match guard: the flow calls it before replaying a near match. It is false when neither question has a number, true when either is `None`, and otherwise true unless the two lists are identical.
- `validate_source_documents( raw, scopes )` returns `( paths, error )` for the `source_document` argument. A bare string becomes one path, and `None` or a blank means absent. It uses `parse_source_documents` for shape, `split_scope` for the `<scope>/<path>` form, and `resolve_within_root` for containment.

## Don't
- Don't add a size limit to source documents there. The ruling is that there is none. The only cap is 16 documents per request.
- `validate_source_documents` takes `scopes` as an argument and needs only a `.root` on each value. The module still imports four helper functions from `routers._scope_registry`.

## Invariants
- Only a tier-1 exact hit sets `is_replay_hit`. The flow's near-match step can still replay a candidate.
- A question with an empty gist never matches on the gist probe.
- `write_back` raises `ValueError` for a snapshot with no question or no id hash, and `RuntimeError` when enabled with no db scope.
- `snapshot_from_result` raises `ValueError` for an empty question or an empty `user_id`.
- `StageTrace.set` copies a dict, list or set, so a later change by the caller cannot rewrite a field.
- Source-document functions never raise. A failure is a message, and the first failure wins.
- Resolution follows symlinks, then re-checks containment. The secrets and prefix guards run on the typed and the resolved relative path.
- Extensions allowed, compared in lowercase: `.md`, `.markdown`, `.txt`, `.yaml`, `.yml`, `.json`, `.csv`, `.rst`.
