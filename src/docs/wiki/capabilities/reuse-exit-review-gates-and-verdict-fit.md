---
capability: reuse-exit-review-gates-and-verdict-fit
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_exit_gate.merge_call_logs@3a57993167
  - lupin_mcp.reuse_exit_gate.entry_of@fef1adda22
  - lupin_mcp.reuse_exit_gate.receipts_by_symbol@b261874f7a
  - lupin_mcp.reuse_exit_gate.exclusions_by_symbol@3da1f9d049
  - lupin_mcp.reuse_exit_gate.parse_rulings@b49e87fcd2
  - lupin_mcp.reuse_exit_gate.unparsed_ruling_lines@3c1558bacb
  - lupin_mcp.reuse_exit_gate.parse_searched@9a7451667b
  - lupin_mcp.reuse_exit_gate.unparsed_searched_lines@28d8aa2698
  - lupin_mcp.reuse_exit_gate.searches_by_symbol@39f6a638ca
  - lupin_mcp.reuse_exit_gate.check_run@118d627e6c
  - lupin_mcp.reuse_exit_gate.run_gate@f77e9796fe
  - lupin_mcp.reuse_exit_gate.main@d1b539ae76
  - lupin_mcp.reuse_review_gate.ini_path@5f083ec73c
  - lupin_mcp.reuse_review_gate.read_gating@0b46578416
  - lupin_mcp.reuse_review_gate.evaluate@918d5d9e57
  - lupin_mcp.reuse_review_gate.main@2ddaee2672
  - lupin_mcp.reuse_verdict_fit.receipt@d615c46108
  - lupin_mcp.reuse_verdict_fit.main@b446617cdc
---
# Reuse exit gate, review gate and verdict fit
Three small tools around the reuse review: did the reviewer look before ruling ([[reuse-record-search]]), does a finding block, and what threshold does the verdict use.

## Exit gate
- The gate takes two crew runs together. Each run has a diff of added definitions and a review document of `RULING` and `SEARCHED` lines. It passes only when the pair adds at least the minimum new definitions and every row is `OK` or `EXCLUDED`.
- `merge_call_logs( log_dir )` merges every per-session call log and counts lines that are not JSON objects. `entry_of` reads the `entry` argument of a logged call.
- `receipts_by_symbol` collects the receipts each symbol was asked about, from `fetch_similar` calls that logged no error. `exclusions_by_symbol` collects the definitions the tool refused to send, by cause.
- `searches_by_symbol` collects the recorded searches each symbol was searched under, from `record_search` calls that logged no error and a well-formed search id.
- `parse_rulings` and `parse_searched` read the ruling and `SEARCHED` lines. `unparsed_ruling_lines` and `unparsed_searched_lines` return lines that open as one but do not read as one.
- `check_run( added, receipts, rulings, ... )` gives each added symbol a status. `OK` needs a ruling citing the symbol's own receipt. A `DISTINCT` ruling also needs a recorded search whose every candidate has a `SEARCHED` line that is not `SAME_JOB`.
- `run_gate` runs it over the crew runs. `main` prints the result as JSON and returns 0 on a pass, 1 on a fail and 2 on a malformed `--run`.

## Review gate and verdict fit
- `read_gating` reads `reuse review gating` fresh from the configuration file. Only a clean `true` is true. `ini_path` names that file, or the env override.
- `evaluate( findings, gating )` returns `reject` only when gating is true and a finding remains. Findings come back in both modes. `main` returns 1 when the diff is rejected.
- The verdict fit's `receipt` fits the old question's one cut-off on the fit half of a recorded split. A person chooses the false-reuse rate. Its `main` writes the receipt once and never overwrites one.
