"""Snapshot-store isolation guard for the CJ Flow v2 paired eval.

The v2 flow writes snapshots back when `v2 snapshot writeback enabled` is True (lupin-app.ini).
A paired v1-vs-v2 run must never let those writes hit a live store.
It must also never let one arm's writes warm the other arm's cold pass.
Two separate, independent checks enforce this.
A store is safe to use only when both pass.

Safety (require_isolated_snapshot_table) asks whether the destination is non-live.
It fails closed by allowlist membership.
The live write destination is the fully-qualified (database, table).
The database comes from the app's own get_database_url().
The table comes from SolutionSnapshot.__tablename__, which is what the ORM actually writes through.
It is permitted only when that `database.table` is a member of the config allowlist
`v2 eval permitted snapshot stores`. The table name alone is not enough: the same table name
in two databases is two stores, so the database is half the identity.
A table-name-only check would let a shared-database write through.
It would also block a truly isolated write to a different database.
An empty or absent allowlist refuses, because an unproven destination is treated as live.

Validity (require_arms_distinct_and_clean) asks whether the pairing is sound.
The two arms must write different fully-qualified destinations, so v1's writes cannot warm
v2's cold pass. Each destination must also start clean (empty), because residue from a prior
run contaminates the cold baseline just as one arm warming the other would.
This check shares no allowlist with safety. It is a cross-arm property, not a membership test.

The two checks are kept apart.
A destination can be non-live (safety passes) yet shared
between the arms or dirty (validity fails), and the reverse.
Each check raises its own error with its own message.
The paired bridge therefore declines loudly and names which property failed.
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
    """Safety failure: the write destination is not a provably non-live measurement store."""


class PairedTargetsNotIsolated( RuntimeError ):
    """Validity failure: the two arms' destinations are not distinct and clean."""


class ConfigTableMismatch( RuntimeError ):
    """Config failure: the declared `v2 snapshot table` names a table the ORM never writes.

    A config value naming a table the write-back never reaches would make the per-arm
    clean-step `TRUNCATE` the wrong table. The real write target would stay dirty while every
    check reports clean. It is raised loudly so a drifted config cannot silently pass.
    """


class NotAMeasurementDatabase( RuntimeError ):
    """Safety failure: a destructive clean-step was aimed at a non-measurement database."""


class PairedCorpusExercisesLeak( RuntimeError ):
    """Corpus failure: an arg-extracting corpus was paired with a v1 pin that still has the leak.

    The leak: the runtime-argument expeditor hands out a registry entry's own fallback_defaults
    dict. The first replayed body's extracted arg then sticks as every later body's default for
    the process life. In a sequential replay that is a cross-body contaminant, so it corrupts
    the measurement itself. The fix is LEAK_FIX_SHA.
    The premise is derived from the pin, not hard-coded.
    The leak is live at a pin exactly when LEAK_FIX_SHA is not an ancestor of it
    (`pin_carries_leak_fix`). A pure-routing corpus such as 'simple' is safe at any pin,
    because its commands never reach arg extraction.

    V1_PIN_SHA carries LEAK_FIX_SHA, so the arm is leak-free and an arg-extracting corpus is
    admitted. Refusing it there would cite a defect that is not present.
    It would also quietly force the baseline onto 'simple', below the spec of 60 samples
    over all commands. The pin also carries
    REQUEST_PATH_REFACTOR_SHA, so the measured v1 is the refactored request path, not the one the
    criteria were written against. The other candidate pin is unrefactored but leaky. The trade
    favours the refactored pin because a leak corrupts what is measured. The refactor is expected,
    not yet measured, to change the path's structure and not the numbers reported.
    It is raised loudly, naming the offending commands and the pin.
    """


