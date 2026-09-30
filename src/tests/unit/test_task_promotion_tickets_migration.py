"""
DB-free structural guards for migration 8d404f635e84 (add task_promotion_tickets),
stage 1 of the asynchronous promotion approval design
(src/rnd/v0.2.1/2026.09.06-asynchronous-promotion-approval-and-its-observable-
resolution.md, row 3493ae9b).

These read the migration script + the ORM model directly — NO Postgres — so they run
in the :7999 unit bucket by the venue rubric: no persistent-state mutation, well under
two minutes, no monopoly.

🔴 WHY PARITY IS THE POINT OF THIS FILE, AND NOT A FORMALITY. A fresh/empty database is
built by `Base.metadata.create_all` and a migrated one is built by this revision's DDL.
Those are TWO RECORDS OF ONE FACT. Let the two CHECK literals drift and the same named
constraint silently means different things depending on how the database was born —
and the divergence is invisible until a row violates one and not the other. The I3
chase CHECK carries the identical warning in this tree for the identical reason; this
follows its guard file deliberately rather than inventing a second shape.

⚠️ WHAT THIS FILE DOES NOT PROVE, said here so a green is not read as more than it is:
nothing below EXECUTES any DDL. It does not show the table can be created, that the
constraints are accepted by Postgres, or that up→down→up round-trips. Those need a live
database and belong in the :8000 tier. This proves the migration and the model AGREE,
and that the revision chains — which is exactly the class of defect that ships silently.

⚠️ AND NOTHING WRITES TO THIS TABLE YET. Stage 1 adds the surface only; the writer
arrives with the 202 in stage 2, which does not land before stage 3's sweeper exists.
A reader finding no producer has found the design, not an omission.
"""
import importlib.util

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION      = "8d404f635e84"
_DOWN_REVISION = "47513717b7e5"
_TABLE         = "task_promotion_tickets"

_CHECK_RESOLVED = "ck_task_promotion_tickets_resolved_has_timestamp"
_CHECK_REFUSED  = "ck_task_promotion_tickets_refused_has_reason"

_INDEXES = ( "idx_task_promotion_tickets_item_id",
             "idx_task_promotion_tickets_state_resolves_by" )


def _script_dir():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _migration_module():
    """Import the migration script as a module so its constants are readable."""
    path   = _script_dir().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "promotion_tickets_migration", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _model_table():
    from cosa.rest.postgres_models import TaskPromotionTicket
    return TaskPromotionTicket.__table__


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
# Chain integrity
# ---------------------------------------------------------------------------

def test_revision_present_and_chains_onto_prior_head():
    """
    The revision exists and names the head it was written against.

    A migration whose down_revision drifts does not fail loudly — it forks the chain,
    and alembic then reports two heads and refuses to upgrade.
    """
    rev = _script_dir().get_revision( _REVISION )

    assert rev is not None, f"revision {_REVISION} is not in the script directory"
    assert rev.down_revision == _DOWN_REVISION, (
        f"revision {_REVISION} chains onto {rev.down_revision!r}, not {_DOWN_REVISION!r} "
        f"— the chain has been re-pointed and this guard is stale, or the migration is"
    )


def test_the_chain_still_has_exactly_one_head():
    """
    Adding this revision must not FORK the chain.

    ⚠️ This is the assertion that catches a merge landing two migrations against the
    same parent — the failure mode a reader cannot see by looking at either file alone,
    because each is individually correct.
    """
    heads = _script_dir().get_heads()

    assert len( heads ) == 1, (
        f"the migration chain has {len( heads )} heads {heads} — two revisions share a "
        f"parent, and alembic will refuse to upgrade until they are merged"
    )
    # 🔴 CHANGED 2026-09-07 (row 0107c19e) FROM `heads[ 0 ] == _REVISION`.
    #
    # That equality made this guard go stale on EVERY subsequent migration — its own
    # failure message said so: "a newer revision has landed on top, WHICH IS FINE, but
    # this guard's constant needs updating". A guard that reddens on a legitimate,
    # expected event is a guard people learn to edit rather than read, and the next one
    # to land (9a1c4f27bd30, the P5 default) is exactly that event.
    #
    # ⚠️ THE FORK CHECK ABOVE IS THE VALUABLE HALF AND IS UNTOUCHED. `len( heads ) == 1`
    # is what catches two migrations sharing a parent — the failure a reader cannot see
    # by looking at either file alone. What is replaced is only the claim that THIS
    # revision is the newest one, which was never the property worth asserting.
    #
    # What replaces it is the property that actually matters and does NOT decay: this
    # revision must still be ON the chain that leads to head. A revision dropped from
    # the chain, or re-pointed onto a different parent, still fails here.
    chain = set()
    node  = _script_dir().get_revision( heads[ 0 ] )
    while node is not None:
        chain.add( node.revision )
        node = _script_dir().get_revision( node.down_revision ) if node.down_revision else None

    assert _REVISION in chain, (
        f"revision {_REVISION!r} is NOT an ancestor of head {heads[ 0 ]!r} — it has been "
        f"dropped from the chain or re-pointed onto a different parent. The chain from "
        f"head holds {len( chain )} revisions."
    )


