---
capability: reuse-shadow-pending-cap
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.reuse_shadow.pending_cap@eb05ff5be4
  - lupin_mcp.reuse_shadow.pending_cap_for@6b559fa2bd
---
# Reuse shadow audit queue cap

The shadow audit queue ([[reuse-shadow-audit-wiring]]) holds no more items than the spend ledger can pay to audit.

## What it does
- `pending_cap( ledger_file )` returns `( limit minus total held ) // MEAN_AUDIT_TOKENS`, never below 0.
- A ledger file that does not exist gives `None`, so a host with no ledger has no cap.
- A ledger that exists and cannot be read gives 0, so nothing queues that could not be paid for.
- `pending_cap_for( ctx )` reads the context's own ledger, or the repository's fleet ledger when the context holds none.

## How it is used
- `queue_lookup` takes the result as `max_pending`. A sampled lookup that finds the queue full is counted and not queued.
- `enqueue_pending` and `pending_count` do the refusing and the counting ([[repo-tools-candidate-shadow-audit-queue]]).
