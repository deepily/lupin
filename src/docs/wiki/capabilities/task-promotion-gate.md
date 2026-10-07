---
capability: task-promotion-gate
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.task_promotion_gate.approval_for_promotion@1eb657c43b
  - cosa.rest.task_promotion_gate.manager_refusal@02900f1468
  - cosa.rest.task_promotion_resolver.resolve_ticket@e0b4242d26
  - cosa.rest.task_promotion_resolver.reconcile_on_startup@c07e54e209
  - cosa.rest.task_request_lifecycle.outcome_of_silence@a56720b131
  - cosa.rest.task_request_pledge.refusal_for_pledge@2ce217bd57
  - cosa.rest.task_priority_firewall.refusal_for_priority_change@1f0df9b9e2
  - cosa.rest.task_priority_firewall.refusal_for_priority_create@34849a5153
  - cosa.rest.task_approval_settings.get_manager_pull_disabled@5304aa9f44
---
# Task promotion gate

The rules for moving a row out of the holding area (`not_approved`) onto somebody's board, and for who may set a priority. A row nobody approved must not become owed work. [[task-store]] holds the rows; the settings live in the `approval_settings` table behind [[db-repositories]].

## What it does
- `approval_for_promotion` decides a promotion in three steps. `manager_refusal` checks the caller's credentials first. `promotion_precheck` then allows the operator's own promotion without an ask. Only then does `approval_from_the_ask` put the question to the owner.
- A worker is refused and the owner is never asked. A manager's promotion causes the ask. The operator's own promotion skips it. Persona `rick` in `ASK_EXEMPT_PERSONAS` is allowed at once, stamped `self`. The async door mints no ticket for it. Only a yes allows; a no, an answer it cannot read and a timed-out default all refuse.
- The async path returns a ticket at once. `resolve_ticket` then asks, re-validates under a fresh row lock and applies the move. If the transition is no longer legal, the ticket resolves `superseded`.
- A manager's promote or demote request (`task_request_lifecycle`) stays pending until the operator answers. A denial closes it and the manager must file again. An admit request must also name one of the manager's own tickets to delete (`task_request_pledge`, switch `sword_of_damocles_active`).
- `task_priority_firewall` keeps three separate checks: P0 only for the operator, raising into P1 to P4 only for the operator or a manager, and creating above P5 only for the operator or a manager.

## Invariants
- Credentials come before the owner is asked. A validated account persona passes `manager_refusal` first, because a browser has no session bridge. An unreadable bridge is refused, not waved through.
- Silence never grants and never denies. `outcome_of_silence` takes no clock and returns the state it was given, so a request cannot age out.
- Nothing in the application calls `reconcile_on_startup` or `sweep_stalled_tickets`; only tests do. If `reconcile_on_startup` ran, it would mark every `pending` ticket `stalled` and raise an urgent alarm. An answer given just before a restart would not be recovered.
- P0 is the one strong rule: it keys on a validated account token. The P1 to P5 rules key on the session bridge role, which a session writes for itself, so they stop mistakes and not forgery.
- A lowering or a repeat of the current priority is always allowed. A worker that asks to create above P5 is refused, not downgraded.
- When the settings database cannot be read, the readers fall back to the INI. The shipped INI sets `task approval enforcement active = True`, so enforcement stays on. Only when both the stored value and the INI key are absent does it default to off, so the gate advises. `get_manager_pull_disabled` falls back to `True`, so manager pulling stays frozen.
- The actor a caller declares buys no approver authority. `refusal_for_admission` only names it in a refusal; authority comes from the account email on the validated token. For an account caller, `recorded_actor` writes `<identity> (<declared>)`. The identity is the mapped approver persona or the email, so a false claim can be traced. An API-key caller has no account, and its declared actor is recorded unchanged.

## How to extend
- Add a rule as a pure function in its own module and have the router call it, so a test can watch it refuse without a database.
- Keep the three priority rules as three checks. They key on different evidence.
- Change a live setting through `set_overrides` in `task_approval_settings`; a hand-edited file is read once at boot and then ignored.