# ---------------------------------------------------------------------------
# Fully-qualified target resolution (database + table), read from the app's own sources.
# ---------------------------------------------------------------------------
def resolve_write_target() -> str:
    """
    The table the v2 write-back ORM actually writes through, read live.

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

    The per-arm clean-step runs `TRUNCATE` on the table the ORM writes through.
    A declared table the writes never reach would be truncated while the real destination
    stayed dirty, so the declaration is cross-checked against the ORM.

    Requires:
        - config_mgr exposes .get( key, default, return_type ).
        - write_target, when passed, is the table the ORM writes through (injected for tests);
          when None it is resolved live via resolve_write_target().

    Ensures:
        - returns the write target (the ORM __tablename__) when the declared value equals it,
          after stripping surrounding whitespace.
        - the clean-step calls this first, so the `TRUNCATE` identifier is only ever the
          resolved ORM __tablename__, never a raw config string. That leaves no injection surface.
        - raises ConfigTableMismatch otherwise, with both values quoted, including the case of
          an absent or blank declaration (which can never equal a real table name).

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
    The database name: the path component of the connection url, minus its leading '/'.

    It is parsed with urlsplit (as v1_eval_arm._db_name does), so a '/' in the query or
    fragment can never be mistaken for the db name.
    """
    return urlsplit( db_url ).path.lstrip( "/" )


def assert_measurement_db( db_url: Any ) -> None:
    """
    Refuse a destructive clean-step unless it targets a measurement database.

    The peer of v1_eval_arm.assert_test_db, living here so v2's clean-step reaches it without
    the v1<->v2 import cycle. A `TRUNCATE` is irreversible, so this is a hard precondition:
    it fails loudly and never proceeds on anything but lupin_db_test or lupin_db_v1baseline.

    Requires:
        - db_url is the url of the connection the `TRUNCATE` will run on, read off
          connection.engine.url by the caller, never a separate argument. A separate
          argument could name a different database than the one actually truncated.

    Ensures:
        - returns None when db_url is a string whose db name is in MEASUREMENT_DB_NAMES.
        - the db name must match the set exactly; a substring check would let
          'lupin_db_test_shadow' in.
        - raises NotAMeasurementDatabase for any other, missing or non-string target, with the
          offending value quoted. The caller must not run `TRUNCATE`.

    Raises:
        - NotAMeasurementDatabase on any non-measurement, missing or non-string target.
    """
    if not isinstance( db_url, str ) or _db_name( db_url ) not in MEASUREMENT_DB_NAMES:
        raise NotAMeasurementDatabase(
            f"refusing to TRUNCATE: the DB target is not a measurement database "
            f"(allowed db names: {sorted( MEASUREMENT_DB_NAMES )}); got {db_url!r}. "
            f"Fail loud, never proceed."
        )


def resolve_write_database() -> str:   # pragma: no cover - live DB boundary (get_database_url reads env)
    """
    The database the app will write to, from the app's own get_database_url().

    It is resolved live and never held as a constant, so it tracks the running
    environment (dev, testing or cloud).
    """
    from cosa.rest.db.database import get_database_url
    return _db_name( get_database_url() )


def fully_qualified( database: str, table: str ) -> str:
    """The `database.table` identity, the unit the safety allowlist is keyed on."""
    return f"{database}.{table}"


