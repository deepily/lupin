---
capability: gate-reachability
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.repo.gate_reachability.read_suite_scripts@977ef43989
  - cosa.repo.gate_reachability.find_gate_targets@2fbf2510b3
  - cosa.repo.gate_reachability.find_test_file_population@6248e6882a
  - cosa.repo.gate_reachability.find_unreferenced_test_files@3300ece73e
  - cosa.repo.gate_reachability.find_zero_collect_test_files@1ca5d01d8b
  - cosa.repo.gate_reachability.find_stale_allowlist_entries@5fb89194f9
  - cosa.repo.gate_reachability.find_stub_bodied_tests@c5df40e2bb
---
# Gate reachability

A census of the test tree. It finds test files that no gate runner can reach, so they add no signal and cannot fail a merge. The checks are plain functions in `cosa.repo.gate_reachability`.

## What it does
- `read_suite_scripts` reads the `SUITE_SCRIPTS` dict literal in `src/cosa/agents/test_suite/job.py` as source text. It does not import the module.
- `find_gate_targets` starts from those runner scripts and follows every `.sh` file they name. It keeps each `src/...` path that exists on disk. A `$SCRIPT_DIR/x` token counts as `x` beside the runner. Comment lines are skipped.
- `find_test_file_population` lists every `test_*.py` under `src/` on disk, not in git. It leaves out the `.claude`, `.venv`, `node_modules`, `__pycache__`, `tmp`, `lupin-mobile` and `lupin-plugin-firefox` path parts.
- `find_unreferenced_test_files` returns the population files that no target names, directly or by an ancestor directory.
- `find_zero_collect_test_files` returns reachable files that define no test. A module-level `test_*` function, a `Test*` class, or a `TestCase` subclass with a `test_*` method counts as a test.
- `find_stale_allowlist_entries` returns ledger entries that are absent, or that are now reachable and define a test.
- `find_stub_bodied_tests` returns reachable `path::name` entries whose body is only a docstring, `pass`, `...`, `assert True` or `raise NotImplementedError`.

## Invariants
- A path token that is only the root of a glob, such as `src/tests` in `src/tests/**/*.test.ts`, is not a target. Accepting it would make every file reachable.
- The exclusions apply to the path inside the project. A worktree under `.claude/worktrees` is therefore not excluded as a whole.
- A file that does not parse is not reported as barren, because its parse error already fails collection.
- A `TestCase` subclass that inherits through a project-local base is not seen. Such a file reads as barren and needs a ledger entry.
- Reachability is necessary for a gate signal, never sufficient. The census cannot tell whether a reached test asserts anything.

## How it is used
- `test_gate_reachability_census.py` runs the unreferenced, zero-collect and stale-entry checks in the unit tier. Its ledger is `src/tests/unit/gate-reachability-allowlist.json`.
- Each ledger entry names a file someone chose not to gate, with a dated reason, and the file must be tracked.
- `src/tests/run-census-guards.sh` picks the test up by its name. Run it before review, since new test files can turn it red.
- Nothing calls `find_stub_bodied_tests`. `test_stub_bodied_test_detector.py` tests its vacuity check only.
- A new test directory is gated by naming it in a runner script that `SUITE_SCRIPTS` reaches.
