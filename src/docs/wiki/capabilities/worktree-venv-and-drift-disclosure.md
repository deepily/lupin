---
capability: worktree-venv-and-drift-disclosure
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.worktree_venv.provision_worktree_venv@ff626c8b91
  - cosa.utils.seat_worktree.drift_disclosure@315fb664e8
  - cosa.utils.worktree_artifacts.parse_artifact_outcomes@748f78aa63
---
# Worktree venv and drift disclosure

Three small helpers beside the tree provisioning in [[worktree-lifecycle]]. Each one delegates to a shell script and never raises.

## What it does
- `provision_worktree_venv( target )` runs `src/scripts/link-worktree-venv.sh` from the target tree and returns `provisioned`, `status`, `exit_code`, `target` and `detail`.
- Status is `ok` on exit 0, `main_repo` on exit 3, `no_target` for a falsy path, `script_absent` for a tree without the script, and `failed` otherwise.
- `main_repo` is a provisioning no-op, but it logs a warning that the seat stands in the shared checkout.
- `drift_disclosure( provisioning )` turns a `provision_seat_worktree` result into one sentence naming the tree and how many commits it is behind.
- It returns None for no result, an unknown drift or a level tree, so a line that appears always means something.
- `parse_artifact_outcomes( stdout )` maps each relative path to `LINKED`, `ALREADY`, `SOURCE_ABSENT` or `REFUSED` from `KEY=path` lines. It ignores prose and unknown keys.

## Don't
- Don't read `drift_disclosure` as a gate. It discloses a number and forbids nothing.
- Don't read `provisioned` False as an error for `main_repo`. It is a correct no-op.

## Invariants
- A later line for the same path overwrites an earlier one in `parse_artifact_outcomes`.
- A timeout or an unrunnable script is `failed` with a null exit code.
