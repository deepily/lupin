---
capability: rest-services-approval-settings-readers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_approval_settings.current_settings@563b4b9579
  - cosa.rest.task_approval_settings.get_approvers@049a6e8664
  - cosa.rest.task_approval_settings.get_approver_accounts@4ad2c43bd3
  - cosa.rest.task_approval_settings.approver_persona_for_account@1f3cbef07e
  - cosa.rest.task_approval_settings.is_approver@a0dd84f55f
  - cosa.rest.task_approval_settings.get_enforcement_active@42855cfdbc
  - cosa.rest.task_approval_settings.default_mint_status@6609720a60
  - cosa.rest.task_approval_settings.get_admission_window_seconds@3c10e20ab5
  - cosa.rest.task_approval_settings.get_sword_of_damocles_active@e253975ed5
  - cosa.rest.task_approval_settings.import_legacy_override_file@728a59ccaf
  - cosa.rest.task_approval_settings.legacy_override_path@d1e21310b7
  - cosa.rest.task_actor_identity.identity_for_account@2c5c300e47
  - cosa.rest.task_actor_identity.recorded_actor@10c0ac3606
---
# Approval settings readers and actor identity

How the task store decides who is an approver and which switches are on. The gate that uses them is [[task-promotion-gate]]; the store is [[task-store]].

## What it does
- Most settings have two layers: a stored override in the `approval_settings` table, then the INI key. The admission window reads the INI key only. `current_settings()` returns `{ key: { value, source } }` where `source` is `override` or `config`, read through the live readers.
- `get_approvers()` returns canonical persona keys and always includes `UNCONDITIONAL_APPROVERS`, so a bad list cannot lock the fleet out. A non-list override is ignored.
- `get_approver_accounts()` maps lowercased login email to a persona from the override or the INI `email = persona` pairs. A malformed pair is skipped.
- `approver_persona_for_account( email )` returns that persona only while it is still an approver, else `None`.
- `is_approver( actor )` matches the canonical persona key of a declared actor string, so a session suffix does not matter. A blank actor is never one.
- `get_enforcement_active()` says whether the gate refuses or only advises. `default_mint_status()` returns `not_approved` when the holding-area default is on, else `queued`. `get_sword_of_damocles_active()` says whether an admit must name a deletion ticket.
- `get_admission_window_seconds()` is the wait between a non-exempt approver's admissions; 0 is off.
- `import_legacy_override_file()` copies the retired JSON file once per database and returns a status. A file whose stamp does not verify imports nothing. `legacy_override_path()` only locates it.
- `identity_for_account( email )` returns the approver persona, else the email, else `None`. `recorded_actor( declared, email )` returns `"<identity> (<declared>)"`, or the declared actor unchanged for an API-key caller.

## Don't
- Don't coerce a stored string with `bool()`. `"false"` would read as on; readers parse strings, and an unparseable value falls through to the next layer.
- Don't read a setting once at import. The default mint status and the flags are read on each call, though the stored layer may be up to 2 seconds stale.

## Invariants
- With an account, `recorded_actor` returns `<identity> (<declared>)`. Over 255 characters, the declared half becomes an elision marker. If identity plus marker still exceeds 255, it returns the declared actor unchanged.
