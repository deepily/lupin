---
capability: rest-services-approval-gate-decisions
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_approval_settings.requested_move@eedd37097c
  - cosa.rest.task_approval_settings.move_for_ticket@c53631b8bb
  - cosa.rest.task_approval_settings.refusal_for_admission@7d4adf391a
  - cosa.rest.task_approval_settings.refusal_for_batch@1ba5001ce2
  - cosa.rest.task_approval_settings.refusal_for_live_mint@f5c89c5440
  - cosa.rest.task_approval_settings.refusal_for_pull@f8d415fd4e
  - cosa.rest.task_approval_settings.actor_is_claiming_their_own_row@59ec5a1ccd
  - cosa.rest.task_approval_settings.set_overrides@274c7c9386
  - cosa.rest.task_approval_settings.set_manager_pull_disabled@0e9efd8f32
---
# Approval gate decisions and settings writes

The pure functions behind the holding-area gate, and the one validated way to change its settings. Reader side: [[rest-services-approval-settings-readers]]. Gate flow: [[task-promotion-gate]].

## What it does
- `requested_move( from_status, to_status )` names the approver-only move a transition is (admit, won't-fix, demote or un-park), or `None`. `move_for_ticket( to_status )` is shorter: a ticket is only minted for admit or demote, so the holding status means demote and anything else means admit.
- `refusal_for_admission` returns a refusal detail or `None`. It is `None` when enforcement is off, when the move is not approver-only, or when the authenticated account maps to a current approver. A manager may close a held row, from `not_approved` to `done`. A manager may also move a parked row to `queued` with an operator-approved card.
- A declared actor string never grants approver rights there. It is only named in the refusal.
- `refusal_for_batch( actor, account_persona, recent_admissions )` refuses a second admission inside the window unless the caller is ask-exempt; the first always passes.
- `refusal_for_live_mint` refuses a create that names a live status while the holding default is on. It passes when `status` was not named or the holding default is off. It also passes for the holding status itself, for priority P0 and for the operator.
- `refusal_for_pull` guards the edge into `in_progress` while the pull switch is on. Other transitions, an `in_progress` re-patch and a switched-off toggle return `None`, and an approver by validated account passes.
- `actor_is_claiming_their_own_row( actor, owner, manager )` is true only when the actor is the owner and the manager is someone else.
- `set_overrides( updated_by, **settings )` validates every key before writing any, preserves other keys and returns the live values read back. `set_manager_pull_disabled( disabled, updated_by )` takes a real bool.

## Don't
- Don't pass a string to `set_manager_pull_disabled`; it raises `ValueError`.
- Don't use `move_for_ticket` to classify an arbitrary transition.

## Invariants
- Every refusal function names a way forward and never raises.
