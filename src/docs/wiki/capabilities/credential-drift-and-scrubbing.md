---
capability: credential-drift-and-scrubbing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.credential_file_scrubber.count_value_occurrences@83f950bac1
  - cosa.utils.credential_file_scrubber.format_report@34636f2dfc
  - cosa.utils.credential_file_scrubber.is_recently_modified@1581f85da5
  - cosa.utils.credential_file_scrubber.main@3811913606
  - cosa.utils.credential_file_scrubber.scan_for_values@1b4d566b5a
  - cosa.utils.credential_file_scrubber.scrub_file@a2bf50e0cd
  - cosa.utils.credential_file_scrubber.scrub_roots@18845a9900
  - cosa.utils.credential_watch.container_is_busy@4209a05774
  - cosa.utils.credential_watch.should_restart_containers@ee9b44da22
  - cosa.utils.secret_drift.sha256_of@8f5c74bfb5
  - cosa.utils.secret_drift.fingerprint_key_file@335f84b427
  - cosa.utils.secret_drift.fingerprint_secret_manager@5b2c1c02fe
  - cosa.utils.secret_drift.check_key_drift@2fa2a18e61
  - cosa.utils.secret_drift.format_report@1849f91777
---
# Credential drift and scrubbing

Three small checks around credentials: an API key file against its Secret Manager copy, credential values left in files, and the OAuth token watcher.

## What it does
- `secret_drift.check_key_drift( key_path, secret_id, project_id, version="latest", runner=subprocess.run )` returns a dict. It holds `status` (`match`, `drift` or `unknown`), both sha256 digests and a `detail` sentence.
- `fingerprint_key_file` returns the sha256 of the stripped file, or `None` when unreadable. `fingerprint_secret_manager` runs `gcloud secrets versions access` with a 90 second timeout and returns `None` on any failure. `sha256_of` hashes UTF-8 text. `format_report` renders one line marked `OK`, `FAIL` or `WARN`.
- `credential_file_scrubber.scan_for_values( roots, values )` runs `grep -rlFa -f -` with the values on stdin. It returns `{ "paths", "unreadable" }` and raises `ValueError` for an empty value list.
- `count_value_occurrences( path, values )` counts verbatim hits in one file. `is_recently_modified( path, window_seconds=300, now=None )` is true for a file written inside the window. `scrub_file( path, values )` rewrites one file through a temp file, fsync and rename, keeps the mode, and returns `{ path, before, after, changed }`.
- `scrub_roots( roots, values=None, window_seconds=300, exclude=(), dry_run=False )` finds and scrubs. A recently written or excluded file is skipped and listed. A file that vanishes between the scan and its rewrite is listed under `unreadable` and the run carries on. With no values it reads `credential_env_values()`. `format_report( result )` prints counts and paths only. `main( argv )` returns 0 when no occurrence survives and 1 otherwise.
- `credential_watch.should_restart_containers( previous_inode, current_inode, expires_at_ms, now_ms, min_remaining_s=120.0 )` returns `( act, reason )`. It acts only when the inode changed and the new token has more than the minimum left.
- `container_is_busy( ps_output, markers )` returns `( busy, reason )`. Empty output counts as busy. The markers are `pytest`, `playwright`, `run-integration-tests` and `run-e2e-ui-tests`.

## Don't
- Don't treat `unknown` from `check_key_drift` as a pass. The comparison did not happen.
- Don't read a scrubber zero as complete. A file written in the last 5 minutes is skipped, and files grep could not open come back as `unreadable`.

## Invariants
- No function here returns or prints a credential value. Reports hold digests, counts, paths and key names.
- Redaction rules come from `cosa.utils.secret_redaction`. `should_restart_containers` returns `False` on the first observation.
- `credential_watch` is pure logic. Its docstring names `src/scripts/credential-refresh-watcher.py`, which is not tracked; only the `.service` file is.
