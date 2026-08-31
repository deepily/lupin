"""
The dev→test companion seed, covered without opening a socket or touching a credential.

`src/scripts/seed_test_companions.py` — 83 statements at zero, claimed off Chloé 🗼's
corrected union gap list at `5506e9a4`.

🔴 WHY EVERY TEST NEUTRALISES THE CONNECTION AT THE MODULE ATTRIBUTE. This script
OVERWRITES `password_hash` and `key_hash` — it was changed from `ON CONFLICT DO NOTHING`
to `DO UPDATE` on 2026-08-19 precisely so a rotated dev credential reaches test. Before
that change it was safe BY ACCIDENT: it could not overwrite anything because it could not
do its job. A test that forgot to patch would not fail — it would resolve `DB_HOST`
(default `lupin-postgres`, which is real docker DNS on this box), connect, and converge
real rows. So `_connect` is replaced by name in every test that reaches `seed_if_missing`,
and the one test that exercises `_connect` itself patches `psycopg2.connect`.

The refusal test additionally asserts that `_connect` was **never called**, because the
guard's own claim is "aborting before any connection is opened" — an exit code alone would
pass whether or not that sentence is true.

Each test names the change that reddens it.
"""

import json
import os
import sys

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import seed_test_companions as mod


# A dev `users` row in the exact column order the SELECT asks for.
def _user_row( uid="u-1", email="a@b.c", pw="hash-1", created="2026-01-01",
               verified=True, active=True, roles=None ):
    return ( uid, email, pw, created, verified, active, roles if roles is not None else [ "admin" ] )


def _key_row( kid="k-1", uid="u-1", key_hash="kh-1", desc="a key",
              active=True, created="2026-01-01", last_used=None ):
    return ( kid, uid, key_hash, desc, active, created, last_used )


class _DevCursor:
    """Answers the two SELECTs the script makes, by which table the SQL names."""

    def __init__( self, users_by_email, keys_by_email ):
        self.users_by_email = users_by_email
        self.keys_by_email  = keys_by_email
        self._pending       = None

    def execute( self, sql, params=None ):
        email = params[ 0 ] if params else None
        if "FROM users" in sql:      self._pending = ( "user", email )
        elif "FROM api_keys" in sql: self._pending = ( "keys", email )
        else:                        self._pending = ( "other", email )

    def fetchone( self ):
        kind, email = self._pending
        return self.users_by_email.get( email )

    def fetchall( self ):
        kind, email = self._pending
        return self.keys_by_email.get( email, [ ] )


class _TestCursor:
    """
    Answers the INSERTs. `xmax = 0` is what the script reads to tell a genuine INSERT
    from an UPDATE, so the fake returns it from scripted queues rather than a constant —
    a constant could not distinguish the seeded path from the refreshed one.
    """

    def __init__( self, user_inserted, key_inserted ):
        self.user_inserted = list( user_inserted )
        self.key_inserted  = list( key_inserted )
        self.executed      = [ ]
        self._pending      = None

    def execute( self, sql, params=None ):
        self.executed.append( ( sql, params ) )
        if   "INSERT INTO users"    in sql: self._pending = "user"
        elif "INSERT INTO api_keys" in sql: self._pending = "key"
        else:                               self._pending = None

    def fetchone( self ):
        if self._pending == "user": return ( self.user_inserted.pop( 0 ), )
        if self._pending == "key":  return ( self.key_inserted.pop( 0 ), )
        raise AssertionError( "fetchone() after a statement that RETURNS nothing" )


class _Conn:
    def __init__( self, cursor ):
        self._cursor = cursor
        self.closed  = False

    def cursor( self ): return self._cursor
    def close( self ):  self.closed = True


@pytest.fixture
def wired( monkeypatch ):
    """
    Replaces `_connect` by name and hands back the pieces. Every field is settable so a
    test states the world it needs rather than inheriting a default it did not read.
    """
    state = {
        "users_by_email" : { },
        "keys_by_email"  : { },
        "user_inserted"  : [ True ] * 12,
        "key_inserted"   : [ True ] * 12,
        "conns"          : [ ],
    }

    def fake_connect( dbname ):
        if dbname == mod.DEV_DB:
            cur = _DevCursor( state[ "users_by_email" ], state[ "keys_by_email" ] )
        else:
            cur = _TestCursor( state[ "user_inserted" ], state[ "key_inserted" ] )
        conn = _Conn( cur )
        state[ "conns" ].append( conn )
        return conn

    monkeypatch.setattr( mod, "_connect", fake_connect )
    return state


