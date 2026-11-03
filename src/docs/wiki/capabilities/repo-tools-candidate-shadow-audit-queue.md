---
capability: repo-tools-candidate-shadow-audit-queue
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.shadow_audit.enqueue_if_sampled@7e5d77b780
  - cosa.repo.symindex.candidates.shadow_audit.enqueue_pending@169f565fdf
  - cosa.repo.symindex.candidates.shadow_audit.audits_in_week@f9f110db24
  - cosa.repo.symindex.candidates.shadow_audit.count_lookup@cf3f37d3c6
  - cosa.repo.symindex.candidates.shadow_audit.run_pending@61ed56235b
  - cosa.repo.symindex.candidates.shadow_audit.store_receipt@525e2b37b5
  - cosa.repo.symindex.candidates.shadow_audit.load_receipts@b15e583a38
  - cosa.repo.symindex.candidates.shadow_audit.daily_volume@6b4bf98a0c
---
# Candidate shadow audit: queue and receipts

Files live under the data folder: `shadow-pending/<id>.json` for queued lookups, `receipts/shadow-<id>.json` for audits and `receipts/shadow-lookups-<day>.log` for the daily count. Sampling and the bound are in [[repo-tools-candidate-shadow-audit]].

## Queueing
- `count_lookup( data_dir, today )` appends one line to the day's log and returns that day's count.
- `enqueue_if_sampled( data_dir, need, language, generation, index_sha, live, today, rate=0.01 )` counts the lookup, then queues it when sampled and returns its id, else None. The queue file keeps the redacted need so the sweep can read it. The same lookup queues once.
- `enqueue_pending( data_dir, need, language, generation, index_sha, live, today, known_miss=False )` is the file write alone: no lookup count and no sampling. `enqueue_if_sampled` calls it, and the daily duplicate job will call it with `known_miss=True` for a lookup behind a found duplicate. The item and the receipt carry `known_miss`; a file written before the field existed reads as False.

## Draining
- `run_pending( data_dir, sweep_fn, today, limit=None )` takes known-miss items first, then fewest attempts, then oldest, then id. It sweeps each, stores a receipt and removes the queue file. It returns `audited`, `failed`, `corrupt`, `dropped` and `receipts`.
- A sweep that raises a `CandidateError` naming `UNKNOWN_ENTRY` leaves the item queued like any failure. On its third failed attempt the file is removed and the item counts as `dropped`.
- `weekly_cap` stops the drain before an audit that would pass the cap. It counts the audits stored in the seven days ending today, and `stopped_by` reads `weekly_cap`. `audits_in_week( data_dir, today )` is that count. `lupin_mcp.reuse_shadow.drain` passes `reuse_ledger.SHADOW_AUDIT_WEEKLY_CAP`, the constant the budget test reads too.
- `max_tokens` caps a drain. Each sweep answer must then carry a whole-number `tokens`. The run stops before a sweep when the tokens spent plus the largest sweep seen would pass the cap. The result gains `spent_tokens` and `stopped_by`. `pass_language` calls the sweep as `( need, language )`. `lupin_mcp.reuse_shadow` sets both, reading the cap from the INI key `reuse shadow audit max tokens per drain`, which has no default.
- A sweep that raises or answers without `verdict` or `causal_ids` leaves the item queued with its attempt count up by one. So does an item whose receipt file is already there and damaged, and that check comes before the sweep, so no sweep is spent. A queue file that is not valid is renamed to `<name>.corrupt` and the run goes on.

## Receipts and volume
- `store_receipt( data_dir, receipt )` writes the file once and returns what is on disk, so a repeat never rewrites history. A bad existing file raises `AUDIT_RECEIPT_CORRUPT`.
- `load_receipts( data_dir )` reads every `shadow-*.json` receipt, sorted by id. A file that is not JSON, lacks a field or holds an unknown outcome raises `AUDIT_RECEIPT_CORRUPT`.
- `daily_volume( data_dir )` returns `{ day: { lookups, audits } }`.
