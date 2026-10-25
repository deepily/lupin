---
capability: repo-tools-symindex-vectors-refresh
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.vector_refresh.refresh_dir@d7b011dc87
  - cosa.repo.symindex.vector_refresh.missing_purpose_lines@473bc17736
  - cosa.repo.symindex.vector_refresh.check_fresh@7540f6914a
  - cosa.repo.symindex.vector_refresh.run_refresh@f87af81c7a
  - cosa.repo.symindex.vector_refresh.cron_lines@09adf82286
  - cosa.repo.symindex.vector_refresh.main@126f014e2e
  - cosa.repo.symindex.vector_refresh.env_file_path@6220714314
  - cosa.repo.symindex.vector_refresh.carried_env@97e4d23411
  - cosa.repo.symindex.candidate_build.run@8c0684e323
  - cosa.repo.symindex.candidate_build.BoundedJobWriter@afaf8d075a
  - cosa.repo.symindex.candidate_build.make_job_writer@6f0901398b
  - cosa.repo.symindex.candidate_build.sample_purposes@4c0e76d6e8
  - cosa.repo.symindex.candidate_build.tree_path_refusal@9a2e9a9fb4
  - cosa.repo.symindex.candidate_build.main@db8f8b3077
---
# Vector set refresh and build

Keeps the stored vector set current. The staleness check is on [[repo-tools-symindex-vectors-status]].

## Daily job (`vector_refresh`)
- `python -m cosa.repo.symindex.vector_refresh [--force] [--root R]` runs once per local day from 10:00. Its switch is the key `reuse vector refresh enabled`; off exits 3.
- `check_fresh` says the set needs no work only when four things hold. The set has build info and its recorded index manifest equals the index's. Its own manifest is readable and its engines match the server. Every sendable pin has a stored purpose line or is listed as unwritten. `missing_purpose_lines` counts the distinct sendable pins with no stored line that the last build did not list as unwritten.
- `run_refresh` reads the searchable entries of the index. Otherwise it calls `candidate_build.run`, twice at most, retrying only a `TimeoutError`. `last_run_date` is recorded only for a fresh set or a finished build.
- Exits: 0 done, fresh or not due, 1 failed, 2 a named candidate error, 3 off, 4 another build holds the lock. State is `refresh-state.json` under `refresh_dir`.
- `cron_lines` give a daily `47 10 * * *` line and an `@reboot sleep 240` line tagged `# reuse-vector-refresh`, built with the librarian's `cron_lines_for`. Each line runs the wrapper script with `REUSE_VECTOR_REFRESH_ENV` set to the credential file, which the wrapper sources. Both lines also carry `DEEPILY_DATA_DIR` and `PLANNING_IS_PROMPTING_ROOT` when the installing shell has them (`carried_env`), because cron reads no `~/.bashrc`. The wrapper script runs the job with the first Python that imports it. It tries `REUSE_VECTOR_REFRESH_PYTHON`, the checkout's `.venv`, `~/.venv-lupin-mcp`, then `python3`. When none imports it, the script exits 1 and names what it tried. `lupin-vm.sh install-refresh-cron [local|vm]` installs with all of that set from known paths. `lupin-vm.sh deploy` refreshes the VM's planning-is-prompting copy.
- `env_file_path` names that file: `.lupin/reuse-vector-refresh.env` under the home folder. The `push-test-mock-login` verb of `lupin-vm.sh` writes the same path. `--install` and `--uninstall` use the librarian's locked crontab editor. `--status` only reads the crontab, and `--print-install` only prints the lines.

## Build (`candidate_build`)
- `run( root, writer, client )` ensures the index and writes purpose lines from every searchable entry, public and private. It rebuilds the vectors under the build lock and swaps the new set in by rename. Vectors of rows whose text is unchanged are reused.
- The vector rows are only the entries that pass the screen's `sendable` check, which is the list the lookup uploads as its stage. A held lock raises `CandidateError` with code `BUILD_LOCK_HELD`, and nothing is written.
- `BoundedJobWriter` asks a bounded Claude Code job for purposes: it writes `request-<key>.json` and submits it. It waits 1800 seconds by default for the response file. `make_job_writer` submits through `/api/v2/submit`. No file in time raises `TimeoutError`, and a malformed one raises `ValueError`.
- `make_job_writer( root, base_url, environ )` needs the main checkout (a worktree raises `ValueError`) and the two `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` credentials, else `DEPENDENCY_MISSING`. With `index` and `out_dir` it reads that index file, hands off under `out_dir/handoff`, and a worktree root is allowed.
- `sample_purposes` writes lines for every k-th searchable symbol, sorted by id, into a separate store. It reads the given `index` folder when one is passed.
- `run` also takes `purposes`, `index`, `out_dir` and `skip_if_current`. With `purposes="skip"` it never calls the writer, builds from the stored lines and lists a pin without one as unwritten. Any other value than `write` or `skip` raises `ValueError`. `index` is read only, and `out_dir` holds the purpose, vector, query-cache and lock files. `skip_if_current` rereads the build info under the lock and returns `{ skipped: "current" }` when it names this index.
- `candidate_build.main` takes `--root`, `--batch-size`, `--sample` with `--store`, and `--index` with `--out-dir`, which come together or not at all.
- `tree_path_refusal( index, out_dir, main_tree )` returns a sentence, or `None` when the output folder is fine. It refuses a folder that overlaps the index folder, lies outside the main checkout, or is not ignored by git inside it.
