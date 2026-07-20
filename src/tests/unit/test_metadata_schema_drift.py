"""
ORM-metadata vs live-schema drift detector — Half 2 of the drift build (f8422ffa).

Plan: src/rnd/v0.1.9/2026.07.19-model-migration-drift-detector-plan.md §3 "Half 2"

What this is
------------
One assertion: ``compare_metadata( MigrationContext, Base.metadata )`` must
return an EMPTY diff against a migration-built database. Everything else in this
file exists to make that assertion trustworthy or to keep it from crying wolf.

Why the API and not the CLI
---------------------------
``alembic revision --autogenerate`` WRITES a revision file — a mutation, and one
that would litter ``src/migrations/versions/`` on every run.
``alembic.autogenerate.compare_metadata()`` returns the diff list and writes
nothing, which is what makes this tier read-only and therefore ``:7999``-eligible.
Verified at source (alembic 1.18.1): ``compare_metadata`` is
``produce_migrations(...).upgrade_ops.as_diffs()`` — comparison only, no I/O.

How this differs from the other two halves — the seam is deliberate
-------------------------------------------------------------------
- **Half 1** (``test_model_migration_drift.py``) AST-parses the migration files.
  Hermetic, no DB, but sees literal ``op.*`` calls only.
- **Half 3b** (``cosa/rest/db/schema_drift.py``) is the boot-time alarm. It is
  deliberately PRESENCE-only — its own docstring defers type, nullability, and
  server-default nuance to "the ``compare_metadata()`` tier (Half 2)". This file
  is that tier. It is the only one of the three that can see a column which
  exists but has the WRONG SHAPE.
- Neither is sold as the other. This one is complete where Half 1 is partial,
  and richer where Half 3b is deliberately blunt.

Which database, and why that is not an arbitrary choice
--------------------------------------------------------
This targets a MIGRATION-BUILT database — ``lupin_db_test`` by default.

That is a finding, not a preference. The Q2 inventory (2026-07-19, Seat 2) ran
this comparison against both live databases:

    lupin_db_test → 0 diff entries
    lupin_db_dev  → 27 diff entries
    BOTH stamped d47487369407

So the models and the migration chain ARE in sync; ``lupin_db_dev`` has diverged
from what its own migration chain produces (filed separately as ``692d1596``).
Asserting against dev would be permanently RED for 27 reasons that are not the
defect this detector exists to catch — the fastest way to teach everyone to
ignore it.

⚠️ NO OP-CLASS FILTERING, DELIBERATELY. The assertion is on the WHOLE diff. A
``[op for op in diff if op[0] == "add_column"]`` would be a known-drift allowlist
wearing a comprehension, and rebuilding a hand-maintained twin is the exact
failure mode §2 of the plan cites as the reason this detector exists. If this
test goes red, fix the drift or change the migration — never widen the filter.

SKIP, never fail, when the substrate moved
------------------------------------------
``lupin_db_test`` is owned by the ``:8000`` test server and the ``clean_test_db``
fixture WIPES it. A detector that goes red because its own substrate moved is a
cry-wolf detector, so the precondition is explicit: this asserts only when the
target DB is reachable AND stamped at the migration head. Otherwise it SKIPS with
a stated reason. Unreachable-or-stale is "I could not measure", which is not the
same claim as "there is no drift", and this file never conflates the two.

Controls — this oracle is proven RED, not assumed
--------------------------------------------------
``test_control_a_*`` and ``test_control_primary_shape_*`` mutate a COPY of the
metadata at RUNTIME (``Table.to_metadata``) and require the comparison to fire.
No tree edit, no DB write, no migration file. Both were confirmed RED against
``lupin_db_dev`` AND ``lupin_db_test`` during implementation.

⚠️ THE 8 PGVECTOR TABLES ARE COVERED BY THIS FILE AND NOTHING ELSE
------------------------------------------------------------------
Migration ``d0e1f2a3b4c5`` creates the ``VECTOR_STORE_MODELS`` tables via
``table.create( bind, checkfirst=True )`` — no DDL text at all. Two consequences,
both found by Seat 1 (Clayton) and both making this file solely responsible:

1. Half 1's AST parser cannot see those tables **by construction**, not by parser
   weakness — there are no ``op.add_column`` / ``op.create_table`` calls to parse.
2. ``checkfirst=True`` means that on an EXISTING database the create is SKIPPED
   ENTIRELY. So a ``mapped_column`` added to one of those 8 models later is never
   created by that migration — which is precisely the target defect, against
   which that migration offers zero protection.

⇒ For those 8 tables, ``compare_metadata()`` is not redundant coverage, it is the
ONLY coverage. ``test_control_vector_store_table_*`` is therefore parametrized
over ``VECTOR_STORE_MODELS`` itself — it self-updates if a 9th table is added,
rather than hard-coding a list that would silently stop covering new ones.

VERIFIED, not assumed (2026-07-19): all 8 are present on ``Base.metadata``
without any tail import, all 8 exist in ``lupin_db_test``, and each was
individually driven RED by a synthetic column. An empty diff here is empty for
the right reason on exactly the tables that most need it.

NAMED GAPS — stated rather than papered over
---------------------------------------------
1. **Control B (docstring-only mention) is STRUCTURALLY INAPPLICABLE here.**
   ``compare_metadata`` reflects the live schema and never reads migration TEXT,
   so it cannot silently degrade into a text search and there is nothing for B to
   prove. B remains non-optional for Half 1's AST oracle, where it is
   load-bearing. A control invented to satisfy a checklist would manufacture the
   reassurance it was supposed to earn.
2. **The PRIMARY control cannot be reproduced in its true historical direction —
   CLOSED AS UNBUILDABLE, not owed.** Seat 1 proved ``61a9851d`` committed the
   model and the migration ATOMICALLY, so the ``f68bc520``/``b49ddc9f`` drift
   never existed in any commit — only in the working tree, which is the
   ``--reload`` hazard itself. ``test_control_primary_shape_*`` below drives the
   real incident column in the INVERTED direction, which is the strongest form
   that can exist. No throwaway database would have helped.
3. Reads ``postgres_models.Base`` only; tables on any other declarative base are
   invisible here, exactly as in Half 3b. (The 8 pgvector models register on this
   same Base — verified above — so they are inside the boundary, not outside it.)

Venue: ``:7999`` unit tier. Read-only — reflection and comparison only, no DDL,
no DML, no revision file.
"""