def parse_permitted_stores( raw: Optional[ str ] ) -> Set[ str ]:
    """
    The permitted-store allowlist as a set of normalized `database.table` strings.

    Ensures:
        - returns an empty set for None or a blank or whitespace-only value. This fails
          closed: an empty allowlist proves nothing, so the safety check will refuse.
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
        - write_target and write_database, when passed, are the table and database the app
          writes through (injected for unit tests); when None they are resolved live via
          resolve_write_target() and resolve_write_database().

    Ensures:
        - returns None when writeback is off, since no write happens and there is no
          destination to guard.
        - returns the fully-qualified `database.table` when writeback is on and that
          destination is a member of the configured permitted-store allowlist.
        - raises IsolationNotConfigured otherwise, with a distinct message for each cause:
            (1) the allowlist is empty or absent, so the destination cannot be proven
                non-live (fail-closed), or
            (2) the destination is not in the allowlist, so it may be a live store.

    Raises:
        - IsolationNotConfigured on either safety failure.
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
    Refuse a paired run unless the arms write different destinations that both start empty.

    Requires:
        - v1_target and v2_target are the fully-qualified `database.table` each arm will write
          (from require_isolated_snapshot_table, or resolved per arm).
        - v1_rowcount and v2_rowcount are the current row counts of those destinations (the
          paired bridge queries them live; injected in unit tests). A count is the clean-start
          evidence, and 0 means empty.

    Ensures:
        - returns ( v1_target, v2_target ) when they differ and both counts are 0.
        - raises PairedTargetsNotIsolated with a distinct message for each cause:
            (a) the two arms share one destination, so v1's writes would warm v2's cold pass, or
            (b) either destination is non-empty, so residue contaminates the cold baseline
                just as cross-arm warming would.

    Raises:
        - PairedTargetsNotIsolated on either validity failure.
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
    Pre-run validity step: query each store's live row count, then require distinct and clean.

    It is the caller that require_arms_distinct_and_clean needs, since a check nobody calls
    checks nothing. It separates the pure decision from the live IO (rowcount_fn), so the
    composition is unit-testable with a fake counter.

    Requires:
        - v1_target and v2_target are the two arms' fully-qualified `database.table` destinations.
        - rowcount_fn(fully_qualified) returns the current row count of that store (live in the
          bridge via count_store_rows, faked in tests).

    Ensures:
        - queries both stores' counts via rowcount_fn and forwards them to
          require_arms_distinct_and_clean, returning its ( v1_target, v2_target ) on success.
        - the count and the safety membership decision key on the same fully-qualified
          `database.table` string, so a count never attests to a different store than the
          one that was blessed.
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
    The live row count of a `database.table` store, the bridge's rowcount_fn for the real run.

    It connects to the database named in `fully_qualified`, not the app's default engine.
    It takes the host and credentials from get_database_url().
    It swaps the url path to the target database via urlsplit, so a query or fragment
    cannot smuggle in a different db.
    The count is therefore of the exact store the safety check blessed, never a same-named
    table in another db. It runs a real `SELECT COUNT(*)`, so it is a live boundary; the
    pure composition it feeds (assert_paired_isolation) is the part that is unit-tested.
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
    The router commands that invoke runtime-argument extraction, the leak site.

    Read live from the registry (JOB_ARG_CONTRACTS) rather than a frozen list, so the guard
    tracks a newly added agent at once. It detects the contact instead of modelling a snapshot.

    Ensures:
        - returns the set of command keys the runtime-argument expeditor extracts args for.
    """
    from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS
    return set( JOB_ARG_CONTRACTS.keys() )


LEAK_FIX_SHA              = "bf77852b"   # the fix for the 8aa89f42 fallback_defaults leak

# ── The pinned v1 baseline sha (MOVED here 2026-08-26, row e2099400 §2 Step 2) ────────
# It lived in v1_eval_arm, and THIS FILE — a keeper — imported it back out, which is a
# third edge out of the excision's delete list. It belongs here anyway: the comment that
# came with it already says the guard's premise is derived from this constant.
# WHY THIS PIN (rows 647f3733 + 297b1fc3, 2026-08-21 — stated here so the report names the
# choice AND its cost, and so the isolation guard's premise is derived from this constant
# rather than hard-coded): 15536409 carries bf77852b, the fix for the 8aa89f42
# fallback_defaults leak — a SEQUENTIAL-REPLAY CONTAMINANT that would corrupt the measurement
# itself — so the arm is LEAK-FREE. It ALSO carries the 9805783d request-path refactor, so the
# measured v1 is the REFACTORED request path, not the one Rick's criteria were written against.
# The trade was chosen deliberately: a leak corrupts what is measured; the refactor is EXPECTED
# — not yet measured — to change the path's structure, not the numbers reported. The other
# pin, b0735467, is unrefactored but leaky. Moving this constant below bf77852b turns
# test_eval_isolation_guard's premise test red on purpose.
V1_PIN_SHA       = "15536409"
V1_PIN_RATIONALE = ( "leak-free (carries bf77852b, the 8aa89f42 fix) but REFACTORED request path "
                     "(carries 9805783d); the refactor's effect on the reported numbers is EXPECTED "
                     "nil, NOT measured — rows 647f3733/297b1fc3" )

REQUEST_PATH_REFACTOR_SHA = "9805783d"   # the v1 request-path refactor the fix sits on top of


