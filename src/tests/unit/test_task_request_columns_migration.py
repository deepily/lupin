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