# ---------------------------------------------------------------------------
# AC1 parity — the migration and the model must say the SAME thing
# ---------------------------------------------------------------------------

def test_the_resolved_check_literal_matches_the_model_verbatim():
    """
    `state = 'pending' OR resolved_at IS NOT NULL`, identical on both sides.

    VERBATIM and not merely equivalent: a whitespace-insensitive or semantic comparison
    would let the two drift into forms that mean the same thing today and diverge under
    the next edit. The whole point is that there is one string, written twice.
    """
    assert _migration_module().CHECK_RESOLVED_CONDITION == _model_check_literal( _CHECK_RESOLVED )


def test_the_refused_check_literal_matches_the_model_verbatim():
    """`state != 'refused' OR refusal IS NOT NULL`, identical on both sides."""
    assert _migration_module().CHECK_REFUSED_CONDITION == _model_check_literal( _CHECK_REFUSED )


def test_the_constraint_NAMES_match_too_not_only_their_bodies():
    """
    Matching literals under DIFFERENT names would still be two different constraints.

    ⚠️ This is a separate claim from the two above and it is not pedantry: a constraint
    is identified to Postgres by its name, so `create_all` and the migration producing
    identical predicates under different names yields a database carrying BOTH, and a
    downgrade that drops only one.
    """
    module      = _migration_module()
    model_names = { getattr( c, "name", None ) for c in _model_table().constraints }

    assert module.CHECK_RESOLVED_NAME == _CHECK_RESOLVED
    assert module.CHECK_REFUSED_NAME  == _CHECK_REFUSED
    assert _CHECK_RESOLVED in model_names, f"model is missing {_CHECK_RESOLVED}"
    assert _CHECK_REFUSED  in model_names, f"model is missing {_CHECK_REFUSED}"


def test_the_table_name_and_indexes_match_the_model():
    """
    The migration builds the table the model expects, under the names the model uses.

    An index named differently on the two paths is not a correctness bug on day one —
    it is a `drop_index` that fails on a database built the other way, which surfaces
    only during a downgrade, which is the worst possible moment to find it.
    """
    module = _migration_module()
    table  = _model_table()

    assert module.TABLE_NAME == _TABLE == table.name

    model_indexes = { index.name for index in table.indexes }
    assert model_indexes == set( _INDEXES ), (
        f"model indexes {sorted( model_indexes )} != expected {sorted( _INDEXES )}"
    )
    assert { module.INDEX_ITEM_ID, module.INDEX_STATE_BY } == set( _INDEXES )


# ---------------------------------------------------------------------------
# The downgrade is not a stub
# ---------------------------------------------------------------------------

def test_downgrade_drops_the_table_rather_than_passing():
    """
    A `downgrade()` that quietly does nothing is worse than one that raises: the
    operator is told the downgrade succeeded and the table is still there.

    ⚠️ Read as a SOURCE-TEXT check and nothing more. It does not execute the DDL, so it
    cannot show the drop works — only that a drop is written. The empirical round-trip
    needs a live database and is not in this tier.
    """
    import inspect as _inspect

    source = _inspect.getsource( _migration_module().downgrade )

    assert "op.drop_table" in source, (
        "downgrade() does not drop the table — a no-op downgrade reports success and "
        "leaves the schema exactly as it was"
    )
    assert "op.drop_index" in source, "downgrade() does not drop its indexes by name"


def test_upgrade_is_guarded_so_a_re_run_is_a_no_op():
    """
    The auto-migrate startup path can reach this on an already-migrated database, and
    the test DB is built from metadata rather than from migrations — so `create_all`
    may have created the table before this revision ever runs.

    Without the guard that is a hard failure on a perfectly healthy database.
    """
    import inspect as _inspect

    source = _inspect.getsource( _migration_module().upgrade )

    assert "_table_exists" in source and "return" in source, (
        "upgrade() is not guarded against an already-present table — it will raise on "
        "a database built from metadata, which is how the test database is built"
    )