import os
from unittest import mock

import pytest

from sqlalchemy import Column, MetaData, String, create_engine
from sqlalchemy.exc import SQLAlchemyError

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from cosa.rest.postgres_models import Base


# An explicit URL wins over everything, so a caller can point this at any
# migration-built database (a CI service container, a throwaway) without
# editing the test.
URL_OVERRIDE_ENV = "LUPIN_DRIFT_CHECK_DATABASE_URL"

# The column whose absence produced the measured incident: 12 live 500s on
# /api/tasks, 2026-07-19. Used by the PRIMARY-shape control.
INCIDENT_TABLE  = "task_items"
INCIDENT_COLUMN = "park_reason_captured_at"

SYNTHETIC_COLUMN = "seat2_control_a_synthetic"


def resolve_migration_built_database_url( environ=None ):
    """
    Resolve the URL of a MIGRATION-BUILT database to compare against.

    Deterministic by construction: it does NOT inherit whatever ``LUPIN_ENV``
    the developer's shell happens to carry, because a drift assertion that
    silently retargets its database depending on the caller's environment is
    measuring something different from run to run.

    Connection-string CONSTRUCTION is delegated to the app's single builder
    (``cosa.rest.db.database.get_database_url``) so no connection logic is
    duplicated here — the same rule ``src/migrations/env.py`` states for itself.

    Requires:
        - cosa.rest.db.database is importable

    Ensures:
        - returns environ[URL_OVERRIDE_ENV] verbatim when that is set non-empty
        - otherwise returns the app builder's URL evaluated as though
          LUPIN_ENV="testing", with DATABASE_URL and DB_NAME neutralised so a
          stray shell override cannot retarget the comparison
        - does not mutate the caller's environment beyond the call

    Args:
        environ: mapping to read (defaults to os.environ; injectable for tests)

    Returns:
        str — a concrete SQLAlchemy URL
    """
    environ = os.environ if environ is None else environ

    override = environ.get( URL_OVERRIDE_ENV )
    if override:
        return override

    from cosa.rest.db.database import get_database_url

    # Force the testing branch of the builder and strip the two vars that could
    # redirect it elsewhere. patch.dict restores os.environ on exit.
    with mock.patch.dict( os.environ, { "LUPIN_ENV": "testing" }, clear=False ):
        os.environ.pop( "DATABASE_URL", None )
        os.environ.pop( "DB_NAME", None )
        return get_database_url()


