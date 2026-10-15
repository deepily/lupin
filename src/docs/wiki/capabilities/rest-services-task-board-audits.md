---
capability: rest-services-task-board-audits
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_store_prose_refs.strip_amendment_stamps@5b196bbdf9
  - cosa.rest.task_store_prose_refs.extract_prose_refs@6f366edcfe
  - cosa.rest.task_store_prose_refs.classify_prose_refs@ac4e767645
  - cosa.rest.task_store_prose_refs.candidate_ref_ids@b2427f3559
  - cosa.rest.task_store_prose_refs.aggregate_counts@a3baf05a4a
  - cosa.rest.task_store_prose_refs.scope_disclosure@b6f643a54f
  - cosa.rest.task_store_rejoin.dormancy_days@671649825a
  - cosa.rest.task_store_rejoin.dormancy_stamp@b78aad1b09
  - cosa.rest.task_store_rejoin.scope_disclosure@82ae40cd9d
  - cosa.rest.task_store_epic_keys.classify_key@bd221c3461
  - cosa.rest.task_store_epic_keys.reach_disclosure@25a5bb74fe
---
# Task board audits: prose refs, rejoin and epic keys

Read-only scanners for the task store, each paired with a disclosure of what it could not see. The rules they check are in [[task-store]].

## What it does
- `strip_amendment_stamps( body )` removes amendment header stamps and returns `( text, count )`, so a shrinking result can be told from a working filter.
- `extract_prose_refs( body )` returns `canonical` (full UUIDs, lowercased, de-duplicated), `abbreviated` (8-hex tokens) and `stamps_excluded`.
- `classify_prose_refs( body, blocked_by, status_by_id )` reports a finding for a citation of a terminal id with no matching `blocked_by` edge. An abbreviated token is never resolved and never a finding.
- `candidate_ref_ids( rows )` returns only canonical ids, for one batch status lookup. `aggregate_counts` sums per-row classifications.
- `scope_disclosure` in `task_store_prose_refs` states the bodies scanned and both blind spots. It is emitted for a clean scan too.
- `task_store_rejoin.dormancy_days( closed_at, now )` counts whole days a row sat stranded, truncated toward zero, 0 for a future close, `None` if unparseable.
- `dormancy_stamp( closed_blockers, now )` builds the amendment note for a rejoined row. It says the premise is unverified and names the blockers' closing receipts.
- `task_store_rejoin.scope_disclosure( counts )` says what the rejoin pass did and which rows it left alone.
- `classify_key( correlation_key )` returns one of four buckets: epic, mirror, foreign or blank. `reach_disclosure` states the rows seen, all four buckets, whether the unknown-slug check ran and which statuses were fetched.

## Don't
- Don't report a count without its disclosure. A clean result omits the unscanned half otherwise.
- Don't resolve an 8-hex token by prefix. It produces false findings.

## Invariants
- None of these functions reads a clock; the caller passes `now`.
