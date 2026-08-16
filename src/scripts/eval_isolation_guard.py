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

from typing import Any, Callable, Optional, Set, Tuple
from urllib.parse import urlsplit


# The config allowlist key (fail-closed): fully-qualified `database.table` non-live stores.
PERMITTED_STORES_KEY = "v2 eval permitted snapshot stores"

# The operator-declared snapshot-table key (lupin-app.ini). It exists to be CROSS-CHECKED
# against the table the ORM actually writes through — a declaration, not a source of truth.
CONFIG_SNAPSHOT_TABLE_KEY = "v2 snapshot table"

# The measurement databases a destructive per-arm clean-step MAY truncate — exactly these
# two, matched on the url's db NAME (not a substring). This is the guard's own authoritative
# copy for the v2 arm's clean-step; it intentionally equals v1_eval_arm.MEASUREMENT_DB_NAMES
# (the v1 arm's destructive-truncate allowlist). It is NOT shared with v1 by import because
# v1_eval_arm imports v2_eval (v1 -> v2), and v2's clean-step imports THIS module (v2 -> guard),
# so a single shared home in either arm would risk the v1<->v2 cycle; the guard is the neutral
# home both arms can reach acyclically. Consolidating v1's local copy onto this one is deferred
# (it would edit v1_eval_arm.py + its tests, wider than this row).
MEASUREMENT_DB_NAMES = frozenset( { "lupin_db_test", "lupin_db_v1baseline" } )


class IsolationNotConfigured( RuntimeError ):
    """SAFETY failure — the write destination is not a PROVABLY non-live measurement store."""


class PairedTargetsNotIsolated( RuntimeError ):
    """VALIDITY failure — the two arms' destinations are not DISTINCT-and-CLEAN."""


class ConfigTableMismatch( RuntimeError ):
    """CONFIG failure — the declared `v2 snapshot table` names a table the ORM never writes.

    The "wired but pointing wrong" defect (Mr Radio, 2026-08-16): a config value that names a
    table the write-back never reaches would make the per-arm clean-step TRUNCATE the wrong
    table, leaving the real write target dirty while every check reports clean. Raised loudly so
    a drifted config cannot silently pass.
    """


class NotAMeasurementDatabase( RuntimeError ):
    """SAFETY failure — a destructive clean-step was aimed at a non-measurement database."""


class PairedCorpusExercisesLeak( RuntimeError ):
    """CORPUS failure — the corpus routes to an arg-extracting command whose fallback_defaults
    leak (bug 8aa89f42, fixed at bf77852b) is UNFIXED at the pinned v1 sha b0735467.

    The v1 arm runs against a worktree pinned at b0735467 (design §2a) — the last sha before the
    9805783d request-path refactor, and bf77852b (the leak fix) sits on top of that refactor, so
    the fix cannot be taken without changing the very path being measured. That leaves the leak
    live at the pin: the runtime-argument expeditor hands out a registry entry's OWN
    fallback_defaults dict, so the first replayed body's extracted arg STICKS as every later
    body's default for the process life — a cross-body contaminant in a SEQUENTIAL replay. The
    'simple' corpus is safe because its commands are pure routing and never reach arg extraction;
    a corpus containing any AGENTIC_AGENTS command is not. Raised loudly, naming the offender.
    """


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