def _all_companions( state, **kw ):
    """Give every companion email a dev row, so the loop runs to completion."""
    for i, email in enumerate( mod.COMPANION_EMAILS ):
        state[ "users_by_email" ][ email ] = _user_row( uid=f"u-{i}", email=email, **kw )


# ── The guard ──────────────────────────────────────────────────────────────────

def test_a_target_that_is_not_a_test_database_refuses_BEFORE_opening_a_connection( monkeypatch, capsys ):
    """
    Reddens if the `"test" not in TEST_DB` guard is dropped or inverted.

    The second assertion is the load-bearing one. The guard's own warning says it is
    "aborting before any connection is opened"; an exit code cannot tell you whether that
    sentence is true, and this script overwrites credential hashes, so where the abort
    happens is the whole point of it.
    """
    calls = [ ]
    monkeypatch.setattr( mod, "TEST_DB", "lupin_db_production" )
    monkeypatch.setattr( mod, "_connect", lambda dbname: calls.append( dbname ) )

    with pytest.raises( SystemExit ) as excinfo:
        mod.seed_if_missing()

    assert excinfo.value.code == 3
    assert calls == [ ], "the refusal must happen before any connection is opened"
    assert "REFUSING" in capsys.readouterr().out


def test_a_target_that_IS_a_test_database_proceeds_past_the_guard( wired ):
    """The negative control for the guard — without it, the test above proves nothing."""
    _all_companions( wired )
    mod.seed_if_missing()
    assert len( wired[ "conns" ] ) == 2


# ── Connection failure ─────────────────────────────────────────────────────────

def test_a_connection_failure_skips_the_seed_and_does_NOT_raise( monkeypatch, capsys ):
    """
    Reddens if the connect try/except is removed. The test server must still start when
    postgres is unreachable — the script says so and degrades to a warning.
    """
    def boom( dbname ): raise OSError( "no route to host" )
    monkeypatch.setattr( mod, "_connect", boom )

    assert mod.seed_if_missing() is None
    out = capsys.readouterr().out
    assert "Cannot connect" in out and "seed skipped" in out


# ── The user loop ──────────────────────────────────────────────────────────────

def test_the_primary_admin_missing_from_dev_aborts_with_2( wired, capsys ):
    """
    Reddens if the `email == ADMIN_EMAIL` arm is dropped. A missing primary admin locks
    the operator out of :8000 on startup, so it fails loud rather than continuing.
    """
    with pytest.raises( SystemExit ) as excinfo:
        mod.seed_if_missing()
    assert excinfo.value.code == 2
    assert "PRIMARY ADMIN" in capsys.readouterr().out


def test_a_NON_primary_companion_missing_from_dev_is_skipped_not_fatal( wired, capsys ):
    """
    The other side of the same branch, and the reason the pair is needed: with only the
    test above, deleting the `email == ADMIN_EMAIL` condition and always exiting would
    still pass.
    """
    wired[ "users_by_email" ][ mod.ADMIN_EMAIL ] = _user_row( email=mod.ADMIN_EMAIL )
    mod.seed_if_missing()
    out = capsys.readouterr().out
    assert "not found" in out and "skipping" in out
    assert "PRIMARY ADMIN" not in out


def test_a_new_row_counts_as_SEEDED_and_an_existing_one_as_REFRESHED( wired, capsys ):
    """
    Reddens if `RETURNING ( xmax = 0 )` stops being read, or the True/False arms swap.
    The counts are DELIBERATELY UNEQUAL — 1 seeded against 5 refreshed — because two equal
    counts cannot reveal an exchange between them however the test is named (row 9ad838d6).
    """
    _all_companions( wired )
    wired[ "user_inserted" ] = [ True ] + [ False ] * 5
    wired[ "key_inserted" ]  = [ ]

    mod.seed_if_missing()

    out = capsys.readouterr().out
    assert "Seeded user:" in out
    assert "Refreshed user from" in out
    assert "Seeded 1 user(s)" in out
    assert "refreshed 5 user(s)" in out


