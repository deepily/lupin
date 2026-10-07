"""
`cosa.utils.db_roles` — the provisioner for the approval-settings guard rail's three roles
(row 80513825). The SQL it feeds psql was also run twice against a throwaway Postgres 16
(pgvector image) and each privilege tried as each role; that run is recorded in
io/findings-80513825.md and is not repeated here because the unit tier has no database.

What is asserted here is the part that carries a secret: the passwords reach psql on STDIN and
nowhere else, a dry run never prints one, a dry run runs nothing, and a bad file stops the run
before any command is built.
"""

import io
import os

import pytest

from cosa.utils import db_roles

APP, HOST, TEST = "app-secret-aaaa", "host-secret-bbbb", "test-secret-cccc"


@pytest.fixture
def files( tmp_path ):
    paths = {}
    for name, value in ( ( "app", APP ), ( "host", HOST ), ( "test", TEST ) ):
        path = tmp_path / f"{name}_pw"
        path.write_text( value + "\n" )
        paths[ name ] = str( path )
    sql = tmp_path / "init-db-roles.sql"
    sql.write_text( "SELECT 1;\nSELECT 2;\n" )
    paths[ "sql" ] = str( sql )
    return paths


def _argv( files, *extra ):
    return [ "--app-pw-file", files[ "app" ], "--host-pw-file", files[ "host" ], "--test-pw-file", files[ "test" ],
             "--psql", "docker exec -i some-postgres psql -U admin -d lupin_db_dev", "--sql", files[ "sql" ], *extra ]


class Recorder:
    def __init__( self, returncode=0 ):
        self.calls, self.returncode = [], returncode
    def __call__( self, command, input, text ):
        self.calls.append( ( command, input, text ) )
        return type( "Done", (), { "returncode": self.returncode } )()


def test_read_secret_strips_whitespace( tmp_path ):
    path = tmp_path / "s"
    path.write_text( "  value-1 \n" )
    assert db_roles.read_secret( str( path ) ) == "value-1"


@pytest.mark.parametrize( "content,why", [ ( "", "is empty" ), ( "a'b", "quote" ), ( "a\\b", "backslash" ), ( "a\nb", "newline" ) ] )
def test_read_secret_refuses_empty_and_unsafe_values( tmp_path, content, why ):
    path = tmp_path / "s"
    path.write_text( content )
    with pytest.raises( ValueError, match=why ): db_roles.read_secret( str( path ) )


def test_read_secret_names_a_missing_file( tmp_path ):
    with pytest.raises( ValueError, match="could not be read: FileNotFoundError" ):
        db_roles.read_secret( str( tmp_path / "absent" ) )


def test_the_stdin_carries_the_three_passwords_the_flag_and_the_sql():
    text = db_roles.build_psql_stdin( APP, HOST, TEST, "SELECT 1;\n", reassign=True )
    assert text.splitlines() == [
        f"\\set app_pw  '{APP}'", f"\\set host_pw '{HOST}'", f"\\set test_pw '{TEST}'",
        "\\set reassign 1", "SELECT 1;",
    ]
    assert db_roles.build_psql_stdin( APP, HOST, TEST, "SELECT 1;" ).count( "reassign" ) == 0


def test_the_redacted_stdin_holds_no_password_and_says_how_much_sql_follows():
    text = db_roles.build_psql_stdin( APP, HOST, TEST, "a\nb\nc\n", redact=True )
    assert not any( secret in text for secret in ( APP, HOST, TEST ) )
    assert "<redacted>" in text and "3 lines of init-db-roles.sql" in text


def test_a_dry_run_prints_the_plan_runs_nothing_and_leaks_no_password( files ):
    out, run = io.StringIO(), Recorder()
    rc = db_roles.main( _argv( files ), run_fn=run, out=out )
    printed = out.getvalue()
    assert rc == 0 and run.calls == [], "a dry run executed something"
    assert "DRY RUN" in printed and "docker exec -i some-postgres psql -U admin -d lupin_db_dev -v ON_ERROR_STOP=1 -q" in printed
    assert not any( secret in printed for secret in ( APP, HOST, TEST ) ), "a dry run printed a password"


