---
capability: coverage-frame-and-visual-failures
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.coverage_frame.coverage_can_see@9727cdce59
  - cosa.utils.coverage_frame.is_omitted@6519b2bb6f
  - cosa.utils.coverage_frame.is_package_dir@bc90abb66b
  - cosa.utils.coverage_frame.omit_patterns@74567de182
  - cosa.utils.coverage_frame.report_paths@80ad3d6272
  - cosa.utils.coverage_frame.source_dirs@986a7b4fa8
  - cosa.utils.coverage_frame.unreachable_declarations@fa7252a918
  - cosa.utils.coverage_frame.unreachable_subdirs@8c3fb60903
  - cosa.utils.coverage_frame.unseen_python_files@948c1fb136
  - cosa.utils.visual_failures.make_run_id@122c024b47
  - cosa.utils.visual_failures.prepare_run_dir@3bb65fec7d
  - cosa.utils.visual_failures.session_collects_visual@43bded8f3f
---
# Coverage frame and visual failures

`coverage_frame` checks the coverage config against the disk, so a file the report cannot see is named. `visual_failures` names and prunes the per-run folder for snapshot failures. The gate itself is in [[gate-reachability]].

## What it does
- `source_dirs` and `omit_patterns` read `pyproject.toml` with `tomllib`.
- `coverage_can_see( path )` mirrors coverage's rule that a dot in the file name hides it.
- `is_package_dir`, `is_omitted` and `report_paths` are helpers for that check.
- `unseen_python_files( root, source_entries, reported_paths, omit_globs )` returns `( unexpected, unseeable )`.
- `unreachable_subdirs` lists non-package directories with visible `.py` files. `unreachable_declarations` returns declared-unseeable paths the census never reached.
- `src/tests/run-coverage-gate.sh` imports the module.
- `make_run_id` picks `LUPIN_TEST_RUN_ID`, then `LUPIN_TEST_SUITE_JOB_ID`, then a UTC stamp with the pid.
- `session_collects_visual( items )` is True when any item uses an `assert_snapshot*` fixture.
- `prepare_run_dir( base, run_id, keep_days=14, keep_newest=5 )` returns `base/run_id` and prunes older sibling directories.

## Don't
- Don't pass a run id that is not a plain name. `prepare_run_dir` raises `ValueError`.

## Invariants
- The module only reads the config and the disk. It runs no tests.
