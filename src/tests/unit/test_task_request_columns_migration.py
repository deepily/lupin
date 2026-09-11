"""
MIGRATION 8beada291153 AND THE MODEL MUST SAY THE SAME THING ABOUT THE REQUEST TRIO.

Row c9fafb9d, rules 3 and 4. The migration adds `request_state` / `request_move` /
`request_ts` to `task_items` plus three CHECKs; `postgres_models.TaskItem` declares the
same three columns and the same three CHECKs.

🔴 WHY THIS FILE EXISTS AT ALL, AND IT IS NOT BOILERPLATE. When the columns were written,
both the model and the migration carried a comment saying "a parity test asserts it". No
such test existed for these constraints — the parity guards in this tree are PER-MIGRATION
(`test_i3_kind_aware_chase_migration.py`, `test_task_promotion_tickets_migration.py`), and
a new migration inherits none of them.

⇒ That comment was a WRONG REASSURANCE, which is the worse half of the pair: a wrong
  INSTRUCTION gets caught the first time somebody follows it, while a wrong reassurance
  disarms the reader who would otherwise have checked. It was written and then made true,
  in that order, and this note records the order rather than tidying it away.

🔴 WHAT THIS FILE DOES AND DOES NOT PROVE — read this before quoting a green from it.
Mr. Radio asked for the limits in the docstring (2026-09-09 ~20:08), and they are three:

  PROVEN, on a real SQL engine:
    · the migration's `upgrade()` really ADDS the three columns to a table that already
      has rows in it, and those rows come out with `request_state` NULL (the no-backfill
      claim, measured rather than argued)
    · the three CHECK PREDICATES are EFFECTIVE — a table built from the MODEL'S OWN
      literal strings accepts a complete request and a no-request row, and REJECTS an
      unruled state, a request with no move, and a request with no timestamp
    · the migration and the model carry byte-identical predicates, and the chain is intact

  ALSO PROVEN, on REAL POSTGRES (added after Mr. Radio pointed out that a SQLite green is
  evidence about SQLite and a presumption about Postgres):
    · the same five shapes behave IDENTICALLY on the engine that enforces them in
      production — legal request and no-request accepted, unruled state and missing move
      and missing timestamp all refused. A rolled-back TEMP table, so nothing persists.
      It SKIPS LOUDLY, naming what goes unproven, when no database answers.

  NOT PROVEN, and each is a named gap rather than a silent one:
    · THAT THE MIGRATION'S OWN DDL ATTACHES THEM. What is proven above is that the
      PREDICATES work on Postgres; the arms build their own table. The migration's
      `op.create_check_constraint` step raises on SQLite and is exercised on no backend
      here, so "these rules work on Postgres" and "this migration installs them on
      Postgres" remain two claims and only the first has a receipt.
    · THAT THE LIVE STORE HAS BEEN MIGRATED. It had not been when this was written.
      `auto_migrate.run_migrations_to_head` applies it on the next process start.
    · anything about the DOORS. That is
      `test_the_request_queue_doors_are_operator_only.py`.

⚠️ AND ONE CORRECTION TO A PLAUSIBLE-SOUNDING CLAIM, because it changed what was testable:
"SQLite does not enforce CHECK constraints" is FALSE, and believing it would have left the
effectiveness arms unwritten. SQLite enforces a CHECK perfectly well when it is part of
CREATE TABLE — measured. What it cannot do is ALTER TABLE ADD CONSTRAINT, which is a
statement about DDL, not about enforcement. The distinction is the whole reason the
effectiveness arms below exist and pass.

WHAT A DIVERGENCE WOULD ACTUALLY DO, since "keep them in sync" is not a reason:
the test DB is built from `Base.metadata.create_all` and a deployed DB is built by
migrations. Let the two strings drift and the SAME constraint name means two different
predicates depending on how the database was made — green in CI, refusing real rows in
production, with nothing in either file looking wrong on its own.
"""
import importlib.util
import os
import sys

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION      = "8beada291153"
_DOWN_REVISION = "9a1c4f27bd30"
_TABLE         = "task_items"

_COLUMNS = ( "request_state", "request_move", "request_ts" )

_CHECKS = ( "ck_task_items_request_state_is_ruled",
            "ck_task_items_request_requires_move",
            "ck_task_items_request_requires_ts" )


def _script_dir():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _migration_module():
    """Import the migration script as a module so its constants are readable."""
    path   = _script_dir().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "task_request_columns_migration", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _model_table():
    from cosa.rest.postgres_models import TaskItem
    return TaskItem.__table__


