---
capability: repo-tools-candidate-shadow-audit-queue
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.shadow_audit.enqueue_if_sampled@a8898cc442
  - cosa.repo.symindex.candidates.shadow_audit.count_lookup@cf3f37d3c6
  - cosa.repo.symindex.candidates.shadow_audit.run_pending@bae2b2ee9f
  - cosa.repo.symindex.candidates.shadow_audit.store_receipt@525e2b37b5
  - cosa.repo.symindex.candidates.shadow_audit.load_receipts@b15e583a38
  - cosa.repo.symindex.candidates.shadow_audit.daily_volume@6b4bf98a0c
---
# Candidate shadow audit: queue and receipts

Files live under the data folder: `shadow-pending/<id>.json` for queued lookups, `receipts/shadow-<id>.json` for audits and `receipts/shadow-lookups-<day>.log` for the daily count. Sampling and the bound are in [[repo-tools-candidate-shadow-audit]].

## Queueing
- `count_lookup( data_dir, today )` appends one line to the day's log and returns that day's count.
- `enqueue_if_sampled( data_dir, need, language, generation, index_sha, live, today, rate=0.01 )` counts the lookup, then queues it when sampled and returns its id, else None. The queue file keeps the redacted need so the sweep can read it. The same lookup queues once.

## Draining
- `run_pending( data_dir, sweep_fn, today, limit=None )` takes items fewest attempts first, then oldest, then id. It sweeps each, stores a receipt and removes the queue file. It returns `audited`, `failed`, `corrupt` and `receipts`.
- A sweep that raises or answers without `verdict` or `causal_ids` leaves the item queued with its attempt count up by one. A queue file that is not valid is renamed to `<name>.corrupt` and the run goes on.

## Receipts and volume
- `store_receipt( data_dir, receipt )` writes the file once and returns what is on disk, so a repeat never rewrites history. A bad existing file raises `AUDIT_RECEIPT_CORRUPT`.
- `load_receipts( data_dir )` reads every `shadow-*.json` receipt, sorted by id. A file that is not JSON, lacks a field or holds an unknown outcome raises `AUDIT_RECEIPT_CORRUPT`.
- `daily_volume( data_dir )` returns `{ day: { lookups, audits } }`.