def require_config_table_matches_write_target(
    config_mgr   : Any,
    *,
    write_target : Optional[ str ] = None,
) -> str:
    """
    Refuse a paired run unless the declared `v2 snapshot table` equals the ORM write target.

    The per-arm clean-step TRUNCATEs the table the ORM writes through; the config key exists so
    an operator can DECLARE that table, and this cross-check proves the declaration matches
    reality (SolutionSnapshot.__tablename__). A config naming a table the writes never reach is
    the "wired but pointing wrong" defect — it would truncate an unrelated table and leave the
    real destination dirty. The clean-step calls this FIRST so the TRUNCATE identifier is only
    ever the resolved ORM __tablename__, never a raw config string (no injection surface).

    Requires:
        - config_mgr exposes .get( key, default, return_type ).
        - write_target, when passed, is the table the ORM writes through (injected for tests);
          when None it is resolved live via resolve_write_target().

    Ensures:
        - returns the write target (the ORM __tablename__) when the declared value equals it,
          after stripping surrounding whitespace.
        - raises ConfigTableMismatch otherwise, with BOTH values quoted — including the case of
          an absent/blank declaration (which can never equal a real table name).

    Raises:
        - ConfigTableMismatch on any drift between the declared table and the ORM write target.
    """
    target   = write_target if write_target is not None else resolve_write_target()
    declared = config_mgr.get( CONFIG_SNAPSHOT_TABLE_KEY, default=None, return_type="string" )
    declared_norm = ( declared or "" ).strip()
    if declared_norm != target:
        raise ConfigTableMismatch(
            f"the declared '{CONFIG_SNAPSHOT_TABLE_KEY}' = {declared!r} does NOT equal the table the "
            f"ORM writes through ({target!r}). A per-arm clean-step would TRUNCATE the declared table "
            f"and leave the real write target dirty. Refusing (config). Set '{CONFIG_SNAPSHOT_TABLE_KEY}' "
            f"= '{target}' to match SolutionSnapshot.__tablename__."
        )
    return target


def _db_name( db_url: str ) -> str:
    """
    The database NAME = the PATH component of the connection url, minus its leading '/'.
    Parsed with urlsplit (mirrors v1_eval_arm._db_name) so a query/fragment '/' can never
    be mistaken for the db name.
    """
    return urlsplit( db_url ).path.lstrip( "/" )


def assert_measurement_db( db_url: Any ) -> None:
    """
    Refuse a destructive clean-step unless it targets a MEASUREMENT database.

    The peer of v1_eval_arm.assert_test_db, living here so v2's clean-step reaches it without
    the v1<->v2 import cycle. A TRUNCATE is irreversible, so this is a HARD precondition: fire
    LOUD and never proceed on anything but lupin_db_test / lupin_db_v1baseline. The db NAME must
    match the set EXACTLY (a substring check would let 'lupin_db_test_shadow' smuggle in).

    Requires:
        - db_url is the url of the connection the TRUNCATE will run on (read off
          connection.engine.url by the caller, never a decoupled arg — the de9c32d0 lesson).

    Ensures:
        - returns None when db_url is a string whose db name is in MEASUREMENT_DB_NAMES.
        - raises NotAMeasurementDatabase for any other / missing / non-string target, with the
          offending value quoted — the caller must not TRUNCATE.

    Raises:
        - NotAMeasurementDatabase on any non-measurement / missing / non-string target.
    """
    if not isinstance( db_url, str ) or _db_name( db_url ) not in MEASUREMENT_DB_NAMES:
        raise NotAMeasurementDatabase(
            f"refusing to TRUNCATE: the DB target is not a measurement database "
            f"(allowed db names: {sorted( MEASUREMENT_DB_NAMES )}); got {db_url!r}. "
            f"Fail loud, never proceed."
        )


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


def assert_paired_isolation(
    v1_target   : str,
    v2_target   : str,
    *,
    rowcount_fn : Callable[ [ str ], int ],
) -> Tuple[ str, str ]:
    """
    The pre-run VALIDITY step: query each store's LIVE row count, then require distinct-and-clean.

    This is the caller require_arms_distinct_and_clean needs — a check with no caller is no
    check. It separates the pure decision (require_arms_distinct_and_clean) from the live IO
    (rowcount_fn), so the composition is unit-testable with a fake counter and the bridge
    supplies count_store_rows for the real run.

    The row count and the SAFETY membership decision key on the SAME fully-qualified
    `database.table` string — the single identity — so the count can never attest to a
    different store than the one that was blessed.

    Requires:
        - v1_target / v2_target are the two arms' fully-qualified `database.table` destinations.
        - rowcount_fn(fully_qualified) returns the current row count of THAT store (live in the
          bridge via count_store_rows, faked in tests).

    Ensures:
        - queries BOTH stores' counts via rowcount_fn and forwards them to
          require_arms_distinct_and_clean, returning its ( v1_target, v2_target ) on success.
        - raises PairedTargetsNotIsolated (from the inner check) when the arms share a store or
          either store is non-empty.
    """
    return require_arms_distinct_and_clean(
        v1_target, v2_target,
        v1_rowcount=rowcount_fn( v1_target ),
        v2_rowcount=rowcount_fn( v2_target ),
    )