def _model_check_literal( name ):
    """The named CheckConstraint literal on the live ORM model."""
    for constraint in _model_table().constraints:
        if getattr( constraint, "name", None ) == name:
            return str( constraint.sqltext )
    raise AssertionError(
        f"the model has no CheckConstraint named {name!r} — either it was renamed or "
        f"dropped, and this guard is now describing a constraint that is not there"
    )


# ---------------------------------------------------------------------------
# THE POSITIVE CONTROL FIRST — a helper that finds nothing passes everything
# ---------------------------------------------------------------------------

def test_the_helpers_can_find_a_constraint_that_is_really_there():
    """
    🔴 WITHOUT THIS, A BROKEN `_model_check_literal` COULD MAKE EVERY PARITY ARM VACUOUS.
    It raises on a miss today, but a future edit that returned None instead would turn
    `None == None` into a passing comparison for two constraints that do not exist.

    So: prove the lookup returns a NON-EMPTY literal for a constraint this file does not
    own — one that predates it and is maintained by somebody else's guard.
    """
    unrelated = _model_check_literal( "ck_task_items_parked_requires_reason" )
    assert unrelated and "park_reason" in unrelated, (
        "the model lookup no longer returns a real predicate, so every parity arm below "
        "is comparing nothing to nothing"
    )


def test_the_migration_module_actually_loaded_its_constants():
    """The other half of the same control — the migration side must be real too."""
    module = _migration_module()
    assert module.revision == _REVISION
    assert len( module.CHECKS ) == len( _CHECKS )
    assert len( module.NEW_COLUMNS ) == len( _COLUMNS )


# ---------------------------------------------------------------------------
# Chain integrity
# ---------------------------------------------------------------------------

def test_revision_exists_and_names_the_head_it_was_written_against():
    """
    A drifting `down_revision` does not fail loudly — it FORKS the chain, and alembic then
    reports two heads and refuses to upgrade at all.
    """
    rev = _script_dir().get_revision( _REVISION )
    assert rev is not None
    assert rev.down_revision == _DOWN_REVISION


def test_the_revision_is_still_an_ancestor_of_head():
    """
    NOT "this is the newest revision" — that claim decays the moment anyone adds one, and
    it was never the property worth asserting. This one does not decay: the revision must
    remain ON the chain that leads to head. Dropped or re-pointed, it fails here.
    """
    script = _script_dir()
    heads  = list( script.get_heads() )
    assert len( heads ) == 1, f"the chain has {len( heads )} heads: {heads!r} — it forked"

    chain, node = set(), script.get_revision( heads[ 0 ] )
    while node is not None:
        chain.add( node.revision )
        node = script.get_revision( node.down_revision ) if node.down_revision else None

    assert _REVISION in chain, (
        f"revision {_REVISION!r} is NOT an ancestor of head {heads[ 0 ]!r} — it was dropped "
        f"from the chain or re-pointed onto a different parent. The chain from head holds "
        f"{len( chain )} revisions."
    )


# ---------------------------------------------------------------------------
# PARITY — the migration and the model must say the SAME thing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "name", _CHECKS )
def test_each_check_literal_matches_the_model_VERBATIM( name ):
    """
    VERBATIM, not merely equivalent.

    A whitespace-insensitive or semantic comparison would let the two drift into forms
    that mean the same thing today and diverge under the next edit. The whole point is
    that there is ONE string, written twice, and the guard's job is to notice the second
    copy changing.
    """
    conditions = dict( _migration_module().CHECKS )
    assert name in conditions, f"the migration no longer declares a CHECK named {name!r}"
    assert conditions[ name ] == _model_check_literal( name ), (
        f"{name}: the migration predicate and the model CheckConstraint have DIVERGED. A "
        f"metadata-built DB and a migrated DB would then enforce two different rules under "
        f"one name."
    )


@pytest.mark.parametrize( "name", _COLUMNS )
def test_each_request_column_exists_on_BOTH_sides( name ):
    """
    The columns themselves, not only their constraints. A CHECK whose column the model
    dropped is a constraint about nothing, and it would still match verbatim.
    """
    assert name in _model_table().columns, f"the model has no column {name!r}"
    assert name in dict( _migration_module().NEW_COLUMNS ), (
        f"the migration no longer adds column {name!r}"
    )


