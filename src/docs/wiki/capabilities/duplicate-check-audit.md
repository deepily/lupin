---
capability: duplicate-check-audit
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_audit.index_id_finder@39c1679d22
  - lupin_mcp.duplicate_check_audit.queue_audits@48f4a6a0f8
---
# Duplicate check audit queue
`queue_audits` in `lupin_mcp.duplicate_check_audit` queues a known-miss shadow audit for each duplicate the daily check finds. The queue is described in [[repo-tools-candidate-shadow-audit-queue]].

## What it does
- `index_id_finder( entries )` builds `index_id_of( finding )`, which names a finding the way the sweep's symbol index does. It matches on file and name. When a file holds several entries of that name, the one at the finding's line wins, else the nearest, the earlier on a tie. It returns None when there is none. The finding's own `d-` id is never used, because the index does not know it.
- `queue_audits( findings, tie_of, receipt_of, data_dir, today, index_id_of )` first asks `index_id_of` for the finding's index id. A finding the index does not hold counts `not_in_index` and is neither tied nor queued, because the sweep would refuse its id. It ties each other finding to the lookup receipt behind it with `tie_of`. The tie finder and the receipt reader are passed in.
- It queues the lookup when the receipt holds a need. The item carries the known-miss marker, the tie kind and the finding's index id, which the sweep leaves out.
- It returns `{ counters, reasons }`. Counters are `queued`, `heuristic_queued`, `not_in_index`, `no_tie`, `no_need_text`, `no_shortlist`, `receipt_unreadable` and `tie_error`. `reasons` maps a finding id to why it was not queued.
- A heuristic tie counts under both `queued` and `heuristic_queued`.
- A tie to a `fetch_similar` receipt counts `no_need_text`, because that receipt holds a symbol id and not a need.
- A receipt that is not a `check_exists` shortlist answer counts `no_shortlist`.

## Don't
- Do not expect a lookup count or a sample. Only the pending-file write is used.
- Nothing here runs a model, sends a request or reads the store.
