---
capability: tfe-to-cc-prompt-bundles
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.tfe_to_cc.prompts.bundle_phase1.build_diagnosis_bundle_prompt@4f0ca8fc85
  - cosa.agents.tfe_to_cc.prompts.bundle_phase3.build_fix_bundle_prompt@1d8aff2497
  - cosa.agents.tfe_to_cc.prompts.output_contract.parse_diagnosis_block@fae8ac0c07
  - cosa.agents.tfe_to_cc.prompts.output_contract.validate_diagnosis_payload@b664cf0770
  - cosa.agents.tfe_to_cc.prompts.output_contract.parse_result_block@57be0d625b
  - cosa.agents.tfe_to_cc.prompts.output_contract.validate_result_payload@380610e654
  - cosa.agents.tfe_to_cc.prompts.output_contract.parse_result_from_git_log@d995e0488b
  - cosa.agents.tfe_to_cc.prompts.output_contract.parse_diagnosis_fallback@1091fc2ed7
---
# TFE-to-CC prompt bundles

The prompt builders and reply parsers for running the test-fix expediter's diagnose and fix steps on Claude Code instead of the SDK path in [[fix-expediter-tfe]]. It is a prompt layer only. No engine switch uses it yet.

## What it does
- `build_diagnosis_bundle_prompt` builds one markdown prompt for all failing-test clusters. Claude Code may read, grep and glob, but not edit, run shell commands or block on a question.
- Its reply must end in one `tfe-diagnosis` JSON block. Each cluster has `root_cause`, `error_category` (`code_bug`, `test_bug`, `fixture_bug` or `environment_bug`), `confidence` from 0 to 1, and optional `affected_components` and `notes`.
- `build_fix_bundle_prompt` builds a coordinator prompt. It plans with `TodoWrite`, then dispatches one `Task` subagent per fix in an isolated worktree, using an embedded brief. It forbids `git push` and a full test run.
- A fix commit reads `fix(tfe): C<n> <title>`. The reply ends in one `tfe-result` block with a `verdict` of `fixed`, `failed` or `unclear` per cluster.
- Both builders raise `ValueError` on an empty list.

## Invariants
- `parse_diagnosis_block` and `parse_result_block` never raise. They return `None` for no block, bad JSON or a missing `clusters` key.
- `validate_*_payload` return `( ok, issues )`. A `fixed` cluster must carry `commit_sha`, which may be an explicit `null`.
- `parse_result_from_git_log` is the fallback when the result block is lost. It reads `fix(tfe): C<n>` lines, newest first. A cluster with no commit is `unclear`, since missing and failed look alike.
- `parse_diagnosis_fallback` scrapes `Cluster Cn` headings and returns a payload only when it recovers a root cause and a category for a cluster.

## How it is used
- Only `src/scripts/tfe_to_cc_phase1_smoke.py`, `src/scripts/tfe_to_cc_phase3_live.py` and their tests import it. The TFE orchestrator does not.
- The package docstring names two engine keys for the diagnose and fix steps as future work, each set to `sdk` or `claude_code`. Neither key is in the INI.
- The design is `src/docs/decisions/2026.04.19-tfe-to-cc-parallel-claude-code-engine.md`.
- To wire it in, add the engine keys and call the builders from the TFE orchestrator, then parse with the functions here.