@pytest.mark.parametrize( "name", _COLUMNS )
def test_every_request_column_is_NULLABLE_which_is_what_makes_the_backfill_unnecessary( name ):
    """
    🔴 THE MIGRATION'S "NO BACKFILL NEEDED" CLAIM RESTS ENTIRELY ON THIS, so it is checked
    rather than trusted.

    Every CHECK reads `request_state IS NULL OR ...`, so an existing row satisfies all
    three vacuously — but only because adding a nullable column leaves it NULL everywhere.
    Make any of these NOT NULL and pre-existing rows need a value nobody has, which is the
    fabricated-timestamp problem `d47487369407` had to label and live with.
    """
    assert _model_table().columns[ name ].nullable, (
        f"{name} is NOT NULL on the model. The migration adds it to a live table without a "
        f"backfill, which is only safe while it is nullable."
    )


def test_the_three_checks_are_SEPARATE_and_not_one_conjunction():
    """
    Three constraints, three names, so a violation says WHICH field is wrong.

    Same convention as the `parked` pair already on this table. One conjunction would
    report "the request constraint failed" and leave the reader to bisect three fields by
    hand — and this table already chose the other way twice.
    """
    model_names = { getattr( c, "name", None ) for c in _model_table().constraints }
    for name in _CHECKS:
        assert name in model_names, f"the model lost CHECK {name!r}"
    assert len( set( _CHECKS ) ) == 3, "the three CHECKs collapsed into fewer names"


# ---------------------------------------------------------------------------
# THE REAL UPGRADE — driven, not read
#
# 🔴 MR. RADIO ASKED THE RIGHT QUESTION (2026-09-09 ~20:04): was this migration APPLIED,
# or only written and tested structurally? Every arm above is a STRUCTURAL READ — it
# imports the module and compares constants, and would pass just as well on a migration
# whose `upgrade()` raised on the first line.
#
# So these arms execute it. The precedent is `test_migration_add_urgency_column.py`:
# an in-memory SQLite engine with an alembic `Operations` bound to it.
#
# ⚠️ AND THE FIRST THING THIS FOUND IS A LIMIT WORTH NAMING RATHER THAN HIDING. On SQLite,
# `op.create_check_constraint` raises NotImplementedError — "No support for ALTER of
# constraints in SQLite dialect". So `upgrade()` gets the COLUMNS in and then dies at the
# constraint step. That is NOT novel to this revision: `d47487369407` calls the same op,
# and production is Postgres while the test DB is built from `Base.metadata.create_all`
# rather than from migrations, so no migration ever runs on SQLite in practice.
# ⇒ What these arms therefore prove is the COLUMN half and the NO-BACKFILL claim, on real
#   rows. The CHECK half stays proven only structurally, and saying so is the point — an
#   unnamed gap is the one nobody closes.
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_task_items( monkeypatch ):
    """
    A scratch `task_items` with TWO pre-existing rows, and the migration bound to it.

    The rows matter: an upgrade driven against an EMPTY table cannot tell a migration that
    leaves existing rows alone from one that has no existing rows to leave alone.
    """
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    connection.execute( text(
        "CREATE TABLE task_items ( id TEXT PRIMARY KEY, status TEXT, updated_ts TEXT )" ) )
    connection.execute( text(
        "INSERT INTO task_items VALUES ( 'a', 'queued', 'x' ), ( 'b', 'not_approved', 'y' )" ) )
    connection.commit()

    module = _migration_module()
    monkeypatch.setattr( module, "op", Operations( MigrationContext.configure( connection ) ) )

    yield module, connection
    connection.close()


def _sqlite_columns( connection ):
    return { c[ "name" ] for c in inspect( connection ).get_columns( "task_items" ) }


def test_the_upgrade_really_ADDS_the_three_columns_to_a_live_table( sqlite_task_items ):
    """
    Driven, not read. The columns must exist on a table that already had rows in it.

    The CHECK step raises on SQLite (see the block comment), so the exception is caught
    HERE rather than allowed to fail the arm — what is under test on this backend is the
    column half, and pretending otherwise would make this a test of SQLite's DDL support.
    """
    module, connection = sqlite_task_items
    assert not ( _sqlite_columns( connection ) & set( _COLUMNS ) ), "the fixture started dirty"

    with pytest.raises( NotImplementedError, match="ALTER of constraints in SQLite" ):
        module.upgrade()

    assert set( _COLUMNS ) <= _sqlite_columns( connection ), (
        "the upgrade did not add the request columns before it reached the constraint step"
    )