def read_stamped_revision( connection ):
    """
    Read the database's stamped Alembic revision, read-only.

    ``MigrationContext.get_current_heads()`` guards on ``_has_version_table()``
    and returns ``()`` when the version table is absent — it does NOT call
    ``_ensure_version_table()``, so no DDL is issued (verified at source,
    alembic 1.18.1 runtime/migration.py). That matters: a detector must not
    create schema in the database it is judging.

    Ensures:
        - returns the comma-joined head string, or None when unstamped/unreadable
        - never raises a SQLAlchemyError to the caller — an unreadable revision
          degrades to None, which the precondition turns into a SKIP

    Args:
        connection: an open SQLAlchemy Connection

    Returns:
        str | None
    """
    try:
        heads = MigrationContext.configure( connection ).get_current_heads()
    except SQLAlchemyError:
        return None
    return ",".join( heads ) if heads else None


def read_script_head():
    """
    Read the migration scripts' head revision.

    Ensures:
        - returns the head revision id, or None when it cannot be resolved
        - never raises

    Returns:
        str | None
    """
    try:
        from alembic.script import ScriptDirectory
        from cosa.rest.db.auto_migrate import build_alembic_config
        return ScriptDirectory.from_config( build_alembic_config() ).get_current_head()
    except Exception:
        return None


def precondition_failure( stamped, head ):
    """
    Decide whether the target database is a valid substrate for the assertion.

    The whole point of this function is that "I could not measure" and "there is
    no drift" are different claims. Only a database that is reachable AND at head
    can distinguish them, so anything else becomes a stated SKIP.

    Ensures:
        - returns None when stamped and head are both known and equal
        - otherwise returns a human-readable reason naming what was wrong

    Args:
        stamped: the DB's stamped revision, or None
        head:    the migration scripts' head revision, or None

    Returns:
        str | None
    """
    if stamped is None:
        return (
            "target database has no readable Alembic stamp (unmigrated, empty, or "
            "wiped by clean_test_db) — cannot distinguish 'no drift' from 'not measured'"
        )
    if head is None:
        return "could not resolve the migration-script head revision from src/migrations/"
    if stamped != head:
        return (
            f"target database is not at head (stamped {stamped}, head {head}) — a diff "
            f"here would report pending migrations, not model/migration drift"
        )
    return None


def format_unexpected_diff( diff, database_url ):
    """
    Render a failure message that names what drifted and what to do about it.

    A drift report reading only "diff was not empty" reproduces the diagnosis
    cost the detector exists to remove.

    Requires:
        - diff is the list returned by compare_metadata()

    Ensures:
        - returns a multi-line string with one line per diff entry, nested
          modify-groups flattened

    Args:
        diff:         the non-empty compare_metadata() diff
        database_url: the URL compared against (host/db portion is echoed)

    Returns:
        str
    """
    entries = []
    for item in diff:
        entries.extend( item if isinstance( item, list ) else [ item ] )

    lines = [
        "",
        "ORM metadata does not match the migration-built schema.",
        f"  database : {database_url.split( '@' )[ -1 ]}",
        f"  entries  : {len( entries )}",
        "",
    ]
    lines += [ f"    - {entry[ 0 ]}: {entry[ 1: ]}" for entry in entries ]
    lines += [
        "",
        "Remedy: write the missing/corrective Alembic migration, or fix the model.",
        "Do NOT filter this assertion by operation class and do NOT add an allowlist —",
        "that rebuilds the hand-maintained twin this detector exists to replace.",
        "",
    ]
    return "\n".join( lines )


