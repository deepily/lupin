#!/usr/bin/env python3
"""
Guarded persona-key backfill probe (Phase 2 straggler sweep).

Phase 2 routes every WRITE seam through `canonical_persona_key`, so newly-stored
`owner_persona` / `accountable_manager` values are ALWAYS canonical. This module
handles the historical tail: any row written BEFORE the cutover whose persona
value is non-canonical (uppercase / accent / punctuation / double-space) — e.g.
a "María" or "Mr. Radio" stored by the bare-`.lower()` write seam — would never
match a canonical READ query and would silently drop out of that persona's
owed-row set.

The probe scans the two persona-typed columns, finds every value that is NOT
already equal to its `canonical_persona_key`, and (with `--apply`) UPDATEs each
straggler in place. It is:

    - IDEMPOTENT — a value already equal to its canonical key is skipped; a
      second run after `--apply` is a clean no-op.
    - DRY-RUN BY DEFAULT — without `--apply` it only REPORTS the planned
      updates (no write), so it is safe to run for inspection at any time.
    - DEGRADE-SAFE on a single bad value — a value that canonicalizes to "" (an
      all-punctuation persona, which should not exist) is REPORTED and SKIPPED
      rather than blanking the column.

Per the 2026-06-18 store probe (`"maria"`→22 rows, `"maría"`→0; `"mr radio"`→54,
`"mr. radio"`→0) the store was ALREADY canonical on the live path, so the
expected straggler set is near-empty — this is belt-and-suspenders for any row
the earlier bare-`.lower()` write seam may have left behind.

Run:
    python -m cosa.rest.persona_key_backfill            # DRY-RUN preview
    python -m cosa.rest.persona_key_backfill --apply    # perform the updates

Design authority: lupin ->
    src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md
    (Phase 2 — "Backfill probe (guarded)").
"""
import sys

from lupin_mcp.persona_normalization import canonical_persona_key


# The persona-typed columns the store invariant covers (design §Design — one
# root). `created_by` is "persona + session id" free text (NOT a bare persona
# key) and `blocked_by` persona refs are canonicalized at the transition seam,
# so neither is swept here.
PERSONA_COLUMNS = ( "owner_persona", "accountable_manager" )


def scan_stragglers( items ):
    """
    Find rows whose persona-typed columns are not already canonical.

    Requires:
        - items is an iterable of objects exposing `.id` and each name in
          PERSONA_COLUMNS as an attribute (a str or None)

    Ensures:
        - returns a list of plans, one per (item, column) that needs a change:
          { "id": item.id, "column": <name>, "old": <current>, "new": <canon> }
        - a column that is None / "" / already-canonical produces NO plan entry
        - a column that canonicalizes to "" (all-punctuation — should not occur)
          is reported with new="" and a "skip" flag so the caller does NOT blank
          the column; it is surfaced, never silently applied
        - pure (no DB access) — the IO boundary lives in the caller
    """
    plans = [ ]
    for item in items:
        for column in PERSONA_COLUMNS:
            current = getattr( item, column )
            if not current:
                continue
            canon = canonical_persona_key( current )
            if canon == current:
                continue                                   # already canonical → no-op
            plans.append( {
                "id"     : item.id,
                "column" : column,
                "old"    : current,
                "new"    : canon,
                "skip"   : ( canon == "" ),                # un-canonicalizable → report, don't blank
            } )
    return plans


def backfill_persona_keys( session, apply=False ):
    """
    Scan + (optionally) UPDATE non-canonical persona keys in the task store.

    Requires:
        - session is an open SQLAlchemy Session (caller owns commit/rollback)
        - apply is a bool — False (default) reports only; True performs UPDATEs

    Ensures:
        - returns { "scanned": <int>, "stragglers": [ <plan>, ... ],
          "applied": <int> } where each plan is a scan_stragglers entry
        - apply=False: `applied` is 0 and NO row is mutated (dry-run)
        - apply=True: every non-skip plan is written via setattr on its row;
          `applied` counts the writes performed; the caller commits
        - a plan with skip=True is NEVER applied (an all-punctuation value is
          surfaced for human attention, never used to blank a column)
    """
    from cosa.rest.postgres_models import TaskItem

    items   = session.query( TaskItem ).all()
    plans   = scan_stragglers( items )
    applied = 0

    if apply and plans:
        by_id = { item.id: item for item in items }
        for plan in plans:
            if plan[ "skip" ]:
                continue
            setattr( by_id[ plan[ "id" ] ], plan[ "column" ], plan[ "new" ] )
            applied += 1

    return { "scanned": len( items ), "stragglers": plans, "applied": applied }


def _run( apply ):   # pragma: no cover - CLI/DB IO boundary
    """Open a DB session, run the backfill, print a report. Returns exit code."""
    from cosa.rest.db.database import get_db

    with get_db() as session:
        report = backfill_persona_keys( session, apply=apply )

    mode = "APPLY" if apply else "DRY-RUN"
    print( f"persona_key_backfill [{mode}] — scanned {report['scanned']} rows, "
           f"{len( report['stragglers'] )} straggler(s), {report['applied']} applied" )
    for plan in report[ "stragglers" ]:
        tag = " (SKIP — un-canonicalizable)" if plan[ "skip" ] else ""
        print( f"  {plan['column']} {plan['id']}: {plan['old']!r} -> {plan['new']!r}{tag}" )
    return 0


if __name__ == "__main__":   # pragma: no cover - CLI entry
    sys.exit( _run( apply=( "--apply" in sys.argv[ 1: ] ) ) )