def test_PRE_EXISTING_rows_survive_the_upgrade_with_a_NULL_request_state( sqlite_task_items ):
    """
    🔴 THE NO-BACKFILL CLAIM, MEASURED ON ROWS INSTEAD OF ARGUED FROM THE SCHEMA.

    The migration's docstring reasons that adding a nullable column leaves it NULL
    everywhere, so every `request_state IS NULL OR ...` CHECK holds vacuously and nothing
    needs stamping. That is a mechanism. This is its receipt — and the two are different
    claims, which is exactly the distinction `d47487369407` had to learn when it discovered
    it DID need to fabricate a value.

    Both rows must still be there. A migration that dropped and recreated the table would
    satisfy a NULL check on zero rows.
    """
    module, connection = sqlite_task_items
    with pytest.raises( NotImplementedError ):
        module.upgrade()

    surviving = connection.execute( text( "SELECT count(*) FROM task_items" ) ).scalar()
    assert surviving == 2, f"the upgrade lost rows: {surviving} of 2 survived"

    states = connection.execute( text( "SELECT DISTINCT request_state FROM task_items" ) ).fetchall()
    assert states == [ ( None, ) ], (
        f"pre-existing rows came out of the upgrade with {states!r} rather than NULL — the "
        f"no-backfill argument does not hold and something wrote a value nobody measured"
    )


def test_re_running_the_column_step_is_a_NO_OP_and_does_not_raise( sqlite_task_items ):
    """
    The idempotence claim, for the half this backend can drive.

    The auto-migrate path runs `upgrade head` on every process start, so a second pass over
    an already-migrated DB is the NORMAL case rather than an edge one. A migration that
    raised "column already exists" would take the server down on its second boot.
    """
    module, connection = sqlite_task_items
    for _ in range( 2 ):
        with pytest.raises( NotImplementedError ):
            module.upgrade()

    assert set( _COLUMNS ) <= _sqlite_columns( connection )
    assert connection.execute( text( "SELECT count(*) FROM task_items" ) ).scalar() == 2


def test_the_upgrade_is_a_NO_OP_when_task_items_does_not_exist():
    """
    The guard branch, which is not decoration: a fresh DB is built from
    `Base.metadata.create_all` and then stamped, so this migration can legitimately meet a
    database with no `task_items` at all and must return quietly rather than raise.
    """
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    module     = _migration_module()
    module.op  = Operations( MigrationContext.configure( connection ) )

    module.upgrade()      # must not raise
    module.downgrade()    # and neither must the reverse

    assert "task_items" not in inspect( connection ).get_table_names()
    connection.close()


# ---------------------------------------------------------------------------
# ARE THE PREDICATES EFFECTIVE? — a constraint that matches verbatim and rejects
# nothing is a string, not a rule
#
# 🔴 EVERY ARM ABOVE COMPARES OR INSPECTS. None of them puts a bad row in front of the
# rules and watches them refuse it, and that is the gap Mr. Radio pointed at.
#
# The real `task_items` cannot be built on SQLite — `blocked_by` is JSONB and the SQLite
# compiler will not render it. So these arms build a MINIMAL table carrying the three
# request columns and the model's OWN literal predicates, read out of the live
# CheckConstraint objects rather than retyped here. Retyping them would make this a test
# of what the author believed the rule was.
# ---------------------------------------------------------------------------

@pytest.fixture
def predicate_probe():
    """A table whose only constraints are the three real predicates, on a real engine."""
    clauses = ", ".join(
        f"CONSTRAINT {name} CHECK ( {_model_check_literal( name )} )" for name in _CHECKS )
    engine     = create_engine( "sqlite://" )
    connection = engine.connect()
    connection.execute( text(
        f"CREATE TABLE probe ( id TEXT, request_state TEXT, request_move TEXT, "
        f"request_ts TEXT, {clauses} )" ) )
    connection.commit()
    yield connection
    connection.close()


def _insert( connection, state, move, ts ):
    """Try one row. Returns True if the constraints ACCEPTED it."""
    def sql( v ): return "NULL" if v is None else f"'{v}'"
    try:
        connection.execute( text(
            f"INSERT INTO probe VALUES ( 'x', {sql( state )}, {sql( move )}, {sql( ts )} )" ) )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        return False


@pytest.mark.parametrize( "label,state,move,ts", [
    ( "no request at all",     None,      None,    None ),
    ( "a complete request",    "pending", "admit", "2026-09-09T00:00:00Z" ),
] )
def test_the_predicates_ACCEPT_what_they_should( predicate_probe, label, state, move, ts ):
    """
    🔴 THE POSITIVE HALF, AND IT IS NOT A FORMALITY. Three constraints that rejected
    EVERYTHING would satisfy every rejection arm below, and a store where no request can
    ever be written is a worse outcome than one where a malformed request can.

    The no-request row is the load-bearing one: `request_state IS NULL` is what every
    pre-existing row in the table looks like, so a predicate that refused it would break
    every write to every row that has nothing to do with requests.
    """
    assert _insert( predicate_probe, state, move, ts ), (
        f"the constraints REFUSED {label} — this shape must be writable"
    )