def copy_metadata( metadata ):
    """
    Deep-copy a MetaData so a control can mutate it without touching the real one.

    Mutating at RUNTIME rather than editing the tree is what keeps the controls
    from becoming a change someone has to remember to revert.

    Ensures:
        - returns a new MetaData carrying an independent copy of every table
        - the source metadata is unmodified

    Args:
        metadata: the MetaData to copy

    Returns:
        sqlalchemy.MetaData
    """
    copied = MetaData()
    for table in metadata.tables.values():
        table.to_metadata( copied )
    return copied


def diff_kinds( diff ):
    """
    Flatten a compare_metadata() diff to a list of ( op, table, name ) triples.

    Ensures:
        - returns one triple per operation, with nested modify-groups flattened
        - table/name degrade to None when an entry does not carry them

    Args:
        diff: a compare_metadata() diff list

    Returns:
        list[tuple]
    """
    entries = []
    for item in diff:
        entries.extend( item if isinstance( item, list ) else [ item ] )

    triples = []
    for entry in entries:
        table = entry[ 2 ] if len( entry ) > 2 else None
        name  = entry[ 3 ] if len( entry ) > 3 else None
        triples.append( ( entry[ 0 ], table, getattr( name, "name", name ) ) )
    return triples


@pytest.fixture( scope="module" )
def migration_built_connection():
    """
    An open, read-only connection to a migration-built database at head.

    SKIPS (never fails) when the database is unreachable or not at head — see
    the module docstring's "SKIP, never fail" section for why that is the
    contract and not a convenience.
    """
    database_url = resolve_migration_built_database_url()
    engine       = create_engine( database_url )

    try:
        connection = engine.connect()
    except SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip( f"target database unreachable ({type( exc ).__name__}) — drift not measured" )

    try:
        reason = precondition_failure( read_stamped_revision( connection ), read_script_head() )
        if reason is not None:
            pytest.skip( reason )
        yield connection
    finally:
        connection.close()
        engine.dispose()


# ══════════════════════════════════════════════════════════════════════════════
# THE ASSERTION
# ══════════════════════════════════════════════════════════════════════════════

def test_orm_metadata_matches_migration_built_schema( migration_built_connection ):
    """
    The whole of Half 2: the ORM metadata and the migration-built schema agree.

    Strictly empty diff. No operation-class filtering, no allowlist — see the
    module docstring for why widening this is the one repair that is forbidden.
    """
    diff = compare_metadata( MigrationContext.configure( migration_built_connection ), Base.metadata )

    assert diff == [], format_unexpected_diff( diff, str( migration_built_connection.engine.url ) )


# ══════════════════════════════════════════════════════════════════════════════
# CONTROLS — a detector that has never gone red is indistinguishable from one
# that cannot. These run against the same connection as the assertion above, so
# a green assertion is only trusted when these are simultaneously red.
# ══════════════════════════════════════════════════════════════════════════════

def test_control_a_detects_mapped_column_absent_from_database( migration_built_connection ):
    """
    CONTROL A — a mapped column present in NO migration and NO database fires.

    This is the target defect class in miniature. If this ever goes green, the
    empty diff above means the instrument is disconnected, not that the schema
    is clean.
    """
    probe = copy_metadata( Base.metadata )
    probe.tables[ INCIDENT_TABLE ].append_column( Column( SYNTHETIC_COLUMN, String( 16 ), nullable=True ) )

    diff = compare_metadata( MigrationContext.configure( migration_built_connection ), probe )

    assert ( "add_column", INCIDENT_TABLE, SYNTHETIC_COLUMN ) in diff_kinds( diff ), (
        "CONTROL A WENT GREEN: compare_metadata did not report a mapped column the "
        "database lacks. The empty-diff assertion in this file is therefore unaudited."
    )


