"""
MIGRATION 525a4ad4067a AND THE MODEL MUST SAY THE SAME THING ABOUT `answer_by` — row dbe42964.

The migration adds `task_promotion_tickets.answer_by` and the CHECK
`ck_task_promotion_tickets_answer_by_before_resolves_by`; `postgres_models.TaskPromotionTicket`
declares both. Parity guards in this tree are per-migration, so this revision inherits none.

WHAT THIS FILE PROVES
  · the revision chains onto 8beada291153 and the chain still has one head
  · the CHECK name and literal are byte-identical on the model and the migration
  · the upgrade's control flow: the column step and the CHECK step are guarded
    INDEPENDENTLY (Mr. Radio's condition, 2026-09-10 20:08 — a DB built by `create_all`
    with the column but not the CHECK must still get the CHECK), a violating row refuses
    the CHECK, and the downgrade drops the CHECK before the column
  · the CHECK predicate is effective on REAL POSTGRES, in a rolled-back TEMP table

WHAT IT DOES NOT PROVE
  · that the migration's DDL runs on Postgres. The control-flow arms drive the real
    `upgrade()` / `downgrade()` over a recording `op` and a stateful fake inspector. The
    DDL itself is proven by the scratch-database rehearsal,
    `src/rnd/2026.09.10-migration-525a4ad4067a-scratch-rehearsal.md`.
"""
import importlib.util

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION      = "525a4ad4067a"
_DOWN_REVISION = "8beada291153"
_TABLE         = "task_promotion_tickets"
_CHECK         = "ck_task_promotion_tickets_answer_by_before_resolves_by"


