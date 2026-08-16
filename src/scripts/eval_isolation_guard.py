"""Snapshot-store isolation guard for the CJ Flow v2 paired eval.

WHY THIS EXISTS. The v2 flow writes snapshots back when `v2 snapshot writeback enabled`
is True (lupin-app.ini). A paired v1-vs-v2 run must NOT let those writes hit a LIVE store
(the standing no-test-touches-a-live-dev-data-store rule) and must not let one arm's writes
warm the other arm's cold pass (design §4). This guard enforces that with TWO SEPARATE,
independent checks — a store is safe to use only when BOTH pass:

  SAFETY (require_isolated_snapshot_table) — is the destination NON-LIVE?
    FAIL-CLOSED by allowlist membership. The app's live write destination is the
    FULLY-QUALIFIED (database, table): the database from the app's own get_database_url()
    and the table from SolutionSnapshot.__tablename__ (what the ORM actually writes
    through). It is permitted ONLY when that `database.table` is a member of the config
    allowlist `v2 eval permitted snapshot stores`. Table name alone is NOT enough:
    `lupin_db_test.solution_snapshots` is isolated from `lupin_db_dev.solution_snapshots`
    despite the identical table name — the database is half the identity. The old
    table-name-only predicate got this wrong in BOTH directions (it let a shared-db write
    through, and it blocked a genuinely isolated different-database write). Fail-closed:
    an empty/absent allowlist REFUSES — an unproven destination is treated as live.

  VALIDITY (require_arms_distinct_and_clean) — is the PAIRING sound?
    The two arms must write DIFFERENT fully-qualified destinations (so v1's writes cannot
    warm v2's cold pass — design §4) AND each destination must START CLEAN (empty), because
    residue from a prior run contaminates the cold baseline exactly as one arm warming the
    other would. This check shares NO allowlist with SAFETY — it is a cross-arm property,
    not a membership test.

The two checks are deliberately not merged: a destination can be non-live (SAFETY passes)
yet shared between the arms or dirty (VALIDITY fails), and vice-versa. Each raises its own
error with its own message so the paired bridge declines LOUDLY, naming which property failed.
"""

from __future__ import annotations

from typing import Any, Optional, Set, Tuple
from urllib.parse import urlsplit


# The config allowlist key (fail-closed): fully-qualified `database.table` non-live stores.
PERMITTED_STORES_KEY = "v2 eval permitted snapshot stores"


class IsolationNotConfigured( RuntimeError ):
    """SAFETY failure — the write destination is not a PROVABLY non-live measurement store."""


class PairedTargetsNotIsolated( RuntimeError ):
    """VALIDITY failure — the two arms' destinations are not DISTINCT-and-CLEAN."""


# ---------------------------------------------------------------------------
# Fully-qualified target resolution (database + table), read from the app's own sources.
# ---------------------------------------------------------------------------
def resolve_write_target() -> str:
    """
    The TABLE the v2 write-back ORM actually writes through, read live.

    Ensures:
        - returns SolutionSnapshot.__tablename__ — the attribute SQLAlchemy routes the
          insert through, so a table rename moves the guard with it automatically.
    """
    from cosa.rest.db.vector_store_models import SolutionSnapshot
    return SolutionSnapshot.__tablename__


def _db_name( db_url: str ) -> str:
    """
    The database NAME = the PATH component of the connection url, minus its leading '/'.
    Parsed with urlsplit (mirrors v1_eval_arm._db_name) so a query/fragment '/' can never
    be mistaken for the db name.
    """
    return urlsplit( db_url ).path.lstrip( "/" )


def resolve_write_database() -> str:   # pragma: no cover - live DB boundary (get_database_url reads env)
    """
    The DATABASE the app will write to, from the app's own get_database_url() — resolved
    LIVE, never a constant, so it tracks the running environment (dev/testing/cloud).
    """
    from cosa.rest.db.database import get_database_url
    return _db_name( get_database_url() )


def fully_qualified( database: str, table: str ) -> str:
    """The `database.table` identity — the unit the SAFETY allowlist is keyed on."""
    return f"{database}.{table}"


def parse_permitted_stores( raw: Optional[ str ] ) -> Set[ str ]:
    """
    The permitted-store allowlist as a set of normalized `database.table` strings.

    Ensures:
        - returns an empty set for None or a blank/whitespace-only value (fail-closed:
          an empty allowlist proves nothing, so SAFETY will refuse).
        - splits on commas and strips each entry; empty entries are dropped.
    """
    if not raw:
        return set()
    return { entry.strip() for entry in raw.split( "," ) if entry.strip() }