def test_control_primary_shape_detects_the_real_incident_column( migration_built_connection ):
    """
    PRIMARY-shape control — the REAL column from the measured incident.

    ``task_items.park_reason_captured_at`` is what produced 12 live 500s on
    2026-07-19. A synthetic mutation proves the detector CAN fire; the real
    column proves it fires on the thing that actually happened.

    NAMED LIMIT (see module docstring gap 2): this drives the mismatch in the
    INVERTED direction — model lacking a column the DB has — because reproducing
    the true historical direction would require building a database at the
    pre-``d47487369407`` revision. This is not sold as the full PRIMARY control.
    """
    probe = copy_metadata( Base.metadata )
    table = probe.tables[ INCIDENT_TABLE ]
    table._columns.remove( table.c[ INCIDENT_COLUMN ] )

    diff = compare_metadata( MigrationContext.configure( migration_built_connection ), probe )

    assert ( "remove_column", INCIDENT_TABLE, INCIDENT_COLUMN ) in diff_kinds( diff ), (
        f"PRIMARY-shape CONTROL WENT GREEN: compare_metadata did not report a "
        f"mismatch on {INCIDENT_TABLE}.{INCIDENT_COLUMN}, the column behind the "
        f"measured incident. Treat the empty-diff assertion as unproven."
    )


def _vector_store_table_names():
    """
    The pgvector table names, derived from VECTOR_STORE_MODELS so this control
    self-updates when a 9th table is added rather than silently under-covering.
    """
    from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS
    return [ model.__tablename__ for model in VECTOR_STORE_MODELS ]


@pytest.mark.parametrize( "table_name", _vector_store_table_names() )
def test_control_vector_store_table_is_reached_by_the_comparison( migration_built_connection, table_name ):
    """
    SOLE-COVERAGE control — one per pgvector table.

    Migration d0e1f2a3b4c5 builds these with table.create( checkfirst=True ), so
    Half 1's AST parser cannot see them and, on an existing database, that
    migration adds nothing. This comparison is their only detector. Each table is
    therefore driven RED individually — a single aggregate control would let one
    table drop out of coverage without anything going red.
    """
    assert table_name in Base.metadata.tables, (
        f"{table_name} is not on postgres_models.Base — it is OUTSIDE this "
        f"detector's boundary and therefore has NO drift coverage at all."
    )

    probe = copy_metadata( Base.metadata )
    probe.tables[ table_name ].append_column( Column( SYNTHETIC_COLUMN, String( 16 ), nullable=True ) )

    diff = compare_metadata( MigrationContext.configure( migration_built_connection ), probe )

    assert ( "add_column", table_name, SYNTHETIC_COLUMN ) in diff_kinds( diff ), (
        f"CONTROL WENT GREEN for {table_name}: a mapped column the database lacks "
        f"was not reported. This table has no other detector — Half 1 cannot see it "
        f"(no DDL text) and d0e1f2a3b4c5 skips it on an existing DB (checkfirst=True)."
    )


def test_every_vector_store_table_exists_in_the_target_database( migration_built_connection ):
    """
    An empty diff must not be empty because the tables are simply absent from
    BOTH sides. That would be the emptiest possible green on exactly the tables
    that most need coverage.
    """
    from sqlalchemy import inspect as sa_inspect

    present = set( sa_inspect( migration_built_connection ).get_table_names() )
    missing = [ name for name in _vector_store_table_names() if name not in present ]

    assert not missing, (
        f"pgvector tables absent from the target database: {missing}. The empty-diff "
        f"assertion would be green for the wrong reason on these tables."
    )


# ══════════════════════════════════════════════════════════════════════════════
# The skip/precondition logic, exercised in both directions. These need no
# database — they are what keep the SKIP contract from being the untested half
# of this file.
# ══════════════════════════════════════════════════════════════════════════════

