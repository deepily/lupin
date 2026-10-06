#!/usr/bin/env python3
"""
Guarded persona-key backfill probe (the straggler sweep).

Every write seam routes through `canonical_persona_key`, so newly-stored
`owner_persona` / `accountable_manager` values are always canonical. This module
handles the historical tail. That means a row written before the cutover whose persona
value is non-canonical (uppercase, accent, punctuation, double-space), such as a "María"
or "Mr. Radio" from the bare-`.lower()` write seam. Such a row never matches a
canonical read query. It silently drops out of that persona's owed-row set.

The probe scans the two persona-typed columns, finds every value not already equal
to its `canonical_persona_key`, and (with `--apply`) updates each straggler in place:

    - Idempotent: a value already equal to its canonical key is skipped, so a
      second run after `--apply` is a clean no-op.
    - Dry-run by default: without `--apply` it only reports the planned updates
      (no write), so it is safe to run for inspection at any time.
    - Degrade-safe on a single bad value: a value that canonicalizes to "" (an
      all-punctuation persona, which should not exist) is reported and skipped
      rather than blanking the column.

A store probe (`"maria"`→22 rows, `"maría"`→0; `"mr radio"`→54, `"mr. radio"`→0)
showed the live path already canonical, so the expected straggler set is near-empty.
The probe is a safety net for rows the earlier bare-`.lower()` write seam may have left.

Run:
    python -m cosa.rest.persona_key_backfill            # DRY-RUN preview
    python -m cosa.rest.persona_key_backfill --apply    # perform the updates

Design: src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md
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
        - a column that is None / "" / already-canonical produces no plan entry
        - a column that canonicalizes to "" (all-punctuation — should not occur)
          is reported with new="" and a "skip" flag so the caller does not blank
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
    Scan for non-canonical persona keys in the task store and optionally rewrite them.

    Requires:
        - session is an open SQLAlchemy Session (caller owns commit/rollback)
        - apply is a bool — False (default) reports only; True performs UPDATEs

    Ensures:
        - returns { "scanned": <int>, "stragglers": [ <plan>, ... ],
          "applied": <int> } where each plan is a scan_stragglers entry
        - apply=False: `applied` is 0 and no row is mutated (dry-run)
        - apply=True: every non-skip plan is written via setattr on its row;
          `applied` counts the writes performed; the caller commits
        - a plan with skip=True is never applied (an all-punctuation value is
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
