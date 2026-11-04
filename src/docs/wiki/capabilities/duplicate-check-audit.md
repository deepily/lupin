---
capability: duplicate-check-audit
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_audit.queue_audits@120850fb12
---
# Duplicate check audit queue
`queue_audits` in `lupin_mcp.duplicate_check_audit` queues a known-miss shadow audit for each duplicate the daily check finds. The queue is described in [[repo-tools-candidate-shadow-audit-queue]].

## What it does
- `queue_audits( findings, tie_of, receipt_of, data_dir, today )` ties each finding to the lookup receipt behind it with `tie_of`. The tie finder and the receipt reader are passed in.
- It queues the lookup when the receipt holds a need. The item carries the known-miss marker, the tie kind and the finding's own id, which the sweep leaves out.
- It returns `{ counters, reasons }`. Counters are `queued`, `heuristic_queued`, `no_tie`, `no_need_text`, `no_shortlist`, `receipt_unreadable` and `tie_error`. `reasons` maps a finding id to why it was not queued.
- A heuristic tie counts under both `queued` and `heuristic_queued`.
- A tie to a `fetch_similar` receipt counts `no_need_text`, because that receipt holds a symbol id and not a need.
- A receipt that is not a `check_exists` shortlist answer counts `no_shortlist`.

## Don't
- Do not expect a lookup count or a sample. Only the pending-file write is used.
- Nothing here runs a model, sends a request or reads the store.
