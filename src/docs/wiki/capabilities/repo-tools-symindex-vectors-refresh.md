---
capability: repo-tools-symindex-vectors-refresh
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.vector_refresh.refresh_dir@d7b011dc87
  - cosa.repo.symindex.vector_refresh.missing_purpose_lines@473bc17736
  - cosa.repo.symindex.vector_refresh.check_fresh@7540f6914a
  - cosa.repo.symindex.vector_refresh.run_refresh@8cf82a8ace
  - cosa.repo.symindex.vector_refresh.cron_lines@cdbae8de66
  - cosa.repo.symindex.vector_refresh.main@867ccf35a6
  - cosa.repo.symindex.candidate_build.run@ac9f7cf8d1
  - cosa.repo.symindex.candidate_build.BoundedJobWriter@afaf8d075a
  - cosa.repo.symindex.candidate_build.make_job_writer@b76de67fc7
  - cosa.repo.symindex.candidate_build.sample_purposes@19eeb92914
  - cosa.repo.symindex.candidate_build.main@169206a5fc
---
# Vector set refresh and build

Keeps the stored vector set current. The staleness check is on [[repo-tools-symindex-vectors-status]].

## Daily job (`vector_refresh`)
- `python -m cosa.repo.symindex.vector_refresh [--force] [--root R]` runs once per local day from 10:00. Its switch is the key `reuse vector refresh enabled`; off exits 3.
- `check_fresh` says the set needs no work only when four things hold. The set has build info and its recorded index manifest equals the index's. Its own manifest is readable and its engines match the server. Every sendable pin has a stored purpose line or is listed as unwritten.
- `missing_purpose_lines` counts the distinct sendable pins with no stored line that the last build did not list as unwritten.
- `run_refresh` otherwise calls `candidate_build.run`, twice at most, retrying only a `TimeoutError`. `last_run_date` is recorded only for a fresh set or a finished build.
- Exits: 0 done, fresh or not due, 1 failed, 2 a named candidate error, 3 off, 4 another build holds the lock. State is `refresh-state.json` under `refresh_dir`.
- `cron_lines` give a daily `47 10 * * *` line and an `@reboot sleep 240` line tagged `# reuse-vector-refresh`. `--install` and `--uninstall` use the librarian's locked crontab editor. `--status` only reads the crontab, and `--print-install` only prints the lines.

## Build (`candidate_build`)
- `run( root, writer, client )` ensures the index and writes missing purpose lines. It rebuilds the vectors under the build lock and swaps the new set in by rename. Vectors of rows whose text is unchanged are reused. A held lock raises `CandidateError` with code `BUILD_LOCK_HELD`, and no purpose line or vector is written.
- `BoundedJobWriter` asks a bounded Claude Code job for purposes: it writes `request-<key>.json` and submits it. It waits 1800 seconds by default for the response file. `make_job_writer` submits through `/api/v2/submit`. No file in time raises `TimeoutError`, and a malformed one raises `ValueError`.
- `make_job_writer( root, base_url, environ )` needs the main checkout (a worktree raises `ValueError`) and the two `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` credentials, else `DEPENDENCY_MISSING`.
- `sample_purposes` writes lines for every k-th public symbol, sorted by id, into a separate store. `candidate_build.main` takes `--root`, `--batch-size`, and `--sample` with `--store`.