def test_precondition_passes_when_stamped_matches_head():
    assert precondition_failure( "d47487369407", "d47487369407" ) is None


def test_precondition_skips_when_database_is_unstamped():
    reason = precondition_failure( None, "d47487369407" )
    assert reason is not None and "no readable Alembic stamp" in reason


def test_precondition_skips_when_script_head_is_unresolvable():
    reason = precondition_failure( "d47487369407", None )
    assert reason is not None and "migration-script head" in reason


def test_precondition_skips_when_database_is_behind_head():
    reason = precondition_failure( "aaaaaaaaaaaa", "d47487369407" )
    assert reason is not None and "not at head" in reason
    assert "aaaaaaaaaaaa" in reason and "d47487369407" in reason


def test_url_override_wins_verbatim():
    url = resolve_migration_built_database_url( { URL_OVERRIDE_ENV: "postgresql://x/y" } )
    assert url == "postgresql://x/y"


def test_url_defaults_to_the_testing_database_and_ignores_shell_overrides( monkeypatch ):
    """
    A stray DATABASE_URL / DB_NAME / LUPIN_ENV in the shell must not retarget the
    comparison — that is what makes the assertion mean the same thing every run.
    """
    monkeypatch.setenv( "LUPIN_ENV", "development" )
    monkeypatch.setenv( "DATABASE_URL", "postgresql://should/not/win" )
    monkeypatch.setenv( "DB_NAME", "should_not_win" )
    monkeypatch.delenv( URL_OVERRIDE_ENV, raising=False )

    url = resolve_migration_built_database_url()

    assert "lupin_db_test" in url
    assert "should" not in url
    # patch.dict restored the caller's environment on the way out.
    assert os.environ[ "DATABASE_URL" ] == "postgresql://should/not/win"
    assert os.environ[ "LUPIN_ENV" ] == "development"


def test_read_stamped_revision_degrades_to_none_when_the_query_fails():
    """An unreadable revision must become a SKIP, never an exception."""
    class ExplodingConnection:
        def __getattr__( self, name ):
            raise SQLAlchemyError( "connection is gone" )

    assert read_stamped_revision( ExplodingConnection() ) is None


def test_read_script_head_resolves_from_the_real_migrations_directory():
    head = read_script_head()
    assert head is not None and len( head ) > 0


def test_format_unexpected_diff_names_entries_and_forbids_widening():
    diff = [
        ( "add_column", None, "task_items", Column( "x", String( 8 ) ) ),
        [ ( "modify_type", None, "notifications", "progress_group_id", {}, "VARCHAR(12)", "VARCHAR(24)" ) ],
    ]
    text = format_unexpected_diff( diff, "postgresql://u:p@host:5432/lupin_db_test" )

    assert "entries  : 2" in text
    assert "add_column" in text and "modify_type" in text
    assert "host:5432/lupin_db_test" in text
    assert "u:p" not in text
    assert "allowlist" in text


def test_diff_kinds_flattens_nested_modify_groups():
    diff = [
        ( "add_table", MetaData() ),
        ( "add_column", None, "task_items", Column( "x", String( 8 ) ) ),
        [ ( "modify_type", None, "notifications", "progress_group_id", {}, "a", "b" ) ],
    ]
    kinds = diff_kinds( diff )

    assert ( "add_column", "task_items", "x" ) in kinds
    assert ( "modify_type", "notifications", "progress_group_id" ) in kinds
    assert kinds[ 0 ][ 0 ] == "add_table"


def test_copy_metadata_leaves_the_real_metadata_untouched():
    """The controls mutate a copy; a leak here would corrupt every later test."""
    probe = copy_metadata( Base.metadata )
    probe.tables[ INCIDENT_TABLE ].append_column( Column( "leak_probe", String( 4 ) ) )

    assert "leak_probe" in probe.tables[ INCIDENT_TABLE ].c
    assert "leak_probe" not in Base.metadata.tables[ INCIDENT_TABLE ].c
