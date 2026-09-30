"""
The notifications table creator, covered without writing into the real repo.

`src/scripts/create_notifications_table.py` — 93 statements at zero, claimed off the
straggler census at tip `d81a9faa`.

🔴 THE SAFETY-CRITICAL PATCH HERE IS `cu.get_project_root`, AND IT IS MORE EXPOSED THAN
ITS SIBLING. `create_api_keys_table.py` goes through `get_auth_db_path()`, which a test
patches by name. This script builds its path inline —

    db_path = cu.get_project_root() + "/src/conf/long-term-memory/lupin-notifications.db"

— so the ONLY thing standing between a test and a real `lupin-notifications.db` written
into `src/conf/long-term-memory/` is that patch. Every test that reaches
`create_notifications_table()` patches `mod.cu` first. A miss would not raise: sqlite
creates the file happily, the test passes, and the repo grows a database nobody meant to
commit.

It also has NO users-table guard, unlike its sibling — nothing stops it running. That
makes the patch the whole of the safety, not a belt beside a brace.

Each test names the change that reddens it.
"""

import importlib
import os
import sqlite3
import sys

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import create_notifications_table as mod


MODNAME = "create_notifications_table"

# The schema's real width. The module DOCSTRING says 24 and is stale; its validator says
# 23 and is correct. Counted rather than copied from either: a fresh in-memory table
# built from CREATE_NOTIFICATIONS_TABLE reports 23 columns. Pinning the measured number
# means a future column change reddens this file instead of quietly agreeing with a
# docstring that was already wrong.
SCHEMA_FIELDS  = 23
SCHEMA_INDEXES = 3


class _Cu:
    """Stands in for `cosa.utils.util`, exposing only what the script calls of it."""

    def __init__( self, root ):
        self._root = str( root )

    def get_project_root( self ):
        return self._root


def _wire( monkeypatch, tmp_path ):
    """
    Redirect the script's project root into tmp_path and build the directory it demands.

    Returns the db path the script will compute, so a test can open the file the script
    actually wrote rather than one it assumes the script wrote.
    """
    ( tmp_path / "src" / "conf" / "long-term-memory" ).mkdir( parents=True )
    monkeypatch.setattr( mod, "cu", _Cu( tmp_path ) )
    return tmp_path / "src" / "conf" / "long-term-memory" / "lupin-notifications.db"


class TestTheTableIsCreated:

    def test_a_clean_run_creates_the_database_file_and_returns_true( self, monkeypatch, tmp_path ):
        """
        The file's existence is the assertion that would catch a wrong project root — if
        the patch ever stopped taking, the script would write elsewhere and this path
        would be empty.
        """
        db = _wire( monkeypatch, tmp_path )
        assert mod.create_notifications_table() is True
        assert db.exists(), "the script wrote its database somewhere other than the patched root"

    def test_the_columns_are_the_ones_the_schema_names( self, monkeypatch, tmp_path ):
        """
        Named, not counted — a count agrees with a rename. Spot-checking the four that
        carry meaning a rename would silently break: the routing pair and the two that
        distinguish a response-required notification from a fire-and-forget one.
        """
        db = _wire( monkeypatch, tmp_path )
        mod.create_notifications_table()
        conn = sqlite3.connect( db )
        cols = { r[ 1 ] for r in conn.execute( "PRAGMA table_info(notifications)" ) }
        conn.close()
        assert len( cols ) == SCHEMA_FIELDS
        assert { "sender_id", "recipient_id", "response_requested", "response_value" } <= cols

    def test_all_three_indexes_are_created_and_named( self, monkeypatch, tmp_path ):
        db = _wire( monkeypatch, tmp_path )
        mod.create_notifications_table()
        conn = sqlite3.connect( db )
        idx  = { r[ 0 ] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='notifications'"
            " AND name NOT LIKE 'sqlite_autoindex%'" ) }
        conn.close()
        assert idx == { "idx_recipient_state", "idx_recipient_created", "idx_expires_at" }

    def test_the_expiry_index_is_partial( self, monkeypatch, tmp_path ):
        """
        `WHERE expires_at IS NOT NULL` — most notifications are fire-and-forget and carry
        no expiry, so a full index would be mostly nulls. Dropping the clause leaves the
        index NAME identical, so the test above cannot see it; only the stored SQL can.
        """
        db = _wire( monkeypatch, tmp_path )
        mod.create_notifications_table()
        conn = sqlite3.connect( db )
        sql  = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_expires_at'" ).fetchone()[ 0 ]
        conn.close()
        assert "WHERE" in sql.upper() and "NOT NULL" in sql.upper()

    def test_running_it_twice_is_harmless( self, monkeypatch, tmp_path ):
        _wire( monkeypatch, tmp_path )
        assert mod.create_notifications_table() is True
        assert mod.create_notifications_table() is True