@pytest.mark.parametrize( "label,state,move,ts", [
    ( "an unruled request_state",   "banana",  "admit", "2026-09-09T00:00:00Z" ),
    ( "a request with NO move",     "pending", None,    "2026-09-09T00:00:00Z" ),
    ( "a request with NO timestamp","pending", "admit", None ),
] )
def test_the_predicates_REJECT_what_they_should( predicate_probe, label, state, move, ts ):
    """
    THE ALL-OR-NOTHING RULE, enforced below Pydantic — which is the point of putting it in
    the schema at all. A hand-written INSERT or a future non-ORM writer must not be able to
    create a request with no move or no date, because `badge_for_move` RAISES on a move it
    cannot classify and a half-written request would take the badge count down with it.

    Each shape is its own arm so a failure names WHICH rule stopped refusing — the same
    reason there are three constraints rather than one conjunction.
    """
    assert not _insert( predicate_probe, state, move, ts ), (
        f"the constraints ACCEPTED {label}. The predicate matches the model verbatim and "
        f"enforces nothing — a string, not a rule."
    )


# ---------------------------------------------------------------------------
# THE SAME PREDICATES ON REAL POSTGRES
#
# 🔴 WHY THIS EXISTS EVEN THOUGH THE SQLITE ARMS PASS. Production is Postgres, and the two
# engines are entitled to disagree — SQLite is famously permissive about types, so a
# predicate it enforces is evidence about SQLite and only a presumption about Postgres.
# Mr. Radio asked for the real thing if it was possible. It was.
#
# ⚠️ FOOTPRINT: a TEMP table, created inside a transaction that is ROLLED BACK, with
# ON COMMIT DROP as a second belt. Nothing is written to any real table and no DDL
# survives the connection. It reads the same store the fleet uses, so it is deliberately
# the smallest possible touch rather than a scratch database nobody asked me to create.
#
# ⚠️ AND IT SKIPS RATHER THAN FAILS when no database answers, because a unit tier must not
# go red on a developer laptop with no container running. The skip message NAMES what goes
# unproven — a silent skip would let the Postgres gap reopen without anybody noticing.
# ---------------------------------------------------------------------------

@pytest.fixture
def postgres_probe():
    """A rolled-back temp table on the real Postgres, or a loud skip."""
    from cosa.rest.db.auto_migrate import resolve_database_url

    try:
        engine     = create_engine( resolve_database_url(), connect_args={ "connect_timeout": 5 } )
        connection = engine.connect()
    except Exception as error:                      # pragma: no cover - environment-dependent
        pytest.skip(
            f"no Postgres reachable ({type( error ).__name__}), so the CHECK predicates are "
            f"proven on SQLite ONLY. The engine that actually runs them in production is "
            f"unexercised by this run."
        )

    transaction = connection.begin()
    clauses     = ", ".join(
        f"CONSTRAINT {name} CHECK ( {_model_check_literal( name )} )" for name in _CHECKS )
    connection.execute( text(
        f"CREATE TEMP TABLE probe ( id TEXT, request_state TEXT, request_move TEXT, "
        f"request_ts TIMESTAMPTZ, {clauses} ) ON COMMIT DROP" ) )

    yield connection

    transaction.rollback()
    connection.close()


def _pg_insert( connection, values ):
    """One row inside a SAVEPOINT, so a rejection does not poison the outer transaction."""
    savepoint = connection.begin_nested()
    try:
        connection.execute( text( f"INSERT INTO probe VALUES ( 'x', {values} )" ) )
        savepoint.commit()
        return True
    except Exception:
        savepoint.rollback()
        return False


@pytest.mark.parametrize( "label,values,accepted", [
    ( "no request at all",          "NULL, NULL, NULL",          True  ),
    ( "a complete request",         "'pending', 'admit', now()", True  ),
    ( "an unruled request_state",   "'banana', 'admit', now()",  False ),
    ( "a request with NO move",     "'pending', NULL, now()",    False ),
    ( "a request with NO timestamp","'pending', 'admit', NULL",  False ),
] )
def test_POSTGRES_agrees_with_sqlite_about_every_shape( postgres_probe, label, values, accepted ):
    """
    The engine that actually enforces these in production, asked directly.

    Both directions in one parametrize on purpose: if only the rejections were checked here,
    a Postgres-specific quirk that refused a legal request would pass this file and break
    every write in the store.
    """
    assert _pg_insert( postgres_probe, values ) is accepted, (
        f"POSTGRES disagrees with SQLite about {label} — the predicate behaves differently "
        f"on the engine that actually runs it"
    )
