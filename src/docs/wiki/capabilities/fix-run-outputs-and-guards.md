---
capability: fix-run-outputs-and-guards
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.shared.plan_writer.PlanWriter@2eff79209a
  - cosa.agents.shared.report_writer.ReportWriter@e6ec009b2c
  - cosa.agents.shared.resume_guard.resume_covers@54f618ac21
  - cosa.agents.shared.sdk_error_result.error_result_text@670be3458c
  - cosa.agents.shared.sdk_error_result.login_hint@ae2c20cf15
  - cosa.agents.shared.sdk_error_result.raise_error_result@de5e8eacd5
  - cosa.agents.shared.fix_executor.BFETimeoutError@0414fa1b5b
  - cosa.agents.shared.diagnosis_json.parse_diagnosis_json@42f2080b38
  - cosa.agents.shared.diagnosis_json.fallback_diagnosis_fields@b6b6ad3701
  - cosa.agents.shared.coder_stream.read_coder_stream@3d8fdfb90c
---
# Fix run outputs and guards

Small helpers shared by both fix expediters. They write the plan and the final report, decide which phases a resumed run skips, and shape failures. Related: [[fix-shared-primitives]].

## What it does
- `PlanWriter.write_plan` writes a markdown plan with the failure, the diagnosis and the proposed fixes. The file lands under `io/swe-team/plans/<email>/`.
- `PlanWriter.update_implementation_log` and `update_git_references` replace a placeholder line in that plan with the fix result and the git result.
- Both update methods do nothing when the file is missing or the placeholder is already gone.
- `ReportWriter.write` writes a final report under `io/swe-team/reports/<email>/`. The title and a timestamp head the file.
- The report slug is cut to six lowercase words, with underscores turned into hyphens. An empty slug becomes `unknown`.
- `resume_covers` returns true when a saved checkpoint ordinal is at or past a phase's ordinal. It returns false when the run is not a resume.
- `error_result_text` names the result subtype, the text from the command line tool and any errors, each cut to 500 characters.
- `login_hint` appends the renew-your-login sentence when the text holds `API Error: 401`.
- `raise_error_result` logs the failure and raises `RuntimeError` with the hint included.
- `BFETimeoutError` is raised when one agent call outlives the wall-clock budget.
- `fallback_diagnosis_fields( reason )` builds the fields both expediters give a fallback diagnosis: confidence 0.1, category `unknown`, one evidence line.
- `read_coder_stream` reads a Coder's message stream to its end. It returns the joined text and each distinct edited path, first seen first. Both expediters call it from `_delegate_to_coder`.
- It checks the timeout on every message and the iteration limit once at the end. It stops at the first message after a cancel.
- Each `Edit` or `Write` calls the post-tool hook. Each tool use and result message sends one progress line. An error result goes through `raise_error_result`.
- The caller passes its own message classes, logger and hook, so its tests can replace them. `SweTeamOrchestrator._redelegate_with_feedback` is a third near-copy, not folded in.

## Invariants
- `BFETimeoutError` is not a `SafetyLimitError`. The fix executor re-raises it, so the job ends dead and the pool slot is released.
- A negative saved ordinal marks a checkpoint with no usable phase, and `resume_covers` returns false for it.
- `resume_covers` raises `KeyError` for a phase missing from the ordinal map.