def _git_is_ancestor( ancestor: str, descendant: str, repo_root: Optional[ str ] = None ) -> bool:
    """
    Ask git whether `ancestor` is reachable from `descendant` in the project repo.

    Requires:
        - both are sha prefixes git can resolve in the repo at repo_root (default: the
          project root from cu.get_project_root(), i.e. LUPIN_ROOT)

    Ensures:
        - True when `git merge-base --is-ancestor` exits 0, False when it exits 1
        - raises RuntimeError on any other exit (an unresolvable sha, a missing repo) and
          never guesses: an unanswerable question must not read as "leak-free" or as "leaky"
    """
    import subprocess
    if repo_root is None:
        import cosa.utils.util as cu
        repo_root = cu.get_project_root()
    proc = subprocess.run( [ "git", "-C", repo_root, "merge-base", "--is-ancestor", ancestor, descendant ],
                           capture_output=True, text=True )
    if proc.returncode == 0: return True
    if proc.returncode == 1: return False
    raise RuntimeError(
        f"git merge-base --is-ancestor {ancestor} {descendant} failed ({proc.returncode}) in "
        f"{repo_root}: {proc.stderr.strip()}"
    )


def pin_carries_leak_fix( pin_sha: str, *, repo_root: Optional[ str ] = None, is_ancestor_fn=None ) -> bool:
    """
    Does the pinned v1 sha carry the fallback_defaults leak fix (LEAK_FIX_SHA)?

    Requires:
        - pin_sha is a non-empty sha prefix
        - is_ancestor_fn, when given, has _git_is_ancestor's signature (injected in tests);
          when None the real git is asked

    Ensures:
        - returns True iff LEAK_FIX_SHA is an ancestor of pin_sha
        - raises ValueError on an empty pin (a blank pin is a configuration error, not a verdict)
    """
    if not pin_sha:
        raise ValueError( "pin_carries_leak_fix needs a non-empty pin sha" )
    fn = is_ancestor_fn if is_ancestor_fn is not None else _git_is_ancestor
    return bool( fn( LEAK_FIX_SHA, pin_sha, repo_root ) )


def require_leak_free_corpus( corpus_commands, *, agentic_commands: Optional[ Set[ str ] ] = None,
                              pinned_sha: Optional[ str ] = None,
                              pin_carries_fix: Optional[ bool ] = None ) -> Set[ str ]:
    """
    Refuse a corpus that routes to an arg-extracting command when the v1 pin has the leak.

    The refusal applies only while the pinned v1 sha still carries the fallback_defaults leak,
    so it is aware of the pin.

    Requires:
        - corpus_commands is an iterable of the router command strings the corpus's utterances
          resolve to (the second element of each (utterance, command) pair from load_corpus).
        - agentic_commands, when given, is the leak-carrying command set (injected in tests);
          when None it is read live from the registry via agentic_command_names().
        - pinned_sha, when given, is the v1 pin to judge; when None it is this module's V1_PIN_SHA.
        - pin_carries_fix, when given, overrides the git question (injected in tests); when
          None it is pin_carries_leak_fix( pinned_sha ).

    Ensures:
        - returns the corpus_commands as a set, unchanged, when it is disjoint from the
          arg-extracting commands, so the leak site is never reached, whatever the pin.
        - returns the set, unchanged, when it intersects but the pin carries the fix. There
          is no leak to refuse, and refusing would cite a defect that is not present and force
          the baseline onto a pure-routing corpus below its own spec.
        - raises PairedCorpusExercisesLeak, naming every offending command (sorted) and the
          pin, when it intersects and the pin lacks the fix: the leak would contaminate the
          sequential replay.

    Raises:
        - PairedCorpusExercisesLeak on a non-empty intersection at a leaky pin.
    """
    commands = set( corpus_commands )
    leaky    = agentic_commands if agentic_commands is not None else agentic_command_names()
    tripped  = sorted( commands & leaky )
    if not tripped:
        return commands
    if pinned_sha is None:
        pinned_sha = V1_PIN_SHA   # module-local since 2026-08-26; was a lazy import out of v1_eval_arm
    carries = pin_carries_fix if pin_carries_fix is not None else pin_carries_leak_fix( pinned_sha )
    if carries:
        return commands   # the leak is fixed at this pin — an arg-extracting corpus is admitted
    raise PairedCorpusExercisesLeak(
        "corpus routes to arg-extracting command(s) whose fallback_defaults leak (bug 8aa89f42, "
        f"fixed at {LEAK_FIX_SHA}) is UNFIXED at the pinned v1 sha {pinned_sha} and would "
        "contaminate the sequential replay: " + ", ".join( tripped ) + ". Either move the pin "
        f"to a sha that carries {LEAK_FIX_SHA} or use a pure-routing corpus (e.g. 'simple'). "
        "Refusing (corpus)."
    )