def test_apply_runs_psql_with_the_passwords_on_stdin_and_not_in_the_command( files ):
    run = Recorder()
    rc  = db_roles.main( _argv( files, "--apply", "--reassign" ), run_fn=run, out=io.StringIO() )
    ( command, stdin, text ), = run.calls
    assert rc == 0 and text is True
    assert command[ :6 ] == [ "docker", "exec", "-i", "some-postgres", "psql", "-U" ]
    assert not any( secret in " ".join( command ) for secret in ( APP, HOST, TEST ) ), "a password reached argv"
    assert f"'{APP}'" in stdin and "\\set reassign 1" in stdin and "SELECT 2;" in stdin


def test_apply_returns_psqls_exit_code( files ):
    assert db_roles.main( _argv( files, "--apply" ), run_fn=Recorder( returncode=3 ), out=io.StringIO() ) == 3


def test_a_bad_password_file_stops_before_any_command( files, tmp_path ):
    ( tmp_path / "app_pw" ).write_text( "" )
    out, run = io.StringIO(), Recorder()
    rc = db_roles.main( _argv( files, "--apply" ), run_fn=run, out=out )
    assert rc == 2 and run.calls == [] and "is empty" in out.getvalue()


def test_an_unreadable_sql_file_stops_before_any_command( files, tmp_path ):
    out, run = io.StringIO(), Recorder()
    argv = _argv( files, "--apply" )
    argv[ argv.index( "--sql" ) + 1 ] = str( tmp_path / "absent.sql" )
    rc = db_roles.main( argv, run_fn=run, out=out )
    assert rc == 2 and run.calls == [] and "SQL file" in out.getvalue()


def test_the_sql_path_defaults_to_the_one_under_lupin_root( files, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", os.environ[ "LUPIN_ROOT" ] )
    argv = [ a for a in _argv( files ) if a != files[ "sql" ] ]
    argv.remove( "--sql" )
    out = io.StringIO()
    assert db_roles.main( argv, run_fn=Recorder(), out=out ) == 0
    assert "lines of init-db-roles.sql" in out.getvalue()


def test_the_shipped_sql_has_the_three_guards_the_scratch_run_proved():
    """A cheap pin that the file still says what the privilege tests were run against."""
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], db_roles.SQL_RELATIVE_PATH )
    text = open( path ).read()
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON approval_settings FROM lupin_host" in text
    assert "REVOKE CONNECT ON DATABASE lupin_db_dev  FROM PUBLIC" in text
    assert "REASSIGN OWNED" not in text.replace( "-- NOT `REASSIGN OWNED BY lupin_dev`", "" ), \
        "REASSIGN OWNED BY the bootstrap superuser fails on a real database; each object is moved by name"
    for variable in ( "app_pw", "host_pw", "test_pw" ):
        assert f":{{?{variable}}}" in text, f"{variable} may be forgotten without stopping the run"


# ---- --rollback: the reassign in reverse -------------------------------------------------

SQL_PATH = os.path.join( os.environ[ "LUPIN_ROOT" ], db_roles.SQL_RELATIVE_PATH )


def _block( text, opener ):
    """The lines between an opener line and the next `\\endif`, with comment lines removed."""
    lines = text.splitlines()
    start = next( i for i, line in enumerate( lines ) if line.strip() == opener )
    end   = next( i for i in range( start + 1, len( lines ) ) if lines[ i ].strip() == "\\endif" )
    return [ line.strip() for line in lines[ start + 1:end ] if line.strip() and not line.strip().startswith( "--" ) ]


def _swap_roles( text ):
    return text.replace( "lupin_dev", "\0" ).replace( "lupin_app", "lupin_dev" ).replace( "\0", "lupin_app" )


def test_the_stdin_for_a_rollback_carries_one_flag_the_sql_and_no_password():
    text = db_roles.build_psql_stdin( APP, HOST, TEST, "SELECT 1;\n", rollback=True )
    assert text.splitlines() == [ "\\set rollback 1", "SELECT 1;" ]
    assert not any( secret in text for secret in ( APP, HOST, TEST ) ) and "app_pw" not in text


