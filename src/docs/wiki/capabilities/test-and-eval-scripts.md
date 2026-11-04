---
capability: test-and-eval-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.test_harness.mock_job.MockAgenticJob@bce2eb7919
  - cosa.agents.test_harness.mock_submit.build_plain_mock_job@23b298c517
  - scripts.check_schema_parity.compute_drift@d5403cac21
  - scripts.check_schema_parity.classify@fea75cae44
  - scripts.check_schema_at_head.classify@eea0a7d7a4
  - scripts.check_dead_claims.find_live_claims@55856ed256
  - scripts.bridge_pin_sweep.sweep@6b207ec6e8
  - scripts.check_bundle_freshness.check_bundle@bacc3d7387
---
# Test and eval scripts

The runner scripts, probes and checkers used to run test tiers and to ask narrow questions about the tree. Suites reach `:8000` only through [[scheduled-test-suite]].

## Tier runners (`src/tests/run-*.sh`)
- `run-unit-tests.sh`, `run-smoke-tests.sh`, `run-pytest-direct.sh` and `run-smoke-direct.sh` pass their arguments to pytest or to a smoke file.
- `run-all-tests.sh` runs the suites in pyramid order, continues past failures unless `--fail-fast` is given, and exits zero only if all passed.
- `run-integration-tests.sh`, `run-typescript-tests.sh` and `run-presentation-regression.sh` are the heavy tiers. `run-v2-eval.sh` runs the v2 paired eval.
- `run-typecheck-gate.sh`, `run-stylelint-gate.sh` and `run-doclint-gate.sh` are the cheap gates; see [[doc-lint-gate]].
## Coverage, census and mutation
- `run-coverage-gate.sh` checks the total against `fail_under` and checks the frame holds every file it claims. Exit 1 is a breach; 2, 3, 4 and 6 mean no trustworthy number.
- `run-census-guards.sh` runs the unit-tier guards, needs no server, and exits 2 if the selection finds nothing or cannot read a file. A file picked by name runs whole; in any other file each `test_every_*` function runs by node id. `--list` prints the selection and runs nothing.
- `detect_thread_credited_coverage.py`, `find_interchangeable_assertions.py` and `bridge_pin_sweep.py` are report-only triage aids over tests.
- `falsify.py` mutates one named function, runs a suite, and restores the file. Exit 0 means a test went red, 1 none did, 2 the mutation was refused.
- `MockAgenticJob` and `build_plain_mock_job` in `src/cosa/agents/test_harness/` simulate a long agentic job without model calls.

## Read-only checks
- `check_schema_parity.py` compares ORM columns with the live database using SELECTs only, and exits non-zero on drift.
- `check_schema_at_head.py` asks whether the database is at the head migration; it must run inside the container.
- `check_dead_claims.py` greps a design document for killed claims that still read as live.
- `check_bundle_freshness.py`, `compose_drift_probe.py` and `bounce_busy_probe.py` check bundles, compose drift and idleness.

## Scripts that change state
- `submit-test-suite.py` posts a job to `/api/v2/submit`. It does not check that the venue is idle.
- `run-test-suite-live-smoke.sh` refuses unless `:8000` reports idle, then runs one file there.
- `purge-pycache.sh` deletes and reconverts bytecode. `migrate-pyc-to-checked-hash.sh` converts it, and `--verify` only reports.
- `migrate_solution_snapshots.py` rewrites snapshot files and offers `--dry-run`.