class TestItRefusesRatherThanGuesses:

    def test_a_missing_database_directory_raises( self, monkeypatch, tmp_path ):
        """
        The one precondition the script checks for itself. It builds no directories —
        sqlite creates files, never folders — so this raise is what stands between an
        operator and a confusing `unable to open database file`.
        """
        monkeypatch.setattr( mod, "cu", _Cu( tmp_path / "nowhere" ) )
        with pytest.raises( RuntimeError, match="Database directory does not exist" ):
            mod.create_notifications_table()

    def test_a_sqlite_error_is_reported_as_false_not_raised( self, monkeypatch, tmp_path ):
        _wire( monkeypatch, tmp_path )
        def _boom( *a, **k ): raise sqlite3.OperationalError( "disk I/O error" )
        monkeypatch.setattr( mod.sqlite3, "connect", _boom )
        assert mod.create_notifications_table() is False

    def test_an_unexpected_error_is_also_swallowed_into_false( self, monkeypatch, tmp_path ):
        """
        A different handler from the sqlite3 one. Narrowing either would leave the
        other's test green, which is why they are covered apart.
        """
        _wire( monkeypatch, tmp_path )
        def _boom( *a, **k ): raise ValueError( "something entirely else" )
        monkeypatch.setattr( mod.sqlite3, "connect", _boom )
        assert mod.create_notifications_table() is False

    def test_a_failing_validation_turns_the_whole_run_false( self, monkeypatch, capsys, tmp_path ):
        _wire( monkeypatch, tmp_path )
        monkeypatch.setattr( mod, "validate_schema", lambda conn: { "success": False, "error": "planted" } )
        assert mod.create_notifications_table() is False
        assert "planted" in capsys.readouterr().err


