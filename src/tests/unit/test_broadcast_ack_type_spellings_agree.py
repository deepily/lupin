"""
The broadcast-ack `type` value is spelled in FOUR places. This is the guard that they
still agree. Row 4f320c27.

  1. `NotificationRepository.BROADCAST_ACK_TYPE` — the definition. The watcher imports
     it to write with and the query uses it to read with, so those two cannot drift.
  2. migration `9184990becdf`'s `INDEX_WHERE` — a SQL string; cannot import a Python name.
  3. the mirroring ORM `Index` predicate in `postgres_models.py` — likewise SQL.
  4. this file, once, as a literal — see the control at the bottom.

🔴 WHAT DRIFT COSTS, AND WHY NOTHING ELSE CATCHES IT. If (2) or (3) stops matching (1),
the partial index simply stops covering the query. Acks are still saved, still pushed,
still returned — correctly — and the only symptom is a sequential scan over a table the
project keeps forever. Every functional test in this change stays green. There is no
failing behaviour to notice, which is exactly why it needs a test that compares the
STRINGS rather than the outcomes.

This is static analysis over two source files: no database, no server, :7999 unit tier.
"""

import ast
import pathlib
import re

import pytest

from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.postgres_models import Notification


_MIGRATION = ( pathlib.Path( __file__ ).resolve().parents[ 2 ]
               / "migrations" / "versions" / "9184990becdf_add_notification_payload.py" )
_INDEX_NAME = "idx_notifications_ack_broadcast"


def _migration_constant( name ):
    """
    Read a module-level `NAME = "literal"` out of the migration by AST.

    By AST and not by import, because importing a migration module drags in the whole
    alembic `op` context; and by AST and not by regex, because a regex would happily
    match the same name inside the docstring that explains it.
    """
    assert _MIGRATION.exists(), f"migration 9184990becdf is missing at {_MIGRATION}"
    tree = ast.parse( _MIGRATION.read_text() )
    for node in tree.body:
        if isinstance( node, ast.Assign ):
            for target in node.targets:
                if isinstance( target, ast.Name ) and target.id == name:
                    return ast.literal_eval( node.value )
    pytest.fail( f"{name} is not a module-level constant in {_MIGRATION.name}" )


def _orm_index_predicate():
    """The `postgresql_where` text of the ack index, as the ORM declares it."""
    for index in Notification.__table__.indexes:
        if index.name == _INDEX_NAME:
            where = index.dialect_options[ "postgresql" ][ "where" ]
            assert where is not None, f"{_INDEX_NAME} must be PARTIAL — an unfiltered index over a forever-kept table is not what was designed"
            return str( where )
    pytest.fail( f"the ORM declares no index named {_INDEX_NAME}" )


class TestTheFourSpellingsAgree:

    def test_the_migration_predicate_names_the_repositorys_ack_type( self ):
        where = _migration_constant( "INDEX_WHERE" )
        assert NotificationRepository.BROADCAST_ACK_TYPE in where, (
            f"migration INDEX_WHERE is {where!r}, which does not name "
            f"{NotificationRepository.BROADCAST_ACK_TYPE!r}" )

    def test_the_ORM_index_predicate_names_the_repositorys_ack_type( self ):
        where = _orm_index_predicate()
        assert NotificationRepository.BROADCAST_ACK_TYPE in where, (
            f"the ORM index predicate is {where!r}, which does not name "
            f"{NotificationRepository.BROADCAST_ACK_TYPE!r}" )

    def test_the_migration_and_the_ORM_declare_the_SAME_predicate( self ):
        """
        Both naming the type is not enough — they must be the same predicate, or
        Postgres builds one index and `alembic autogenerate` reports drift forever.
        """
        assert _migration_constant( "INDEX_WHERE" ) == _orm_index_predicate()

    def test_the_migration_and_the_ORM_index_the_SAME_expression( self ):
        expr = _migration_constant( "INDEX_EXPR" )
        orm  = " ".join( str( c ) for c in
                         next( i for i in Notification.__table__.indexes if i.name == _INDEX_NAME ).expressions )
        assert "broadcast_id" in expr, expr
        assert expr.replace( " ", "" ) in orm.replace( " ", "" ), ( expr, orm )

    def test_the_migration_and_the_ORM_agree_on_the_index_NAME( self ):
        assert _migration_constant( "INDEX_NAME" ) == _INDEX_NAME

    def test_the_migration_targets_the_notifications_table( self ):
        """A perfectly-matching predicate on the wrong table builds nothing useful."""
        assert _migration_constant( "TABLE_NAME" ) == Notification.__tablename__


class TestTheseChecksCanSeeAPositive:
    """
    Every assertion above is a match that PASSES. A matcher is worth nothing until it
    has been watched rejecting something, so each one is run once against a value
    that must fail it.
    """

    def test_the_type_matcher_rejects_a_predicate_naming_a_different_type( self ):
        wrong = "type = 'some_other_notification_type'"
        assert NotificationRepository.BROADCAST_ACK_TYPE not in wrong

    def test_the_constant_reader_fails_loudly_on_a_name_the_migration_lacks( self ):
        with pytest.raises( pytest.fail.Exception ):
            _migration_constant( "A_CONSTANT_THAT_IS_NOT_THERE" )

    def test_the_literal_in_this_file_is_the_one_under_test( self ):
        """
        The single hard-coded spelling in this file — if the project ever renames the
        type, this line is the one that must be edited, deliberately, by hand.
        """
        assert NotificationRepository.BROADCAST_ACK_TYPE == "commons_broadcast_ack"
        assert re.fullmatch( r"[a-z_]+", NotificationRepository.BROADCAST_ACK_TYPE )
