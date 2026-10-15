---
capability: bfe-data-model
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.bug_fix_expediter.config.BugFixExpediterConfig@f55f3365e5
  - cosa.agents.bug_fix_expediter.dead_job_packager.package_dead_job@d7b747b6e5
  - cosa.agents.bug_fix_expediter.state.BFEState@34cf061b0c
  - cosa.agents.bug_fix_expediter.state.DeadJobContext@875ceaf7e6
  - cosa.agents.bug_fix_expediter.state.DiagnosisResult@3bb4c8e17f
  - cosa.agents.bug_fix_expediter.state.FixResult@7c0a6fc0b4
  - cosa.agents.bug_fix_expediter.state.ProposedFix@0f69c7b948
  - cosa.agents.bug_fix_expediter.state.create_initial_state@ae6e02fdd5
---
# Bug fix expediter data model

The bug fix expediter turns one failed or interrupted job into a diagnosis, a proposed fix and an applied fix. These are the records it passes between phases. The run itself is in [[fix-expediter-bfe]].

## What it does
- `package_dead_job` reads one row of the job history by its `id_hash` and returns a `DeadJobContext`. It returns `None` when no row matches.
- `package_dead_job` raises `ValueError` for an empty id, or for a job whose status is neither `failed` nor `interrupted`.
- `DeadJobContext` carries the error, the stack trace taken from the job's metadata, the question text and the routing command.
- `DiagnosisResult` holds the root cause, an error category, a confidence from 0 to 1, evidence, affected components and a transient flag.
- `ProposedFix` holds a title, a description, a fix type, a confidence, a risk level, an effort estimate and a list of file changes.
- `FixResult` records whether the fix applied and succeeded, how many attempts ran, and the git strategy, commit, branch and pull request address.
- `FixResult` also holds the id of the job that was resubmitted after the fix.
- `BFEState` is a typed dictionary of the whole run: input, context, diagnosis, fixes, the selected fix, the result, the retry job and the phase.
- `create_initial_state` returns a `BFEState` in the `packaging` phase, with empty lists and every other field unset.
- `BugFixExpediterConfig` holds the models, the iteration and budget limits and the trust mode. `from_config` fills it from the configuration manager.

## Invariants
- A fresh config is switched off: `enabled` and `push_fix_branch_enabled` both default to false, and `trust_mode` defaults to `shadow`.
- Confidence fields are validated between 0 and 1 when the model is built.