# ---------------------------------------------------------------------------
# SAFETY — the destination must be a PROVABLY non-live measurement store.
# ---------------------------------------------------------------------------
def require_isolated_snapshot_table(
    config_mgr     : Any,
    *,
    write_target   : Optional[ str ] = None,
    write_database : Optional[ str ] = None,
) -> Optional[ str ]:
    """
    Refuse a paired run unless the app's write destination is a permitted non-live store.

    Requires:
        - config_mgr exposes .get( key, default, return_type ) for the v2 keys.
        - write_target / write_database, when passed, are the table / database the app
          writes through (injected for unit tests); when None they are resolved live via
          resolve_write_target() / resolve_write_database().

    Ensures:
        - returns None when writeback is OFF — no write happens, so no destination to guard.
        - returns the fully-qualified `database.table` when writeback is ON AND that
          destination is a member of the configured permitted-store allowlist.
        - raises IsolationNotConfigured otherwise, with a distinct message for each cause:
            (1) the allowlist is empty/absent — the destination cannot be PROVEN non-live
                (fail-closed), or
            (2) the destination is not in the allowlist — it may be a live store.

    Raises:
        - IsolationNotConfigured on either SAFETY failure.
    """
    writeback = config_mgr.get( "v2 snapshot writeback enabled", default=False, return_type="boolean" )
    if not writeback:
        return None

    table       = write_target if write_target is not None else resolve_write_target()
    database    = write_database if write_database is not None else resolve_write_database()
    destination = fully_qualified( database, table )

    permitted = parse_permitted_stores(
        config_mgr.get( PERMITTED_STORES_KEY, default=None, return_type="string" )
    )
    if not permitted:
        raise IsolationNotConfigured(
            f"v2 snapshot writeback is ON but the '{PERMITTED_STORES_KEY}' allowlist is empty — "
            f"the write destination '{destination}' cannot be PROVEN a non-live measurement store. "
            f"Fail-closed: refusing. Configure the isolated store(s) as `database.table` entries."
        )
    if destination not in permitted:
        raise IsolationNotConfigured(
            f"v2 snapshot write destination '{destination}' is NOT in the permitted measurement-store "
            f"allowlist {sorted( permitted )} — a paired run could write a LIVE store. Refusing (safety). "
            f"Add it to '{PERMITTED_STORES_KEY}' only if it is genuinely isolated."
        )
    return destination


# ---------------------------------------------------------------------------
# VALIDITY — the two arms must write DISTINCT, CLEAN destinations.
# ---------------------------------------------------------------------------
def require_arms_distinct_and_clean(
    v1_target   : str,
    v2_target   : str,
    *,
    v1_rowcount : int,
    v2_rowcount : int,
) -> Tuple[ str, str ]:
    """
    Refuse a paired run unless the two arms write DIFFERENT destinations that BOTH start empty.

    Requires:
        - v1_target / v2_target are the fully-qualified `database.table` each arm will write
          (from require_isolated_snapshot_table, or resolved per arm).
        - v1_rowcount / v2_rowcount are the CURRENT row counts of those destinations (the
          paired bridge queries them live; injected in unit tests). A count is the clean-start
          evidence — 0 means empty.

    Ensures:
        - returns ( v1_target, v2_target ) when they DIFFER and both counts are 0.
        - raises PairedTargetsNotIsolated with a distinct message for each cause:
            (a) the two arms share one destination — v1's writes would warm v2's cold pass
                (design §4), or
            (b) either destination is non-empty — residue contaminates the cold baseline
                exactly as cross-arm warming would.

    Raises:
        - PairedTargetsNotIsolated on either VALIDITY failure.
    """
    if v1_target == v2_target:
        raise PairedTargetsNotIsolated(
            f"v1 and v2 write the SAME destination '{v1_target}' — v1's writes would warm v2's cold "
            f"pass (design §4). The arms must use DISTINCT stores. Refusing (validity)."
        )
    dirty = []
    if v1_rowcount != 0:
        dirty.append( f"v1 '{v1_target}' holds {v1_rowcount} row(s)" )
    if v2_rowcount != 0:
        dirty.append( f"v2 '{v2_target}' holds {v2_rowcount} row(s)" )
    if dirty:
        raise PairedTargetsNotIsolated(
            "a paired run requires each arm's store to START CLEAN (empty) — residue contaminates the "
            "cold baseline just as one arm warming the other would: " + "; ".join( dirty ) + ". Refusing (validity)."
        )
    return ( v1_target, v2_target )
