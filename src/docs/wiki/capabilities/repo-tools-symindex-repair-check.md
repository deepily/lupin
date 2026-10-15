---
capability: repo-tools-symindex-repair-check
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.repair_check.run_repair_check@b9599d9ad4
  - cosa.repo.symindex.repair_check.RepairResult@12a520890d
  - cosa.repo.symindex.repair_check.ReplayFailed@5f5ab22845
  - cosa.repo.symindex.repair_check.read_head@73f0c1d6e9
  - cosa.repo.symindex.repair_check.replayer_over@279c738e89
---
# Repair check

Replays a missed reuse receipt several times before and after a summary rewrite, to show whether the rewrite fixed the miss. The unit tier covers it over cached answers only.

## `run_repair_check( replay, rewrite, receipt_id, symbol, runs=5 )`
- Replays the receipt `runs` times. It calls `rewrite()` only when every before-run lacked the symbol, then replays `runs` more times, unless the first after-run shows the index unchanged. A `runs` that is not a positive int raises `ValueError`.
- It returns a `RepairResult( verdict, before, after, runs )`, where before and after count the runs that held the symbol, or None when not reached.
- `REPAIRED`: 0 before and all after. `ALREADY_MATCHED`: the symbol was in every before-run, so no miss was reproduced. `NOT_REPAIRED`: absent in every after-run.
- `FLIPPY_BEFORE` and `FLIPPY_AFTER`: a mixed count, which is no evidence either way.
- `NO_INPUT_CHANGE`: the first after-run saw the same index sha as the last before-run, so the rewrite changed nothing the replay reads. The check is coarse, because the sha moves for an edit to any symbol the sweep reads.
- `CALL_FAILED`: a replay raised `ReplayFailed`.

## Wiring to the replay tool
- `read_head( result )` takes the replay tool's result dict and returns `Replayed( ids, index_sha )` from its HEAD shortlist. An error result, a missing head, or a head uncertain for any cause but `LOW_CONFIDENCE` raises `ReplayFailed`.
- `replayer_over( replay_tool, first_repeat=1 )` returns the `replay( receipt_id )` callable. The k-th call passes `repeat = first_repeat + k - 1`, so every replay is its own draw. Pass a higher base to re-check a receipt with new draws, since the same base reads the first check's cached answers.