def test_a_rollback_dry_run_prints_the_plan_runs_nothing_and_reads_no_password_file( files, tmp_path ):
    ( tmp_path / "app_pw" ).write_text( "" )
    out, run = io.StringIO(), Recorder()
    rc = db_roles.main( _argv( files, "--rollback" ), run_fn=run, out=out )
    assert rc == 0 and run.calls == [], "a dry run executed something, or an empty password file was read"
    assert "DRY RUN" in out.getvalue() and "\\set rollback 1" in out.getvalue()


def test_a_rollback_apply_sends_the_flag_and_the_sql_and_never_a_password( files, tmp_path ):
    ( tmp_path / "app_pw" ).write_text( "" )                        # unreadable as a password; --rollback must not care
    run = Recorder()
    rc  = db_roles.main( _argv( files, "--apply", "--rollback" ), run_fn=run, out=io.StringIO() )
    ( command, stdin, text ), = run.calls
    assert rc == 0 and text is True
    assert stdin.splitlines()[ 0 ] == "\\set rollback 1" and "SELECT 2;" in stdin
    assert "app_pw" not in stdin and "host_pw" not in stdin and "test_pw" not in stdin and "reassign" not in stdin
    assert not any( secret in stdin + " ".join( command ) for secret in ( APP, HOST, TEST ) )


def test_a_rollback_runs_with_no_password_file_options_at_all( files ):
    argv = [ "--psql", "psql -U admin -d lupin_db_dev", "--sql", files[ "sql" ], "--apply", "--rollback" ]
    run  = Recorder( returncode=5 )
    assert db_roles.main( argv, run_fn=run, out=io.StringIO() ) == 5
    assert len( run.calls ) == 1 and run.calls[ 0 ][ 1 ].startswith( "\\set rollback 1\n" )


def test_without_a_rollback_all_three_password_files_are_still_required( files ):
    argv = [ "--psql", "psql", "--sql", files[ "sql" ], "--app-pw-file", files[ "app" ], "--host-pw-file", files[ "host" ] ]
    run  = Recorder()
    with pytest.raises( SystemExit ) as stopped: db_roles.main( argv, run_fn=run, out=io.StringIO() )
    assert stopped.value.code == 2 and run.calls == []


def test_a_rollback_and_a_reassign_together_are_refused_before_anything_runs( files ):
    run = Recorder()
    with pytest.raises( SystemExit ) as stopped:
        db_roles.main( _argv( files, "--apply", "--rollback", "--reassign" ), run_fn=run, out=io.StringIO() )
    assert stopped.value.code == 2 and run.calls == []


def test_the_rollback_block_is_the_reassign_block_with_only_the_two_role_names_swapped():
    text      = open( SQL_PATH ).read()
    reassign  = _block( text, "\\if :{?reassign}" )
    rollback  = _block( text, "\\if :{?rollback}" )
    only_here = ( "\\connect lupin_db_dev", "\\quit" )
    rollback  = [ line for line in rollback if line not in only_here and not line.startswith( "SET log_" ) ]
    joined_reassign = " ".join( reassign )
    joined_rollback = " ".join( rollback )
    assert joined_reassign.count( "\\gexec" ) == 4, "the reassign block no longer has its four generated statements"
    assert "ALTER SCHEMA public OWNER TO lupin_app;" in joined_reassign
    assert _swap_roles( joined_rollback ) == joined_reassign


def test_the_rollback_block_touches_no_role_password_or_grant_and_ends_the_session():
    text     = open( SQL_PATH ).read()
    rollback = "\n".join( _block( text, "\\if :{?rollback}" ) ).upper()
    for word in ( "GRANT", "REVOKE", "CREATE ROLE", "ALTER ROLE", "DROP ROLE", "PASSWORD", "DEFAULT PRIVILEGES", "REASSIGN OWNED" ):
        assert word not in rollback, f"the rollback block mentions {word}"
    assert rollback.rstrip().endswith( "\\QUIT" ), "the rollback block must end the session so nothing below it runs"
    code   = "\n".join( line for line in text.splitlines() if not line.strip().startswith( "--" ) )
    opener = code.index( "\\if :{?rollback}" )
    for later in ( "CREATE ROLE", "ALTER ROLE", "GRANT ", "REVOKE ", ":{?app_pw}" ):
        assert code.index( later ) > opener, f"{later} comes before the rollback block, so a rollback would reach it"
