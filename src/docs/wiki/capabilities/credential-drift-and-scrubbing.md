---
capability: credential-drift-and-scrubbing
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.utils.credential_file_scrubber.count_value_occurrences@83f950bac1
  - cosa.utils.credential_file_scrubber.format_report@34636f2dfc
  - cosa.utils.credential_file_scrubber.is_recently_modified@1581f85da5
  - cosa.utils.credential_file_scrubber.main@3811913606
  - cosa.utils.credential_file_scrubber.scan_for_values@1b4d566b5a
  - cosa.utils.credential_file_scrubber.scrub_file@a2bf50e0cd
  - cosa.utils.credential_file_scrubber.scrub_roots@18845a9900
  - cosa.utils.secret_drift.sha256_of@8f5c74bfb5
  - cosa.utils.secret_drift.fingerprint_key_file@335f84b427
  - cosa.utils.secret_drift.fingerprint_secret_manager@5b2c1c02fe
  - cosa.utils.secret_drift.check_key_drift@2fa2a18e61
  - cosa.utils.secret_drift.format_report@1849f91777
---
# Credential drift and scrubbing

Two small checks around credentials: an API key file against its Secret Manager copy, and credential values left in files.

## What it does
- `secret_drift.check_key_drift( key_path, secret_id, project_id, version="latest", runner=subprocess.run )` returns a dict. It holds `status` (`match`, `drift` or `unknown`), both sha256 digests and a `detail` sentence.
- `fingerprint_key_file` returns the sha256 of the stripped file, or `None` when unreadable. `fingerprint_secret_manager` runs `gcloud secrets versions access` with a 90 second timeout and returns `None` on any failure. `sha256_of` hashes UTF-8 text. `format_report` renders one line marked `OK`, `FAIL` or `WARN`.
- `credential_file_scrubber.scan_for_values( roots, values )` runs `grep -rlFa -f -` with the values on stdin. It returns `{ "paths", "unreadable" }` and raises `ValueError` for an empty value list.
- `count_value_occurrences( path, values )` counts verbatim hits in one file. `is_recently_modified( path, window_seconds=300, now=None )` is true for a file written inside the window. `scrub_file( path, values )` rewrites one file through a temp file, fsync and rename, keeps the mode, and returns `{ path, before, after, changed }`.
- `scrub_roots( roots, values=None, window_seconds=300, exclude=(), dry_run=False )` finds and scrubs. A recently written or excluded file is skipped and listed. A file that vanishes between the scan and its rewrite is listed under `unreadable` and the run carries on. With no values it reads `credential_env_values()`. `format_report( result )` prints counts and paths only. `main( argv )` returns 0 when no occurrence survives and 1 otherwise.

## Don't
- Don't treat `unknown` from `check_key_drift` as a pass. The comparison did not happen.
- Don't read a scrubber zero as complete. A file written in the last 5 minutes is skipped, and files grep could not open come back as `unreadable`.

## Invariants
- No function here returns or prints a credential value. Reports hold digests, counts, paths and key names.
- Redaction rules come from `cosa.utils.secret_redaction`.
- The OAuth token watcher (`credential_watch` and its systemd unit) was retired on 17 Aug 2026, once each container held its own grant.
