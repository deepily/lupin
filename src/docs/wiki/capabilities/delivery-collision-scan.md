---
capability: delivery-collision-scan
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.delivery-collision-scan.discover_branches@a5a7e084b0
  - scripts.delivery-collision-scan.commit_file_map@075108e93d
  - scripts.delivery-collision-scan.code_files_of@11d15a5612
  - scripts.delivery-collision-scan.is_absent_from@6c80157c07
  - scripts.delivery-collision-scan.scan@08bb559dde
  - scripts.delivery-collision-scan.main@c6ccf8e97c
---
# Delivery collision scan

Finds files edited by two or more branches whose edits are not yet delivered to the target branch. A commit on a worktree branch moves nobody's tree but its author's, so several engineers once wrote the same fix. The repo root comes from the script's own location, never from `LUPIN_ROOT`.

## Finding candidates
- `discover_branches` discovers candidate branches from git, never from a hand list. It returns the branches inside the tip-age window and those excluded, because a collision on an excluded branch is invisible, not absent.
- `commit_file_map` lists every non-merge commit on a branch not in the target, with its code files, in one git call per branch. Ancestry over-reports about three times because delivery is by squash, so this is a pre-filter and never a verdict.
- `code_files_of` returns the sorted repo-relative paths a commit touched that end in a code suffix.

## Confirming
- `is_absent_from` is the verdict. It returns true when a long line the commit added to a path is missing from the target's copy. It returns false when the line is present.
- It returns false when no probe line can be found, because an unprobeable commit is not evidence of absence. Results are cached per commit and path.

## Scanning
- `scan` returns the collisions, as paths mapped to at least two distinct branches, plus the denominators it covered.
- It raises `LookupError` when discovery finds zero branches or zero commits, since an empty scan passes every per-item check. It raises `TimeoutError` at the deadline, because a partial scan is not a clean one.
- `main` prints its denominators on every run. Exit 0 means no collision, 1 means a collision, and 2 means refused with nothing scanned.