@pytest.mark.parametrize( "roles,expected", [
    ( [ "admin", "tester" ],   '["admin", "tester"]' ),
    ( { "role": "admin" },     '{"role": "admin"}'   ),
] )
def test_roles_reach_the_insert_as_JSON_when_they_are_a_list_OR_A_DICT( wired, roles, expected ):
    """
    Reddens if the `isinstance( roles, ( list, dict ) )` arm stops serializing.

    CHLOÉ 🗼 FOUND THE DICT ROW — my first version tested only the list, and measured:
    narrowing the check to `( list, )` SURVIVES at sha 1c4baa9ebdaa, 19 passed. The column
    is jsonb and psycopg2 will not auto-cast a dict back to it, so an unserialised dict is
    a live failure the suite could not see. A tuple of accepted types needs a row PER TYPE
    — testing one member proves nothing about the others.
    """
    _all_companions( wired, roles=roles )
    mod.seed_if_missing()

    test_cur = wired[ "conns" ][ 1 ].cursor()
    user_sql = [ p for s, p in test_cur.executed if "INSERT INTO users" in s ]
    assert user_sql[ 0 ][ 6 ] == expected


def test_roles_that_are_ALREADY_a_string_are_passed_through_untouched( wired ):
    """
    The false arm of the same branch. Without it, removing the isinstance check entirely
    and always calling json.dumps would still pass the test above — and would double-encode
    a value that is already JSON.
    """
    _all_companions( wired, roles='["admin"]' )
    mod.seed_if_missing()

    test_cur = wired[ "conns" ][ 1 ].cursor()
    user_sql = [ p for s, p in test_cur.executed if "INSERT INTO users" in s ]
    assert user_sql[ 0 ][ 6 ] == '["admin"]', "an already-serialized value must not be encoded twice"


def test_every_companion_is_marked_protected_TRUE( wired ):
    """
    Reddens if the is_protected UPDATE is dropped, or if it stops setting TRUE.

    The value assertion is not decoration. My first version asserted only that a statement
    MENTIONING is_protected ran for each companion, and `TRUE` -> `FALSE` SURVIVED the
    mutation pass at sha feca858e0ab4: the column name and the email parameter are
    identical either way, so the fixture could not see the one thing the statement is for.
    A companion silently marked unprotected is deletable by any cleanup that spares
    protected rows.
    """
    _all_companions( wired )
    mod.seed_if_missing()

    test_cur = wired[ "conns" ][ 1 ].cursor()
    stmts    = [ ( s, p ) for s, p in test_cur.executed if "is_protected" in s ]

    assert sorted( p[ 0 ] for _, p in stmts ) == sorted( mod.COMPANION_EMAILS )
    assert all( "is_protected = TRUE" in s for s, _ in stmts ), \
        "setting is_protected FALSE leaves the column name and the email param unchanged"


# ── The API-key loop ───────────────────────────────────────────────────────────

def test_api_keys_are_counted_by_the_same_xmax_rule_as_users( wired, capsys ):
    """
    Reddens if the key loop stops reading `xmax = 0`. Counts unequal for the same reason
    as the user test: 1 seeded against 2 refreshed.
    """
    _all_companions( wired )
    wired[ "users_by_email" ] = { e: _user_row( uid=f"u-{i}", email=e )
                                  for i, e in enumerate( mod.COMPANION_EMAILS ) }
    wired[ "keys_by_email" ][ mod.SERVICE_ACCT ] = [ _key_row( kid="k-1" ),
                                                     _key_row( kid="k-2" ),
                                                     _key_row( kid="k-3" ) ]
    wired[ "user_inserted" ] = [ False ] * 6
    wired[ "key_inserted" ]  = [ True, False, False ]

    mod.seed_if_missing()

    out = capsys.readouterr().out
    # CHLOÉ 🗼's strengthening. "Seeded API key:" alone names the line and not the value —
    # the fixture CAN discriminate (desc="a key", kid="k-1", both truthy and distinct) and
    # the assertion simply did not look. Naming the description makes this test fail for
    # its OWN reason rather than relying on its neighbour to catch an operand swap.
    assert "Seeded API key: a key" in out
    assert "Seeded 0 user(s) and 1 API key(s)" in out
    assert "2 API key(s)" in out


