"""
The api_keys table creator, covered without touching a real auth database.

`src/scripts/create_api_keys_table.py` — 102 statements at zero, claimed off the
straggler census at tip `d81a9faa`.

🔴 NO WRITE REACHES THE REAL `lupin-auth.db`. Both `get_auth_db_path` and
`get_auth_db_connection` are stopped at the MODULE attribute, never deeper, so a missed
patch surfaces as an AttributeError against the module rather than as a CREATE TABLE
against the fleet's live credential store. The script's whole job is to write schema, so
a test that reached the real path would not fail — it would SUCCEED, silently, against
the wrong database. Same trap CLAUDE.md records for the two postgres databases: an
operation that works is not evidence it worked where you meant.

The sqlite here is REAL, in `tmp_path`. Faking the driver would leave the interesting
assertions — seven fields, four indexes, the `sqlite_autoindex` exclusion — agreeing with
whatever the code does. A real file gives them teeth and costs milliseconds.

The module runs work AT IMPORT TIME (the LUPIN_ROOT bootstrap), so the tests covering it
re-import under a modified environment and restore `sys.modules` and `sys.path`.

Each test names the change that reddens it.
"""

import importlib
import os
import sqlite3
import sys

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import create_api_keys_table as mod


MODNAME = "create_api_keys_table"


def _auth_db( tmp_path, with_users=True ):
    """
    A real sqlite auth database in tmp_path, with or without `users`.

    `users` is a parameter because the script REFUSES to run without it, and that
    refusal is the guard standing between a rerun and a foreign key pointing at nothing.
    """
    path = tmp_path / "lupin-auth.db"
    conn = sqlite3.connect( path )
    if with_users:
        conn.execute( "CREATE TABLE users ( id TEXT PRIMARY KEY, email TEXT )" )
        conn.commit()
    conn.close()
    return path


def _wire( monkeypatch, tmp_path, with_users=True ):
    """Point the module's two database entry points at a throwaway file."""
    path = _auth_db( tmp_path, with_users=with_users )
    monkeypatch.setattr( mod, "get_auth_db_path", lambda: path )
    monkeypatch.setattr( mod, "get_auth_db_connection", lambda: sqlite3.connect( path ) )
    return path


class TestTheTableIsCreated:

    def test_a_clean_auth_database_gets_the_table_and_returns_true( self, monkeypatch, tmp_path ):
        path = _wire( monkeypatch, tmp_path )
        assert mod.create_api_keys_table() is True
        conn  = sqlite3.connect( path )
        names = { r[ 0 ] for r in conn.execute( "SELECT name FROM sqlite_master WHERE type='table'" ) }
        conn.close()
        assert "api_keys" in names

    def test_the_seven_fields_are_the_seven_the_schema_names( self, monkeypatch, tmp_path ):
        """
        Named rather than counted. A count of 7 passes just as well if a column is
        renamed or retyped — and the script's own validator only counts, so counting
        here would inherit the blind spot instead of covering it.
        """
        path = _wire( monkeypatch, tmp_path )
        mod.create_api_keys_table()
        conn = sqlite3.connect( path )
        cols = { r[ 1 ]: r[ 2 ] for r in conn.execute( "PRAGMA table_info(api_keys)" ) }
        conn.close()
        assert set( cols ) == { "id", "user_id", "key_hash", "description",
                                "created_at", "last_used_at", "is_active" }
        # TEXT and not INTEGER on purpose — users.id is a UUID, and the script's own
        # comment records this as a FIX. A revert would pass a field COUNT.
        assert cols[ "user_id" ] == "TEXT"

    def test_all_four_indexes_are_created_and_named( self, monkeypatch, tmp_path ):
        path = _wire( monkeypatch, tmp_path )
        mod.create_api_keys_table()
        conn = sqlite3.connect( path )
        idx  = { r[ 0 ] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='api_keys'"
            " AND name NOT LIKE 'sqlite_autoindex%'" ) }
        conn.close()
        assert idx == { "idx_api_keys_key_hash", "idx_api_keys_user_id",
                        "idx_api_keys_is_active", "idx_api_keys_user_active" }

    def test_running_it_twice_is_harmless( self, monkeypatch, tmp_path ):
        """
        IF NOT EXISTS — a second run must be a no-op, not an error. The realistic
        operational case: somebody re-runs it because they are unsure it took.
        """
        _wire( monkeypatch, tmp_path )
        assert mod.create_api_keys_table() is True
        assert mod.create_api_keys_table() is True


