---
capability: needset-loss-trace
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.loss_trace.asked_ids@0847f41e7f
  - lupin_mcp.reuse_needset.loss_trace.check_need@d4336855da
  - lupin_mcp.reuse_needset.loss_trace.index_locator@e278b6c99a
  - lupin_mcp.reuse_needset.loss_trace.classify@ef032f3b45
  - lupin_mcp.reuse_needset.loss_trace.trace_need@a2aa83da21
  - lupin_mcp.reuse_needset.loss_trace.trace_version@36c418760c
  - lupin_mcp.reuse_needset.loss_trace.trace_all@dc02e38341
  - lupin_mcp.reuse_needset.loss_trace.extend_key@b6e8c993a7
  - lupin_mcp.reuse_needset.loss_trace.retrace@c9ad589de6
  - lupin_mcp.reuse_needset.loss_trace.confirmation_items@91778eb0ec
  - lupin_mcp.reuse_needset.loss_trace.summarize@c6b2aa3ea7
  - lupin_mcp.reuse_needset.loss_trace.write_report@6477e4e601
---
# Need set: loss trace

Finds where, in the search pipeline, a need's key gets lost. Each need goes through four stages: retrieved, rated relevant, read, and ruled the same job. The first stage that fails names the loss. The probe is on [[needset-agent-probe]].

## Tracing
- `check_need` asks the checker about one need on the candidate route and returns its receipt, stored nowhere. The need's seed is left out, so a need is not found by its own source.
- `asked_ids` lists the entries sent to the judge: the stage's ids plus its widened ids, sorted. A receipt with no candidate stage, or a failed one, raises `RECEIPT_FIELD_ABSENT`.
- `index_locator` builds the function that finds a symbol's file and line range in the searchable index.
- `classify` names where a matched need's key was lost, as the first stage whose set of key symbols is empty. `ALT_MATCH` replaces a failed ruling when a shortlisted symbol outside the key was ruled the same job.
- A nothing need gets `FALSE_MATCH` if the checker ended with reuse or extend or the probe ruled a symbol the same job, else `CORRECT_NO_MATCH`.
- `trace_need` traces one need. The probe runs only when its rulings can change the answer.
- `trace_version` names the trace, so a changed checker call, classifier or probe prompt is a ledger miss.
- `trace_all` traces every need and skips those the ledger holds. The ledger key holds the need, source commit, index hash, checker commit, probe model and trace version.

## Confirmation and report
- `extend_key` adds reviewer-confirmed alternatives to a need's key, sorted, with the version raised by one. The need's id stays the same.
- `retrace` classifies a stored record again against the key as it now stands, from the stored evidence, so no call is made.
- `confirmation_items` builds one reviewer item for every alt match and false match, showing the proposed alternatives' source or the ruled symbols' source.
- `summarize` counts matched needs by loss stage, kind and language, with the 95 percent upper bound on the miss rate. `write_report` writes a JSON and a markdown report, with the figures before and after the confirmations.