@pytest.mark.parametrize( "description,expected,why", [
    ( "the cosa-voice key", "the cosa-voice key", "a described key is announced BY its description" ),
    ( None,                 "k-only",             "a key with no description falls back to its id" ),
] )
def test_a_seeded_api_key_is_announced_by_its_description_or_its_id( wired, capsys, description, expected, why ):
    """
    CHLOÉ 🗼's TEST, and she was right that mine could not see this.

    We wrote this suite concurrently — Mr Radio's DM-assignment crossed my start — and she
    ruled to keep mine because it was larger. I checked the ruling rather than accept it in
    my own favour, and hers catches something mine did not: `description or key_id`.

    Measured — collapsing that to plain `{key_id}` SURVIVES my 17 tests at sha b92989afe6a8,
    17 passed, while the file still reports 100%. It is invisible to the gate because
    coverage.py does not treat an `or` short-circuit as a branch, so the fallback arm is
    never reported as unreached. Same class as the `.get` default that survived on
    bounce_dev_warn tonight: an arm nothing exercises, under a report that looks finished.

    Both rows are needed. With only the described one, deleting `or key_id` still passes;
    with only the None one, deleting `description or` still passes.
    """
    _all_companions( wired )
    wired[ "keys_by_email" ][ mod.SERVICE_ACCT ] = [ _key_row( kid="k-only", desc=description ) ]
    wired[ "user_inserted" ] = [ False ] * 6
    wired[ "key_inserted" ]  = [ True ]

    mod.seed_if_missing()

    assert f"Seeded API key: {expected}" in capsys.readouterr().out, why


def test_the_summary_reports_a_pure_REFRESH_as_none_newly_created( wired, capsys ):
    """
    Reddens if the `users_seeded == 0 and keys_seeded == 0` arm is dropped.

    This line is the one the script's own comment is about: the old wording claimed the
    credentials were GOOD when all it knew was that rows EXISTED, and it printed on every
    startup for months while :8000 logins returned 401. It must report what was DONE.
    """
    _all_companions( wired )
    wired[ "user_inserted" ] = [ False ] * 6
    wired[ "key_inserted" ]  = [ ]

    mod.seed_if_missing()

    out = capsys.readouterr().out
    assert "none newly created" in out
    assert "6 user(s)" in out


# ── Failure mid-flight, and the finally ────────────────────────────────────────

def test_an_error_mid_seed_is_caught_and_BOTH_connections_still_close( wired, monkeypatch, capsys ):
    """
    Reddens if the except is narrowed away or the finally is dropped. A leaked connection
    on the startup path would outlive the script on every container start.
    """
    _all_companions( wired )

    original = _TestCursor.execute
    def explode( self, sql, params=None ):
        if "INSERT INTO users" in sql: raise RuntimeError( "relation does not exist" )
        return original( self, sql, params )
    monkeypatch.setattr( _TestCursor, "execute", explode )

    mod.seed_if_missing()

    out = capsys.readouterr().out
    assert "Companion seed error" in out
    assert "some admin features may return 401" in out
    assert all( c.closed for c in wired[ "conns" ] ), "both connections must close"


# ── The primitives ─────────────────────────────────────────────────────────────

def test__connect_asks_psycopg2_for_an_AUTOCOMMIT_connection( monkeypatch ):
    """
    The one test that reaches psycopg2. It patches `connect` on the module psycopg2
    object, so a regression that bypassed the patch would raise rather than dial out.

    autocommit is asserted because the script never commits: without it every INSERT
    above would be rolled back on close and the seed would silently do nothing.
    """
    seen = { }

    class _Fake:
        autocommit = False

    def fake_connect( **kw ):
        seen.update( kw )
        return _Fake()

    monkeypatch.setattr( mod.psycopg2, "connect", fake_connect )

    conn = mod._connect( "lupin_db_test" )

    assert conn.autocommit is True
    assert seen[ "dbname" ] == "lupin_db_test"
    assert seen[ "port" ] == int( mod.DB_PORT ), "the port must be an int, not the env string"
    assert seen[ "connect_timeout" ] == 5


@pytest.mark.parametrize( "fn,marker", [ ( "_info", "[SEED]" ), ( "_success", "✓" ), ( "_warn", "⚠" ) ] )
def test_each_helper_prints_its_own_marker( fn, marker, capsys ):
    """Reddens if two helpers are collapsed into one — they are how the log is read."""
    getattr( mod, fn )( "a message" )
    out = capsys.readouterr().out
    assert marker in out and "a message" in out


