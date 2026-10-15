---
capability: repo-tools-docker-smoke-report
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.docker_smoke_report.summarize@eb1b551546
  - cosa.repo.docker_smoke_report.render@0aacf1efc4
  - cosa.repo.docker_smoke_report.main@50b5287115
---
# Docker smoke report

Reads the junit XML from `src/tests/run-docker-smoke-gate.sh` and says whether the step passed. Inside the merge gate's containers every test of the three docker smoke files skips, so a skip here must not read as a pass.

## What it counts
- `summarize( junit_path, expected=EXPECTED_FILES )` returns `total`, `passed`, `failed`, `skipped`, `skips` (a `node::name: reason` string each) and `missing`.
- A skip, a failure and an error all count as failed. An expected file with no test case in the report is listed in `missing` and also adds one to `failed` per file.
- The expected files are `test_credential_mount_shape`, `test_db_roles_rollback_real_postgres` and `test_db_grants_real_postgres`.
- An unreadable path raises `OSError`, and a file that is not XML raises `ParseError`.

## Output and exit codes
- `render( summary )` returns `SKIPPED` and `MISSING` lines, then `Total Tests`, `Passed`, `Failed` and `Skipped` lines, one each.
- `main( argv )` prints the render of `argv[1]`. It returns 0 when nothing failed and 1 otherwise. It returns 2 when the report cannot be read, with a `REFUSING` line and no counts.
- Run it as `python -m cosa.repo.docker_smoke_report <junit.xml>`.