class TestItRefusesRatherThanGuesses:

    def test_no_users_table_means_no_api_keys_table( self, monkeypatch, tmp_path ):
        """
        The foreign key targets users(id). Creating api_keys without it leaves a
        constraint pointing at nothing, so the script raises — and its own handler
        turns that into False rather than letting it propagate.
        """
        path = _wire( monkeypatch, tmp_path, with_users=False )
        assert mod.create_api_keys_table() is False
        conn  = sqlite3.connect( path )
        names = { r[ 0 ] for r in conn.execute( "SELECT name FROM sqlite_master WHERE type='table'" ) }
        conn.close()
        assert "api_keys" not in names, "the table was created despite the missing users table"

    def test_a_missing_database_DIRECTORY_raises( self, monkeypatch, tmp_path ):
        """
        Distinct from a missing FILE, which is only a warning: sqlite will create the
        file but cannot create the directory, so this one is fatal.
        """
        monkeypatch.setattr( mod, "get_auth_db_path", lambda: tmp_path / "nope" / "lupin-auth.db" )
        with pytest.raises( RuntimeError, match="Database directory does not exist" ):
            mod.create_api_keys_table()

    def test_a_missing_database_FILE_is_only_a_warning( self, monkeypatch, capsys, tmp_path ):
        """The complement of the test above — the PAIR is what shows the two are treated differently."""
        path = tmp_path / "lupin-auth.db"           # directory exists, file does not
        monkeypatch.setattr( mod, "get_auth_db_path", lambda: path )
        monkeypatch.setattr( mod, "get_auth_db_connection", lambda: sqlite3.connect( path ) )
        mod.create_api_keys_table()
        assert "does not exist" in capsys.readouterr().out

    def test_a_sqlite_error_is_reported_as_false_not_raised( self, monkeypatch, tmp_path ):
        _wire( monkeypatch, tmp_path )
        def _boom(): raise sqlite3.OperationalError( "database is locked" )
        monkeypatch.setattr( mod, "get_auth_db_connection", _boom )
        assert mod.create_api_keys_table() is False

    def test_an_unexpected_error_is_also_swallowed_into_false( self, monkeypatch, tmp_path ):
        """
        The broad `except Exception` gives an operator a message rather than a
        traceback. Covered separately from the sqlite3 case: they are different
        handlers, and narrowing one would leave the other's test still green.
        """
        _wire( monkeypatch, tmp_path )
        def _boom(): raise ValueError( "something entirely else" )
        monkeypatch.setattr( mod, "get_auth_db_connection", _boom )
        assert mod.create_api_keys_table() is False

    def test_a_failing_validation_turns_the_whole_run_false( self, monkeypatch, capsys, tmp_path ):
        _wire( monkeypatch, tmp_path )
        monkeypatch.setattr( mod, "validate_schema", lambda conn: { "success": False, "error": "planted" } )
        assert mod.create_api_keys_table() is False
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
        conn.execute( "CREATE TABLE api_keys ( id INTEGER PRIMARY KEY, user_id TEXT )" )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is False
        assert out[ "field_count" ] == 2
        assert "Expected 7 fields" in out[ "error" ]

    def test_it_fails_a_correct_table_that_is_missing_its_indexes( self, tmp_path ):
        """
        Field count passes, index count does not — the branch BETWEEN the two checks,
        which a test that only ever supplies a complete table cannot reach.
        """
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( mod.CREATE_API_KEYS_TABLE )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is False
        assert out[ "index_count" ] == 0
        assert "Expected 4 indexes" in out[ "error" ]

    def test_a_complete_table_validates( self, tmp_path ):
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( mod.CREATE_API_KEYS_TABLE )
        for sql in mod.CREATE_INDEXES: conn.executescript( sql )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out == { "success": True, "field_count": 7, "index_count": 4 }

    def test_the_automatic_primary_key_index_is_not_counted( self, tmp_path ):
        """
        ⚠️ THE `sqlite_autoindex%` EXCLUSION IS LOAD-BEARING AND EASY TO DELETE. A UNIQUE
        column gets an index sqlite made itself; counting it takes 4 to 5 and fails a
        schema that is correct. Reproduced WITH a UNIQUE column so the exclusion has
        something to exclude — without one, deleting the clause changes nothing and this
        test would pass either way.
        """
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.executescript( """
            CREATE TABLE api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE, description TEXT,
                created_at TIMESTAMP, last_used_at TIMESTAMP, is_active BOOLEAN );
        """ )
        for sql in mod.CREATE_INDEXES: conn.executescript( sql )
        try:     out = mod.validate_schema( conn )
        finally: conn.close()
        assert out[ "success" ] is True, "sqlite's own index was counted as one of ours"

    def test_a_broken_connection_is_reported_not_raised( self, tmp_path ):
        conn = sqlite3.connect( tmp_path / "x.db" )
        conn.close()                                    # every query now raises
        out = mod.validate_schema( conn )
        assert out[ "success" ] is False
        assert "Validation query failed" in out[ "error" ]


class TestMain:

    def test_success_exits_zero( self, monkeypatch ):
        monkeypatch.setattr( mod, "create_api_keys_table", lambda: True )
        assert mod.main() == 0

    def test_failure_exits_one( self, monkeypatch ):
        monkeypatch.setattr( mod, "create_api_keys_table", lambda: False )
        assert mod.main() == 1

    def test_an_escaping_exception_exits_one_and_prints_a_traceback( self, monkeypatch, capsys ):
        """
        `create_api_keys_table` swallows its own errors, so this handler only fires for
        something raised outside it — and then an operator needs the traceback, not a
        one-line message.
        """
        def _boom(): raise RuntimeError( "escaped" )
        monkeypatch.setattr( mod, "create_api_keys_table", _boom )
        assert mod.main() == 1
        err = capsys.readouterr().err
        assert "FATAL ERROR" in err and "Traceback" in err


class TestTheBootstrap:
    """
    The LUPIN_ROOT block at the top of the module. It runs on IMPORT, so these tests
    re-import under a modified environment and put `sys.modules` and `sys.path` back.
    """

    def test_no_lupin_root_refuses_to_import_and_says_how_to_fix_it( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        monkeypatch.delitem( sys.modules, MODNAME, raising=False )
        with pytest.raises( RuntimeError, match="LUPIN_ROOT environment variable not set" ):
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
        """The `if src_path not in sys.path` guard — its False branch."""
        root = tmp_path / "fakeroot"
        ( root / "src" ).mkdir( parents=True )
        monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
        monkeypatch.setattr( sys, "path", [ str( root / "src" ) ] + list( sys.path ) )
        monkeypatch.delitem( sys.modules, MODNAME, raising=False )
        importlib.import_module( MODNAME )
        assert sys.path.count( str( root / "src" ) ) == 1
