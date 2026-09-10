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
from alembic.script import ScriptDirectory

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
