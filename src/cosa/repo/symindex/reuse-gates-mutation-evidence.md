# Replay gates (ii) and (iii): mutation evidence

Plan 2, phase W-C exit gate: (ii) the receipt id recomputed from tool, query, `index_sha`, model and threshold equals the stored id; (iii) a corrupted cache entry and a missing entry each return a named error rather than a verdict. The plan asks for both to be "proved by mutation: edit one input, or corrupt the entry, and name the test that reddens". This file is that record. The earlier runs (Tiberius, task-store row `9babe43d`, amendments of 2026-10-01 00:05, 00:29 and 00:40 UTC) live only in the store; their arm list was counted, not listed.

## What was run

Run by John on 2026-10-07, 12:21 to 12:30 EDT, in a detached seat worktree at `67ef47f79` (`08509073d` plus one test-only commit; `src/lupin_mcp/reuse_tools.py` is byte-identical to `08509073d`, sha1 `a2ec947b24`).

- Test set: `src/tests/unit/test_reuse_tools.py` only, run as `pytest src/tests/unit/test_reuse_tools.py -q -p no:cacheprovider` with `LUPIN_ROOT` and `PYTHONPATH` pinned to the seat tree. **Baseline: 128 passed, 0 failed.** The earlier 10-file reuse set was not re-run.
- One edit per arm to `reuse_tools.py`. The anchor text matched exactly once (the edit tool refuses otherwise) and `git diff --numstat` showed the one-line change. `src/scripts/purge-pycache.sh` ran before each arm. After each arm the file was restored with `git checkout HEAD --` and its sha1 read back as `a2ec947b24`.
- Kill signal: a test that passed in the baseline now fails. Every arm was killed.

## Arms

| # | Gate | Edit to `reuse_tools.py` | Result | Tests that failed |
| --- | --- | --- | --- | --- |
| 1 | ii | `query` dropped from `receipt_id()` | 4 failed, 124 passed | `test_reuse_extend_and_new_verdicts_and_the_request_shape`, `test_each_uncertain_path_asserts_its_cause_not_only_the_verdict`, `test_the_receipt_id_changes_with_every_input_including_the_prompt_template`, `test_gate_ii_the_id_recomputes_from_the_stored_inputs_and_an_edited_input_is_named` |
| 2 | ii | `index_sha` dropped | 3 failed, 125 passed | `test_an_l0_edit_changes_index_sha_and_so_the_receipt`, `test_read_capability_pages_errors_and_receipt`, `test_gate_ii_...` |
| 3 | ii | `model` dropped | 2 failed, 126 passed | `test_the_receipt_id_changes_with_every_input_...`, `test_gate_ii_...` |
| 4 | ii | `policy` dropped | 1 failed, 127 passed | `test_the_receipt_id_changes_with_every_input_...` |
| 5 | ii | `prompt_template_hash` dropped | 2 failed, 126 passed | `test_the_receipt_id_changes_with_every_input_...`, `test_gate_ii_...` |
| 6 | ii | `causes` dropped | 3 failed, 125 passed | `test_an_incomplete_receipt_never_shadows_the_complete_one_for_the_same_question`, `test_the_receipt_id_changes_with_every_input_...`, `test_fetch_similar_excludes_the_symbol_itself_and_reports_its_uncertainty` |
| 7 | ii | `tool` dropped | 1 failed, 127 passed | `test_the_receipt_id_changes_with_every_input_...` |
| 8 | ii | `tool_version` dropped | 1 failed, 127 passed | `test_c2a_the_tool_version_is_part_of_the_receipt_id` |
| 9 | iii | `JevCache.get`: the `response_sha` check removed | 1 failed, 127 passed | `test_gate_iii_a_corrupt_or_missing_input_is_a_named_error_never_a_verdict` |
| 10 | iii | `JevCache.get`: the `request_hash == key` check removed | 1 failed, 127 passed | `test_gate_iii_...` |
| 11 | iii | `sweep()`: the `CACHE_MISSING` raise on a frozen miss removed | 2 failed, 126 passed | `test_replay_frozen_is_deterministic_and_head_notices_a_change`, `test_gate_iii_...` |
| control | | restore, purge, re-run | **128 passed, 0 failed** (12:29 EDT) | none |

## Findings

- **Eleven of eleven arms killed.** Every receipt-id input and every cache check is guarded by a named test.
- **`test_gate_ii_...` alone reddens for four of the eight id inputs** (`query`, `index_sha`, `model`, `prompt_template_hash`). For `policy`, `causes`, `tool` and `tool_version` the killer is a different test (`test_the_receipt_id_changes_with_every_input_...`, `test_c2a_...` and two others). Gate (ii) holds as a set of tests, not through the test that carries its name.
- **Not re-run here:** the over-the-wire arms (removing `@_offloaded_tool`, a module-level import of `reuse_tools`), the `NAME_RE` arms, the C1/C2 arms and the snapshot-damage arms recorded in the earlier runs. Those tests exist; this file does not claim their arms were repeated.
- A surviving mutant has four explanations (weak test, broken harness, equivalent mutant, fixture that cannot discriminate). None arose: no arm survived.
