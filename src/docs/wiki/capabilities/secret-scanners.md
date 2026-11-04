---
capability: secret-scanners
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.pre-commit-secret-scan.added_lines_by_file@72605cab11
  - scripts.pre-commit-secret-scan.main@6998b63ba6
  - scripts.secret_scan.scan_text@a15dc1b9ae
  - scripts.secret_scan.scan_ref@cf3911d57e
---
# Secret scanners

Two scanners for committed credential values. One is the commit gate and the other is the inventory sweep. Both report masked output only. It shows the key, the length and a truncated sha256, never the value, since a report that quotes the secret spreads it further.

## Commit gate
- The pre-commit gate refuses a commit that adds a credential value. It scans only the lines the staged change adds. Known credential-shaped lines already sit in the repo, and a gate that fired on them would be switched off.
- `added_lines_by_file` maps each staged file to the line numbers the change adds. A deleted or renamed-away path never appears.
- `main` scans the staged content of each text file and keeps only findings on added lines. It returns 0 when there are none and 1 with a masked report otherwise.
- The diff is read with `--no-relative`, so a `diff.relative` setting cannot make a manual run pass on a clean-looking scan. Install the hook by hand, never automatically. `git commit --no-verify` bypasses it, and the reason belongs in the commit message.

## Inventory sweep
- `scan_text` yields masked findings for one blob of text. It reports values only, not paths, field names or placeholders.
- `scan_ref` scans every text path in a ref, the published surface rather than the checkout. A redacted working copy cannot hide what the ref still carries.
- The scanner runs in worktree, ref or history mode. Worktree mode exits 2 when no repo root is found, never reporting clean.
- A clean result looks the same as a blind scanner, so its fixture suite plants known positives and fails if any stops being found.
- Blind spots include a bare token in prose, binary files and values that only lived in ignored files.
