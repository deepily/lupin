---
capability: needset-records-and-quota
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.errors.NeedsetError@86f8e53032
  - lupin_mcp.reuse_needset.schema.need_id@9851f0d4bf
  - lupin_mcp.reuse_needset.schema.new_need@f480326b80
  - lupin_mcp.reuse_needset.schema.validate_need@07783ccf4f
  - lupin_mcp.reuse_needset.quota.plan_quota@be72893016
  - lupin_mcp.reuse_needset.quota.census@fa2d8eead2
  - lupin_mcp.reuse_needset.quota.draw@48b7979bcb
  - lupin_mcp.reuse_needset.quota.plan_record@2a9ef54452
  - lupin_mcp.reuse_needset.quota.write_plan@8e52103946
---
# Need set: records, errors and quota plan

The need set is a diagnostic set of plain-sentence needs. Each is paired with an answer key: the index symbols that already do the job, or none. This page covers the record, its errors and the plan that fixes how many needs of each kind are drawn.

## Need record
- `validate_need` checks a record against the `needset-need-1` format. A matched kind has a seed and a non-empty key. A `nothing` need has neither.
- The key source says how the key was found. It is `twin` for a near copy, `vector`, `bm25`, `directory` or `random` for the two routed kinds, and none for `nothing`.
- A record at status `checked` or later carries a check block. It holds a model, a result of agree, disagree or unsure, a note and a mechanical list. The id must equal `need_id`.
- `need_id` is `n-` and ten hex digits of the sha256 of the kind, language, seed, need and source commit. It does not depend on key order, or on the key, check or status.
- `new_need` builds a validated record with status `drafted`, key version 1 and no check. An invalid record raises `BAD_NEED`.
- `NeedsetError` carries a stable code such as `QUOTA_UNFILLABLE` or `NEED_LEAKS_KEY`, so a caller reports the cause and never guesses it.

## Quota plan
- `plan_quota` fills the kind-by-language table so the language margins are exact. The split of matched needs by kind has no default, and a missing one raises `KIND_SPLIT_UNSET`.
- The TypeScript cells sum to the largest-remainder share of the total, and the Python cells to the rest.
- `census` counts the distinct eligible seeds in every cell before any model call.
- `draw` picks the seeds of every cell, with spares, from a sorted pool and a fixed seed. The same seed gives the same draw whatever order the pool lists its ids in.
- A seed is the primary of at most one cell. A cell whose seeds cannot all be found raises `QUOTA_UNFILLABLE`.
- `plan_record` builds the record written before the first draft is requested. `write_plan` writes it once, by hard link, so of several racing writers exactly one succeeds. A second write raises `PLAN_ALREADY_WRITTEN`.
