---
capability: rest-core-persona-key-backfill
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.persona_key_backfill.scan_stragglers@37ee3fc2e4
  - cosa.rest.persona_key_backfill.backfill_persona_keys@fba490fa2d
---
# Persona key backfill

A sweep over task-store rows whose persona columns were written before every write went through `canonical_persona_key`. Such a row, a `María` or `Mr. Radio` for example, never matches a canonical read, so it drops out of that persona's owed list. The store is on [[task-store]].

## Functions
- `scan_stragglers( items )` is pure. It returns one plan `{id, column, old, new}` for each row and column whose value differs from its canonical key, plus a `skip` flag. `None`, empty and already canonical values give no plan.
- A value that canonicalizes to `""` is reported with `new=""` and a skip flag, so nothing blanks the column.
- `backfill_persona_keys( session, apply=False )` scans the store and returns `{scanned, stragglers, applied}`.
- With `apply=False` nothing is written and `applied` is 0. With `apply=True` each non-skip plan is written to its row and `applied` counts them.
- The caller owns the commit or rollback. It sweeps `owner_persona` and `accountable_manager`. `python -m cosa.rest.persona_key_backfill` is a dry run, and `--apply` writes.

## Don't
- Don't apply a skipped plan. An all-punctuation value needs a person to look.
- Don't run `apply=True` without reading the dry-run list first.