def count_store_rows( fully_qualified: str ) -> int:   # pragma: no cover - live DB boundary (real SELECT COUNT)
    """
    The LIVE row count of a `database.table` store — the bridge's rowcount_fn for the real run.

    Connects to the DATABASE NAMED IN `fully_qualified` (not the app's default engine): it takes
    get_database_url()'s host/credentials and swaps the db-path to the target database via
    urlsplit (so a query/fragment cannot smuggle a different db), so the count is OF the exact
    store the SAFETY check blessed — never a same-named table in a different db. Live boundary (a
    real SELECT COUNT(*)); the pure composition it feeds (assert_paired_isolation) is unit-tested.
    """
    from sqlalchemy import create_engine, text
    from cosa.rest.db.database import get_database_url
    database, _, table = fully_qualified.partition( "." )
    target_url = urlsplit( get_database_url() )._replace( path=f"/{database}" ).geturl()
    target_engine = create_engine( target_url )
    try:
        with target_engine.connect() as connection:
            return int( connection.execute( text( f"SELECT COUNT(*) FROM {table}" ) ).scalar() )
    finally:
        target_engine.dispose()


# ---------------------------------------------------------------------------
# CORPUS — the paired corpus must not route to an arg-extracting command.
# ---------------------------------------------------------------------------
def agentic_command_names() -> Set[ str ]:
    """
    The router commands that invoke runtime-argument extraction — the fallback_defaults leak site.

    Read LIVE from the registry (AGENTIC_AGENTS) rather than a frozen list, so the guard tracks
    a thirteenth agent the moment someone adds one — detect the contact, do not model a snapshot
    of it.

    Ensures:
        - returns the set of command keys the runtime-argument expeditor extracts args for.
    """
    from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS
    return set( AGENTIC_AGENTS.keys() )


def require_leak_free_corpus( corpus_commands, *, agentic_commands: Optional[ Set[ str ] ] = None ) -> Set[ str ]:
    """
    Refuse a paired run whose corpus routes to any arg-extracting command (the leak site).

    Requires:
        - corpus_commands is an iterable of the router command strings the corpus's utterances
          resolve to (the second element of each (utterance, command) pair from load_corpus).
        - agentic_commands, when given, is the leak-carrying command set (injected in tests);
          when None it is read LIVE from the registry via agentic_command_names().

    Ensures:
        - returns the corpus_commands as a set, unchanged, when it is DISJOINT from the
          arg-extracting commands — the fallback_defaults leak is never reached.
        - raises PairedCorpusExercisesLeak, NAMING every offending command (sorted), when the
          corpus routes to one or more arg-extracting commands: at the pinned v1 sha b0735467
          that leak is unfixed and would contaminate the sequential replay.

    Raises:
        - PairedCorpusExercisesLeak on any non-empty intersection.
    """
    commands = set( corpus_commands )
    leaky    = agentic_commands if agentic_commands is not None else agentic_command_names()
    tripped  = sorted( commands & leaky )
    if tripped:
        raise PairedCorpusExercisesLeak(
            "corpus routes to arg-extracting command(s) whose fallback_defaults leak (bug "
            "8aa89f42) is UNFIXED at the pinned v1 sha b0735467 and would contaminate the "
            "sequential replay: " + ", ".join( tripped ) + ". Use a pure-routing corpus (e.g. "
            "'simple'). Refusing (corpus)."
        )
    return commands
