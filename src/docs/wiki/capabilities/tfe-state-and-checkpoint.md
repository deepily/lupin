---
capability: tfe-state-and-checkpoint
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.test_fix_expediter.state.TestRemediationContext@de0de006d8
  - cosa.agents.test_fix_expediter.state.FailureCluster@39eb6caa87
  - cosa.agents.test_fix_expediter.state.TestDiagnosisResult@b5aac8e1b9
  - cosa.agents.test_fix_expediter.state.TFEProposedFix@dfd337ebd1
  - cosa.agents.test_fix_expediter.state.TFEState@ba4864ded6
  - cosa.agents.test_fix_expediter.state.create_initial_state@5f6e2d8871
  - cosa.agents.test_fix_expediter.state.CheckpointData@d2de9b9460
  - cosa.agents.test_fix_expediter.state.StalledException@9fd0193567
  - cosa.agents.test_fix_expediter.state.VoiceGateTimeoutError@dcfab8eb34
  - cosa.agents.test_fix_expediter.state.VoiceGateUnreachableError@59331f2f04
---
# Test fix expediter state and checkpoint

The records and signals of a test fix expediter run. They parallel the bug fix expediter's, but one run covers many failures grouped into clusters. See [[fix-expediter-tfe]] and [[bfe-data-model]].

## What it does
- `TestRemediationContext` is the parsed snapshot of a failed test suite job: its failures, summary and the job's identifiers.
- `FailureCluster` groups failure indices that share a root cause. It carries a cluster id, an error signature, a hypothesis and a confidence.
- `TestDiagnosisResult` extends the bug fix expediter's diagnosis with a cluster id and the test symptoms seen.
- `TFEProposedFix` is one proposed fix for one cluster. It repeats the bug fix fields with a required cluster id.
- `TFEState` is the whole run's state. `create_initial_state` returns it in the loading phase with every field initialized.
- `CheckpointData` is the state saved in the job's metadata when the job stalls. A resume rebuilds the orchestrator from it.
- `StalledException` asks the job to stall cleanly with its checkpoint. The job records `STALLED` and not a failure.
- `VoiceGateTimeoutError` means the question was asked and nobody answered. Its `delivered` flag says whether the ask reached a human.
- `VoiceGateUnreachableError` means the asking call itself broke, and carries the phase and the original cause.

## Invariants
- Both voice gate errors lead to a checkpoint and a stall. Neither is read as an approval.
- `TFEProposedFix` does not inherit from the bug fix `ProposedFix`, so the cluster id can be required.