def test_running_the_module_as_a_script_invokes_the_seed( monkeypatch, capsys ):
    """
    Covers the `__main__` guard. psycopg2.connect is made to raise so the run reaches the
    connect-failure path and stops there — the module is executed for real, and no socket
    is opened.
    """
    import runpy

    def boom( **kw ): raise OSError( "patched: no database in a unit test" )
    monkeypatch.setattr( mod.psycopg2, "connect", boom )

    runpy.run_path( mod.__file__, run_name="__main__" )

    assert "Cannot connect" in capsys.readouterr().out


# ── The converge contract (the 2026-08-19 fix itself) ──

@pytest.mark.parametrize( "table,columns", [
    ( "INSERT INTO users",    [ "email", "password_hash", "email_verified", "is_active", "roles" ] ),
    ( "INSERT INTO api_keys", [ "key_hash", "description", "is_active" ] ),
] )
def test_both_upserts_CONVERGE_the_credential_columns_rather_than_DO_NOTHING( wired, table, columns ):
    """
    TIBERIUS 👑's TEST, sent verbatim. Reddens if either ON CONFLICT arm reverts to DO
    NOTHING, or stops refreshing any one credential column.

    This is the defect the script was rewritten for on 2026-08-19: create-only seeding froze
    the test row at whatever it was first given, so a password or key rotated in dev never
    reached test and :8000 returned 401 for credentials that worked on :7999 — while the seed
    reported success on every container start.

    Measured, and I reproduced the gap independently before taking his patch: reverting the
    users upsert to DO NOTHING SURVIVES my 20 tests at sha 277b0937b7bc. His four shas for the
    same family — 06afafb1f88b, e552fc8737cb, 50a2127fbb39, f9c81295be5e — are his measurement,
    not mine; I verified the class, he enumerated it.

    The fake cursor returns its scripted `xmax` whatever the SQL says, so no assertion over its
    OUTPUT can reach this — the conflict clause is observable only in the statement TEXT, which
    is how test_every_companion_is_marked_protected_TRUE already reads `is_protected = TRUE`.
    I had documented this as a ceiling of a unit test against a database script. It was not a
    ceiling; it was a seam I did not use. Documenting a gap is not closing one.
    """
    _all_companions( wired )
    wired[ "keys_by_email" ][ mod.SERVICE_ACCT ] = [ _key_row() ]

    mod.seed_if_missing()

    test_cur = wired[ "conns" ][ 1 ].cursor()
    sql      = next( s for s, _ in test_cur.executed if table in s )

    assert "ON CONFLICT ( id ) DO UPDATE SET" in sql, \
        "DO NOTHING freezes the test row at its first value — the 2026-08-19 defect"
    # Split the SET clause into whole assignments and compare each EXACTLY. A substring
    # check cannot do this job: "EXCLUDED.email" sits inside "EXCLUDED.email_verified",
    # so dropping the email assignment survives one, and so does pointing it at any
    # source column whose name STARTS WITH the right one.
    set_clause = " ".join( sql.split() ).split( "DO UPDATE SET ", 1 )[ 1 ]
    # RACHEL 🕊️: the clause ends at RETURNING *or* at a conditional WHERE, and an
    # assignment may be written with or without spaces around the equals. Both are valid
    # SQL that means what this test wants, and both used to REDDEN it — a false red, never
    # a false green, because a mis-split leaves no member matching the expected pair. Safe
    # direction, still worth removing: a test that reddens on a legitimate reformat trains
    # the next reader to weaken it.
    for terminator in ( "RETURNING", "WHERE" ):
        set_clause = set_clause.split( terminator )[ 0 ]
    assignments = { " = ".join( half.strip() for half in a.split( "=", 1 ) )
                    for a in set_clause.split( "," ) }
    for column in columns:
        assert f"{column} = EXCLUDED.{column}" in assignments, \
            f"'{column}' is never refreshed from dev, so a rotated value cannot reach test"