def _script_dir():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _migration_module():
    """Import the migration script as a module, fresh each call, so a monkeypatch never leaks."""
    path   = _script_dir().get_revision( _REVISION ).path
    spec   = importlib.util.spec_from_file_location( "answer_by_migration", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _model_table():
    from cosa.rest.postgres_models import TaskPromotionTicket
    return TaskPromotionTicket.__table__


def _model_check_literal( name ):
    for constraint in _model_table().constraints:
        if getattr( constraint, "name", None ) == name:
            return str( constraint.sqltext )
    raise AssertionError( f"the model has no CheckConstraint named {name!r}" )


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

def test_the_revision_chains_onto_the_request_columns_migration():
    rev = _script_dir().get_revision( _REVISION )
    assert rev is not None, f"revision {_REVISION} is not in the script directory"
    assert rev.down_revision == _DOWN_REVISION, (
        f"{_REVISION} chains onto {rev.down_revision!r}, not {_DOWN_REVISION!r}. Two revisions "
        f"sharing a parent is two heads, and `alembic upgrade head` fails at server start."
    )


def test_the_chain_has_exactly_one_head_and_this_revision_is_on_it():
    heads = _script_dir().get_heads()
    assert len( heads ) == 1, f"the migration chain has {len( heads )} heads: {heads}"

    chain = set()
    node  = _script_dir().get_revision( heads[ 0 ] )
    while node is not None:
        chain.add( node.revision )
        node = _script_dir().get_revision( node.down_revision ) if node.down_revision else None

    assert _REVISION in chain, f"{_REVISION} is not an ancestor of head {heads[ 0 ]}"
    assert _DOWN_REVISION in chain, "the parent fell off the chain"


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------

def test_the_helper_finds_a_constraint_that_is_really_there():
    """Without this, a broken `_model_check_literal` would make the parity arm vacuous."""
    assert "resolved_at IS NOT NULL" in _model_check_literal( "ck_task_promotion_tickets_resolved_has_timestamp" )


def test_the_check_literal_and_name_match_the_model_VERBATIM():
    module = _migration_module()
    assert module.CHECK_ANSWER_BY_NAME == _CHECK
    assert module.CHECK_ANSWER_BY_CONDITION == _model_check_literal( _CHECK )
    assert module.TABLE_NAME == _TABLE == _model_table().name


def test_the_column_is_nullable_timestamptz_on_the_model():
    """Nullable is what lets pre-existing tickets stay unbackfilled."""
    column = _model_table().columns[ "answer_by" ]
    assert column.nullable is True
    assert column.type.timezone is True


# ---------------------------------------------------------------------------
# Control flow of the real upgrade() / downgrade()
# ---------------------------------------------------------------------------

class _Schema:
    """The table as the fake inspector sees it. The fake `op` mutates it, so a re-inspect sees the change."""
    def __init__( self, table=True, column=False, check=False, violations=0 ):
        self.table      = table
        self.columns    = { "id", "resolves_by" } | ( { "answer_by" } if column else set() )
        self.checks     = { "ck_task_promotion_tickets_resolved_has_timestamp" } | ( { _CHECK } if check else set() )
        self.violations = violations
        self.calls      = []


class _Inspector:
    def __init__( self, schema ):          self.schema = schema
    def get_table_names( self ):           return [ _TABLE ] if self.schema.table else [ "task_items" ]
    def get_columns( self, table ):        return [ { "name": n } for n in sorted( self.schema.columns ) ]
    def get_check_constraints( self, t ):  return [ { "name": n } for n in sorted( self.schema.checks ) ]


class _Result:
    def __init__( self, value ): self.value = value
    def scalar( self ):          return self.value


class _Bind:
    def __init__( self, schema ): self.schema = schema
    def execute( self, statement ):
        sql = str( statement )
        self.schema.calls.append( ( "execute", sql ) )
        return _Result( self.schema.violations if "NOT (" in sql else 0 )


class _Op:
    def __init__( self, schema ):
        self.schema = schema
        self.bind   = _Bind( schema )
    def get_bind( self ):
        return self.bind
    def add_column( self, table, column ):
        self.schema.calls.append( ( "add_column", table, column.name ) )
        self.schema.columns.add( column.name )
    def create_check_constraint( self, name, table, condition ):
        self.schema.calls.append( ( "create_check_constraint", name, table, condition ) )
        self.schema.checks.add( name )
    def drop_constraint( self, name, table, type_ ):
        self.schema.calls.append( ( "drop_constraint", name, table, type_ ) )
        self.schema.checks.discard( name )
    def drop_column( self, table, name ):
        self.schema.calls.append( ( "drop_column", table, name ) )
        self.schema.columns.discard( name )


def _drive( schema, step ):
    module        = _migration_module()
    module.op     = _Op( schema )
    module.inspect = lambda bind: _Inspector( schema )
    getattr( module, step )()
    return [ c for c in schema.calls if c[ 0 ] != "execute" ], module


def test_a_fresh_table_gets_the_column_then_the_check():
    schema = _Schema()
    calls, module = _drive( schema, "upgrade" )
    assert calls == [
        ( "add_column", _TABLE, "answer_by" ),
        ( "create_check_constraint", _CHECK, _TABLE, module.CHECK_ANSWER_BY_CONDITION ),
    ]


def test_a_table_with_the_column_but_NOT_the_check_still_gets_the_check():
    """
    🔴 MR. RADIO'S CONDITION. A database `create_all` built from a model carrying the column
    but not yet the CHECK. "Column exists → return" would leave it unconstrained forever.
    """
    schema = _Schema( column=True, check=False )
    calls, _ = _drive( schema, "upgrade" )
    assert [ c[ 0 ] for c in calls ] == [ "create_check_constraint" ]


def test_a_fully_migrated_table_is_left_alone():
    """The normal case: `upgrade head` runs on every process start."""
    schema = _Schema( column=True, check=True )
    calls, _ = _drive( schema, "upgrade" )
    assert calls == []


def test_no_table_is_a_no_op_both_ways():
    for step in ( "upgrade", "downgrade" ):
        schema = _Schema( table=False )
        calls, _ = _drive( schema, step )
        assert calls == [], f"{step} touched a table that does not exist"


def test_a_row_that_already_breaks_the_check_stops_the_upgrade_before_the_check():
    schema = _Schema( column=True, violations=2 )
    with pytest.raises( RuntimeError, match="2 ticket\\(s\\).*answer_by later than resolves_by" ):
        _drive( schema, "upgrade" )
    assert _CHECK not in schema.checks, "a CHECK was created over rows that break it"


def test_the_violation_count_asks_the_rows_with_the_check_s_own_predicate():
    """The counting query must negate the SAME literal the CHECK installs, not a restatement."""
    schema = _Schema( column=True )
    _, module = _drive( schema, "upgrade" )
    queries = [ c[ 1 ] for c in schema.calls if c[ 0 ] == "execute" ]
    assert f"NOT ( {module.CHECK_ANSWER_BY_CONDITION} )" in " ".join( queries )


def test_the_downgrade_drops_the_check_BEFORE_the_column():
    schema = _Schema( column=True, check=True )
    calls, _ = _drive( schema, "downgrade" )
    assert calls == [
        ( "drop_constraint", _CHECK, _TABLE, "check" ),
        ( "drop_column", _TABLE, "answer_by" ),
    ]


def test_a_partial_upgrade_downgrades_cleanly():
    schema = _Schema( column=True, check=False )
    calls, _ = _drive( schema, "downgrade" )
    assert calls == [ ( "drop_column", _TABLE, "answer_by" ) ]


def test_downgrading_an_unmigrated_table_does_nothing():
    schema = _Schema( column=False, check=False )
    calls, _ = _drive( schema, "downgrade" )
    assert calls == []


# ---------------------------------------------------------------------------
# The predicate on real Postgres
# ---------------------------------------------------------------------------

@pytest.fixture
def postgres_probe():
    """A rolled-back TEMP table on the real Postgres, or a loud skip."""
    from cosa.rest.db.auto_migrate import resolve_database_url

    try:
        engine     = create_engine( resolve_database_url(), connect_args={ "connect_timeout": 5 } )
        connection = engine.connect()
    except Exception as error:                      # pragma: no cover - environment-dependent
        pytest.skip(
            f"no Postgres reachable ({type( error ).__name__}), so the answer_by CHECK "
            f"predicate is unexercised on the engine that enforces it."
        )

    transaction = connection.begin()
    connection.execute( text(
        f"CREATE TEMP TABLE probe ( resolves_by TIMESTAMPTZ NOT NULL, answer_by TIMESTAMPTZ, "
        f"CONSTRAINT {_CHECK} CHECK ( {_model_check_literal( _CHECK )} ) ) ON COMMIT DROP" ) )

    yield connection

    transaction.rollback()
    connection.close()


def _pg_insert( connection, answer_by_sql ):
    savepoint = connection.begin_nested()
    try:
        connection.execute( text(
            f"INSERT INTO probe VALUES ( TIMESTAMPTZ '2026-09-10 12:08:00+00', {answer_by_sql} )" ) )
        savepoint.commit()
        return True
    except Exception:
        savepoint.rollback()
        return False


@pytest.mark.parametrize( "label,answer_by_sql,accepted", [
    ( "a legacy ticket with no answer_by",   "NULL",                                   True  ),
    ( "an answer window before the stall",   "TIMESTAMPTZ '2026-09-10 12:02:00+00'",   True  ),
    ( "an answer window AT the stall",       "TIMESTAMPTZ '2026-09-10 12:08:00+00'",   True  ),
    ( "an answer window AFTER the stall",    "TIMESTAMPTZ '2026-09-10 12:08:01+00'",   False ),
] )
def test_POSTGRES_enforces_the_order_of_the_two_deadlines( postgres_probe, label, answer_by_sql, accepted ):
    assert _pg_insert( postgres_probe, answer_by_sql ) is accepted, f"Postgres got {label} wrong"
