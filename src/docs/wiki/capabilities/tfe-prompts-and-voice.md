---
capability: tfe-prompts-and-voice
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.test_fix_expediter.prompts.cluster.build_cluster_prompt_stub@58de2c4b8f
  - cosa.agents.test_fix_expediter.prompts.diagnosis.build_diagnosis_prompt@d34bbdf959
  - cosa.agents.test_fix_expediter.prompts.proposal.build_proposal_system_prompt@26b66c5c46
  - cosa.agents.test_fix_expediter.prompts.proposal.build_proposal_prompt@d9d48a99bb
  - cosa.agents.test_fix_expediter.prompts.fix.build_fix_prompt@9109cdd587
  - cosa.agents.test_fix_expediter.prompts.fix.build_verification_prompt@bee7820df0
  - cosa.agents.test_fix_expediter.prompts.fix.build_redelegation_prompt@b5d0a1bf7b
  - cosa.agents.test_fix_expediter.cosa_interface.notify_progress@c527c06baa
  - cosa.agents.test_fix_expediter.cosa_interface.ask_confirmation@b015a79b37
  - cosa.agents.test_fix_expediter.cosa_interface.get_feedback@dc91fb4cf6
  - cosa.agents.test_fix_expediter.cosa_interface.present_choices@ded6f26cca
---
# Test fix expediter prompts and voice

The per-cluster prompts for each agent role, and the voice functions the test fix expediter uses. Compare [[bfe-prompts-and-voice]].

## What it does
- `build_cluster_prompt_stub` is a stub for the model clustering step. The full prompt is not written yet.
- `build_diagnosis_prompt` builds one cluster's diagnosis prompt: cluster metadata, per-failure records with truncated tracebacks and the iteration limits.
- From the second iteration the diagnosis prompt adds the earlier attempts, so the lead agent refines.
- `build_proposal_system_prompt` caps the number of fixes the lead may propose, and asks for them ranked by confidence.
- `build_proposal_prompt` carries the diagnosis, the affected components and a short list of the cluster's failures.
- `build_fix_prompt` tells the coder to apply the selected fix's changes as written.
- `build_verification_prompt` tells the tester to run pytest filtered to the cluster's failing tests only.
- `build_redelegation_prompt` hands the tester's failure report back to the coder for another iteration.
- The fix prompt builders register under the key `tfe` in `FIX_PROMPT_BUILDERS` when the module is imported.
- `notify_progress`, `ask_confirmation`, `get_feedback` and `present_choices` pass straight through to the bug fix expediter's versions.

## Invariants
- The sender id is `test_fix_expediter@lupin.deepily.ai`, so notifications are attributed to this agent.