def test_the_users_INSERT_binds_each_parameter_to_the_column_that_NAMES_it( wired ):
    """
    CHLOÉ 🗼's finding. Every other assertion in this file reads the statement TEXT, and
    the text is identical whichever order the parameters are bound in. Swapping `email`
    and `pw_hash` in the tuple writes the password hash into the email column and leaves
    the SQL byte-for-byte unchanged — measured 2026-08-31, it SURVIVES the whole file at
    sha 3a0a397f2b0e, 22 passed.

    The seam was already here: the fake cursor records ( sql, params ) and two tests
    above read params by a hardcoded index. This binds them BY NAME, parsed out of the
    INSERT's own column list, so the assertion cannot drift when a column is added and
    an index silently means something else.

    `active=False` is deliberate. Every other field the fixture builds is distinct, but
    email_verified and is_active are both True by default — two equal values cannot
    reveal a swap between them, so the test would assert their sum and not their
    identity however it were named.
    """
    _all_companions( wired, active=False )
    mod.seed_if_missing()

    test_cur    = wired[ "conns" ][ 1 ].cursor()
    sql, params = next( ( s, p ) for s, p in test_cur.executed if "INSERT INTO users" in s )

    named   = " ".join( sql.split() ).split( "INSERT INTO users (", 1 )[ 1 ].split( ")", 1 )[ 0 ]
    columns = [ c.strip() for c in named.split( "," ) ]
    assert len( columns ) == len( params ), \
        f"{len( columns )} columns named but {len( params )} parameters bound"

    bound = dict( zip( columns, params ) )
    row   = wired[ "users_by_email" ][ mod.COMPANION_EMAILS[ 0 ] ]

    assert bound[ "id" ]             == row[ 0 ]
    assert bound[ "email" ]          == row[ 1 ], "the email column is not receiving the email"
    assert bound[ "password_hash" ]  == row[ 2 ], "the password_hash column is not receiving the hash"
    assert bound[ "created_at" ]     == row[ 3 ]
    assert bound[ "email_verified" ] == row[ 4 ]
    assert bound[ "is_active" ]      == row[ 5 ]
    # CHLOÉ 🗼: position 6 was covered only INCIDENTALLY — a swap touching it moved
    # created_at as well, and the two roles tests above read index 6 by hand. Both are
    # real, and both move if anyone renumbers. Naming it here makes the seventh column
    # carry its own assertion rather than inherit one.
    assert bound[ "roles" ]          == json.dumps( row[ 6 ] )


def test_the_api_keys_INSERT_binds_each_parameter_to_the_column_that_NAMES_it( wired ):
    """
    The same class as the users test above, on the other upsert — and it was open while
    that one was closed. TIBERIUS 👑 caught the gap from the NAME rather than the code:
    the first test was called `test_the_INSERT_…`, which claims both statements, and
    asserted only the users one. Swapping key_hash and description here writes the
    description into the key_hash column, leaves the SQL byte-identical, and SURVIVED the
    whole file at sha 10ecb3653ffb, 23 passed.

    A test whose name claims more than its assertions reach does not merely overstate —
    it tells the next reader the other half is covered, so nobody goes looking.

    _key_row's seven defaults are already pairwise distinct, so no fixture change is
    needed here; the users test needed active=False only because its two booleans were
    both True.
    """
    _all_companions( wired )
    wired[ "keys_by_email" ][ mod.SERVICE_ACCT ] = [ _key_row() ]

    mod.seed_if_missing()

    test_cur    = wired[ "conns" ][ 1 ].cursor()
    sql, params = next( ( s, p ) for s, p in test_cur.executed if "INSERT INTO api_keys" in s )

    named   = " ".join( sql.split() ).split( "INSERT INTO api_keys (", 1 )[ 1 ].split( ")", 1 )[ 0 ]
    columns = [ c.strip() for c in named.split( "," ) ]
    assert len( columns ) == len( params ), \
        f"{len( columns )} columns named but {len( params )} parameters bound"

    bound = dict( zip( columns, params ) )
    row   = _key_row()

    assert bound[ "id" ]           == row[ 0 ]
    assert bound[ "user_id" ]      == row[ 1 ]
    assert bound[ "key_hash" ]     == row[ 2 ], "the key_hash column is not receiving the key hash"
    assert bound[ "description" ]  == row[ 3 ], "the description column is not receiving the description"
    assert bound[ "is_active" ]    == row[ 4 ]
    assert bound[ "created_at" ]   == row[ 5 ]
    assert bound[ "last_used_at" ] == row[ 6 ]
