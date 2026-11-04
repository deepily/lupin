---
capability: needset-call-cap
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.model_transport.set_charge_hook@986d84594a
  - lupin_mcp.reuse_needset.call_cap.stage@4765009b1e
  - lupin_mcp.reuse_needset.call_cap.CallCap@64919847bf
  - lupin_mcp.reuse_needset.call_cap.CallCap.rows@e0947aa0e8
  - lupin_mcp.reuse_needset.call_cap.CallCap.used@e827ca820a
  - lupin_mcp.reuse_needset.call_cap.CallCap.by_stage@76f106b896
  - lupin_mcp.reuse_needset.call_cap.CallCap.charge@a7d86b9836
  - lupin_mcp.reuse_needset.call_cap.CallCap.installed@fe4a57edf4
  - lupin_mcp.reuse_needset.call_cap.CallCap.guard@93b470386b
  - lupin_mcp.reuse_needset.call_cap.charge_attempt@a521d40754
---
# Need set: call cap

One shared cap on model calls for Set B's first-thousand run, 1,314 in all. The first attempt spent 686, and Rick raised the budget by about 1,000 on 1 November 2026. Each stage may also have a budget of its own. Drafting, the checker's judge and the agent probe are all counted, whichever stage makes the call. Embedding calls to our own server are not model calls and are not counted.

## Counting
- `CallCap` keeps its count in one ledger file that outlives the process. A new cap over the same file starts from the calls already there, so a restarted run cannot get a fresh 1,314. A new run folder starts at zero.
- `charge` counts one call before it is made, under an exclusive file lock. Call 1,315 raises `CALL_CAP_REACHED`, writes nothing and contacts no model. A call past the running stage's budget (`stage_limits`) raises `STAGE_BUDGET_REACHED` instead. The other stages keep their own calls. A budget of none refuses the stage's first call.
- `rows`, `used` and `by_stage` read the ledger. A torn last line is skipped.
- `stage` names the stage that makes the calls inside a block, and each ledger row carries the name.

## Wiring
- `set_charge_hook` on the model transport names a function that sees every call first. A hook that raises refuses the call. The agy retry also calls the hook before each retried try, so a retry counts as a call.
- `installed` sets the hook to the cap's `charge` for a block and puts the earlier hook back after it. It does the same for the Jev transport's hook, so each HTTP attempt to Jev, retries included, counts beside the drafter's calls.
- `guard` wraps an async call that reaches a model by another door, so it charges first.
- `charge_attempt` is for a caller that charges itself, as the agent probe does before each attempt. It raises `CAP_NOT_INSTALLED` when a stage is running and no cap is installed. Such a caller must not also be wrapped by `guard`.