class TestValidateSchema:

    def test_it_reports_the_table_missing( self, tmp_path ):
        conn = sqlite3.connect( tmp_path / "x.db" )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is False
        assert "not found" in out[ "error" ]

    def test_it_counts_a_short_table_as_a_failure_and_says_how_short( self, tmp_path ):
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.execute( "CREATE TABLE notifications ( id TEXT PRIMARY KEY, title TEXT )" )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is False
        assert out[ "field_count" ] == 2
        assert f"Expected {SCHEMA_FIELDS} fields" in out[ "error" ]

    def test_it_fails_a_correct_table_that_is_missing_its_indexes( self, tmp_path ):
        """The branch between the two checks: fields pass, indexes do not."""
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( mod.CREATE_NOTIFICATIONS_TABLE )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is False
        assert out[ "index_count" ] == 0
        assert f"Expected {SCHEMA_INDEXES} indexes" in out[ "error" ]

    def test_a_complete_table_validates( self, tmp_path ):
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( mod.CREATE_NOTIFICATIONS_TABLE )
        for sql in mod.CREATE_INDEXES: conn.executescript( sql )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is True
        assert out[ "field_count" ]  == SCHEMA_FIELDS
        assert out[ "index_count" ] == SCHEMA_INDEXES

    def test_the_validator_agrees_with_the_schema_it_ships_beside( self, tmp_path ):
        """
        ⚠️ THE CONSISTENCY CHECK THE MODULE'S OWN DOCSTRING FAILS. That docstring claims
        24 fields; the schema and the validator both say 23. Building the table from
        `CREATE_NOTIFICATIONS_TABLE` and validating it pins the two to each other, so a
        column added to the SQL without touching `expected_fields` — or the reverse —
        reddens here rather than at 3am against a real database.
        """
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( mod.CREATE_NOTIFICATIONS_TABLE )
        for sql in mod.CREATE_INDEXES: conn.executescript( sql )
        try:
            measured = len( conn.execute( "PRAGMA table_info(notifications)" ).fetchall() )
            out      = mod.validate_schema( conn )
        finally:
            conn.close()
        assert measured == SCHEMA_FIELDS
        assert out[ "success" ] is True, "the validator rejects the schema shipped beside it"

    def test_the_automatic_primary_key_index_is_not_counted( self, tmp_path ):
        """
        ⚠️ THE `sqlite_autoindex%` EXCLUSION IS LOAD-BEARING ON THE REAL SCHEMA, not on a
        contrived one — which is why this uses `CREATE_NOTIFICATIONS_TABLE` itself.

        `id TEXT PRIMARY KEY` is not a rowid alias the way `INTEGER PRIMARY KEY` is, so
        sqlite builds `sqlite_autoindex_notifications_1` to enforce it. That index is
        present in every real database this script creates. Delete the exclusion and the
        count goes 3 → 4 and rejects a schema the script itself just wrote.

        My first cut of this test built a synthetic table instead and failed against
        correct code, because the synthetic table lacked the columns the indexes name.
        The test was wrong, not the script — and the real schema turned out to be the
        better evidence anyway.
        """
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( mod.CREATE_NOTIFICATIONS_TABLE )
        for sql in mod.CREATE_INDEXES: conn.executescript( sql )
        try:
            every = { r[ 0 ] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='notifications'" ) }
            out   = mod.validate_schema( conn )
        finally:
            conn.close()

        # The precondition, asserted rather than assumed: without an autoindex present
        # this test would pass with the exclusion deleted, and prove nothing.
        assert any( n.startswith( "sqlite_autoindex" ) for n in every ), \
            "no automatic index exists, so this test cannot see the exclusion"
        assert out[ "success" ] is True, "sqlite's own index was counted as one of ours"
        assert out[ "index_count" ] == SCHEMA_INDEXES

    def test_a_broken_connection_is_reported_not_raised( self, tmp_path ):
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.close()
        out = mod.validate_schema( conn )
        assert out[ "success" ] is False
        assert "Validation query failed" in out[ "error" ]


class TestMain:

    def test_success_exits_zero( self, monkeypatch ):
        monkeypatch.setattr( mod, "create_notifications_table", lambda: True )
        assert mod.main() == 0

    def test_failure_exits_one( self, monkeypatch ):
        monkeypatch.setattr( mod, "create_notifications_table", lambda: False )
        assert mod.main() == 1

    def test_an_escaping_exception_exits_one_and_prints_a_traceback( self, monkeypatch, capsys ):
        def _boom(): raise RuntimeError( "escaped" )
        monkeypatch.setattr( mod, "create_notifications_table", _boom )
        assert mod.main() == 1
        err = capsys.readouterr().err
        assert "FATAL ERROR" in err and "Traceback" in err


class TestTheBootstrap:
    """The LUPIN_ROOT block, which runs on IMPORT — so these re-import and restore state."""

    def test_no_lupin_root_refuses_to_import_and_says_how_to_fix_it( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        monkeypatch.delitem( sys.modules, MODNAME, raising=False )
        with pytest.raises( RuntimeError, match="LUPIN_ROOT" ):
            importlib.import_module( MODNAME )

    def test_importing_puts_src_on_the_path( self, monkeypatch, tmp_path ):
        root = tmp_path / "fakeroot"
        ( root / "src" ).mkdir( parents=True )
        monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
        monkeypatch.setattr( sys, "path", list( sys.path ) )
        monkeypatch.delitem( sys.modules, MODNAME, raising=False )
        importlib.import_module( MODNAME )
        assert str( root / "src" ) in sys.path

    def test_an_src_path_already_present_is_not_added_twice( self, monkeypatch, tmp_path ):
        root = tmp_path / "fakeroot"
        ( root / "src" ).mkdir( parents=True )
        monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
        monkeypatch.setattr( sys, "path", [ str( root / "src" ) ] + list( sys.path ) )
        monkeypatch.delitem( sys.modules, MODNAME, raising=False )
        importlib.import_module( MODNAME )
        assert sys.path.count( str( root / "src" ) ) == 1
