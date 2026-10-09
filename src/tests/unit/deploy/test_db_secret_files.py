"""
The provisioner makes and checks the compose secret files, the same way on every host.

Rick's condition: the sudo step is accepted only if it is replicated and automated.
These tests drive `cosa.utils.db_secret_files` and the `--secrets-dir` flag of `cosa.utils.db_roles`
against a scratch directory. Root is simulated by an injected `geteuid` and `chown`, so the unit tier
needs neither. The real file modes are real; only the owner is recorded.

The password never appears in a report, a check line or a dry run.
"""

import io
import os

import pytest

from cosa.utils import db_grants, db_roles, db_secret_files as sf

APP, HOST, TEST = "app-secret-aaaa", "host-secret-bbbb", "test-secret-cccc"
VALUES = { sf.APP_FILE: APP, sf.TEST_FILE: TEST }


class Owners:
    """A recording chown and an owner lookup that follows a file renamed into place."""
    def __init__( self ): self.owner = { }
    def chown( self, path, uid, gid ): self.owner[ path[ :-4 ] if path.endswith( ".new" ) else path ] = ( uid, gid )
    def of( self, path ): return self.owner.get( path, ( os.getuid(), os.getgid() ) )


@pytest.fixture
def owners( monkeypatch ):
    recorder = Owners()
    monkeypatch.setattr( sf, "_owner_of", recorder.of )
    return recorder


def _poke( path, text ):
    """Overwrite a secret file past its read-only mode, then put the mode back."""
    os.chmod( path, 0o640 )
    path.write_text( text )
    os.chmod( path, 0o440 )


def _write( directory, owners, values=None ):
    return sf.write_files( str( directory ), values or VALUES, geteuid=lambda: 0, chown=owners.chown )


def test_a_caller_that_is_not_root_is_refused_and_nothing_is_written( tmp_path, owners ):
    target = tmp_path / "secrets"
    with pytest.raises( PermissionError, match="needs root" ):
        sf.write_files( str( target ), VALUES, geteuid=lambda: 1000, chown=owners.chown )
    assert not target.exists(), "a refused run must not create the directory"


def test_the_first_run_makes_the_directory_and_both_files_with_the_right_mode_and_owner( tmp_path, owners ):
    target = tmp_path / "secrets"
    report = _write( target, owners )
    assert report == { sf.APP_FILE: "written", sf.TEST_FILE: "written" }
    assert oct( os.stat( target ).st_mode & 0o777 ) == oct( 0o750 ), "the directory must be 0750"
    assert owners.owner[ str( target ) ] == ( 0, 1002 )
    for name, password in VALUES.items():
        path = target / name
        assert path.read_text() == password + "\n", f"{name} holds the wrong content"
        assert oct( os.stat( path ).st_mode & 0o777 ) == oct( 0o440 ), f"{name} must be 0440"
        assert owners.owner[ str( path ) ] == ( 0, 1002 ), f"{name} must be root:1002"
    assert sorted( p.name for p in target.iterdir() ) == sorted( VALUES ), "a temporary file was left behind"


def test_a_second_run_changes_nothing( tmp_path, owners ):
    target = tmp_path / "secrets"
    _write( target, owners )
    before = { n: os.stat( target / n ).st_ino for n in VALUES }
    assert _write( target, owners ) == { sf.APP_FILE: "unchanged", sf.TEST_FILE: "unchanged" }
    assert { n: os.stat( target / n ).st_ino for n in VALUES } == before, "an unchanged file must not be rewritten"


@pytest.mark.parametrize( "damage", [ "content", "mode", "owner", "link" ] )
def test_a_wrong_file_is_repaired_and_reported( tmp_path, owners, damage ):
    target = tmp_path / "secrets"
    _write( target, owners )
    victim = target / sf.TEST_FILE
    if damage == "content": _poke( victim, "stale\n" )
    if damage == "mode": os.chmod( victim, 0o644 )
    if damage == "owner": owners.owner[ str( victim ) ] = ( 1000, 1000 )
    if damage == "link":
        other = tmp_path / "elsewhere"
        other.write_text( TEST + "\n" )
        os.chmod( other, 0o440 )                 # the target looks right in every way but being a link
        victim.unlink()
        victim.symlink_to( other )
    report = _write( target, owners )
    assert report == { sf.APP_FILE: "unchanged", sf.TEST_FILE: "repaired" }, f"damage {damage}: {report}"
    assert not victim.is_symlink() and victim.read_text() == TEST + "\n"
    assert oct( os.stat( victim ).st_mode & 0o777 ) == oct( 0o440 )
    assert owners.owner[ str( victim ) ] == ( 0, 1002 )


def test_a_file_that_cannot_be_read_counts_as_wrong( tmp_path, owners ):
    target = tmp_path / "secrets"
    _write( target, owners )
    os.chmod( target / sf.APP_FILE, 0o000 )
    if os.geteuid() == 0: pytest.skip( "root reads a mode 000 file, so there is nothing to refuse" )
    assert _write( target, owners )[ sf.APP_FILE ] == "repaired"


def test_the_owner_lookup_reads_the_real_uid_and_gid_without_following_a_link( tmp_path ):
    real = tmp_path / "real"
    real.write_text( "x" )
    link = tmp_path / "link"
    link.symlink_to( real )
    assert sf._owner_of( str( real ) ) == ( os.getuid(), os.getgid() )
    assert sf._owner_of( str( link ) ) == ( os.getuid(), os.getgid() ), "a link reports its own owner, and a dangling one must not raise"
    link.unlink()
    link.symlink_to( tmp_path / "nowhere" )
    assert sf._owner_of( str( link ) ) == ( os.getuid(), os.getgid() )


def test_a_file_with_the_right_mode_and_owner_that_fails_to_read_counts_as_wrong( tmp_path, owners, monkeypatch ):
    target = tmp_path / "secrets"
    _write( target, owners )
    def refuse( path ): raise PermissionError( "no" )
    monkeypatch.setattr( sf, "_read_text", refuse )
    assert sf._state( str( target / sf.APP_FILE ), APP, sf.GROUP_ID ) == "wrong"


def test_the_report_never_holds_a_password( tmp_path, owners ):
    report = _write( tmp_path / "secrets", owners )
    assert APP not in str( report ) and TEST not in str( report )


# ---- the read-only check ---------------------------------------------------------------------

def test_a_clean_directory_has_no_gap_and_a_note_when_values_are_not_given( tmp_path, owners ):
    target = tmp_path / "secrets"
    _write( target, owners )
    assert sf.check_files( str( target ), VALUES ) == ( [ ], [ ] )
    gaps, notes = sf.check_files( str( target ) )
    assert gaps == [ ] and any( "not compared" in n for n in notes ), f"notes: {notes}"


def test_every_kind_of_gap_is_named_with_its_file_and_one_remedy( tmp_path, owners ):
    target = tmp_path / "secrets"
    _write( target, owners )
    ( target / sf.APP_FILE ).unlink()                                               # absent
    victim = target / sf.TEST_FILE
    os.chmod( victim, 0o644 )                                                       # wrong mode
    owners.owner[ str( victim ) ] = ( 1000, 1000 )                                  # wrong owner
    gaps, _ = sf.check_files( str( target ), VALUES )
    text = "\n".join( gaps )
    assert f"{target / sf.APP_FILE} is absent" in text
    assert "has mode 0644, expected 0440" in text
    assert "is owned by 1000:1000, expected 0:1002" in text
    assert sum( line.startswith( "remedy:" ) for line in gaps ) == 1, "exactly one remedy line"
    assert APP not in text and TEST not in text


def test_a_link_an_empty_file_and_a_wrong_value_are_gaps( tmp_path, owners ):
    target = tmp_path / "secrets"
    target.mkdir()
    ( target / sf.APP_FILE ).symlink_to( tmp_path )
    empty = target / sf.TEST_FILE
    empty.write_text( "\n" )
    os.chmod( empty, 0o440 )
    owners.owner[ str( empty ) ] = ( 0, 1002 )
    gaps, _ = sf.check_files( str( target ), VALUES )
    assert any( "is a link" in g for g in gaps ) and any( "is empty" in g for g in gaps ), gaps
    _poke( empty, "other\n" )
    gaps, _ = sf.check_files( str( target ), VALUES )
    assert any( "does not hold the password of the given password file" in g for g in gaps ), gaps


def test_a_file_this_login_cannot_read_is_a_note_and_not_a_gap( tmp_path, owners ):
    if os.geteuid() == 0: pytest.skip( "root reads everything" )
    target = tmp_path / "secrets"
    _write( target, owners )
    for name in VALUES: os.chmod( target / name, 0o000 )
    owners_fix = { str( target / n ): ( 0, 1002 ) for n in VALUES }
    owners.owner.update( owners_fix )
    gaps, notes = sf.check_files( str( target ), VALUES )
    assert any( "cannot be read by this login" in n for n in notes ), notes
    assert not any( "does not hold" in g or "is empty" in g for g in gaps ), "an unreadable file must not be called wrong"


def test_the_wanted_pairs_name_exactly_the_two_files():
    assert sf.wanted( "a", "b" ) == { "db_app_password": "a", "db_test_password": "b" }
    assert sf.FILE_NAMES == ( "db_app_password", "db_test_password" )


# ---- the --secrets-dir flag of the provisioner -----------------------------------------------

@pytest.fixture
def pw( tmp_path ):
    out = { }
    for name, value in ( ( "app", APP ), ( "host", HOST ), ( "test", TEST ) ):
        path = tmp_path / f"{name}_pw"
        path.write_text( value + "\n" )
        out[ name ] = str( path )
    sql = tmp_path / "init.sql"
    sql.write_text( "SELECT 1;\n" )
    out[ "sql" ] = str( sql )
    return out


def _argv( pw, directory, *extra ):
    return [ "--app-pw-file", pw[ "app" ], "--host-pw-file", pw[ "host" ], "--test-pw-file", pw[ "test" ],
             "--psql", "docker exec -i x psql -U a -d lupin_db_dev", "--sql", pw[ "sql" ], "--secrets-dir", str( directory ), *extra ]


class Psql:
    def __init__( self, rc=0 ): self.calls, self.rc = [ ], rc
    def __call__( self, command, input, text ):
        self.calls.append( command )
        return type( "Done", (), { "returncode": self.rc } )()


def test_a_dry_run_lists_the_files_runs_nothing_and_prints_no_password( tmp_path, pw ):
    out, psql = io.StringIO(), Psql()
    assert db_roles.main( _argv( pw, tmp_path / "s" ), run_fn=psql, out=out, geteuid=lambda: 1000 ) == 0
    text = out.getvalue()
    assert "then, as root, in" in text and "db_app_password" in text and "db_test_password" in text
    assert psql.calls == [ ] and not ( tmp_path / "s" ).exists()
    assert APP not in text and TEST not in text and HOST not in text


def test_an_apply_without_root_is_refused_before_psql_runs( tmp_path, pw ):
    out, psql = io.StringIO(), Psql()
    assert db_roles.main( _argv( pw, tmp_path / "s", "--apply" ), run_fn=psql, out=out, geteuid=lambda: 1000 ) == 2
    assert "needs root" in out.getvalue() and psql.calls == [ ], "psql must not run when the files cannot be written"


def test_an_apply_as_root_runs_psql_first_then_writes_the_files( tmp_path, pw, owners ):
    order, out = [ ], io.StringIO()
    def psql( command, input, text ):
        order.append( "psql:" + str( os.path.isdir( tmp_path / "s" ) ) )
        return type( "Done", (), { "returncode": 0 } )()
    assert db_roles.main( _argv( pw, tmp_path / "s", "--apply" ), run_fn=psql, out=out, geteuid=lambda: 0, chown=owners.chown ) == 0
    assert order == [ "psql:False" ], f"psql must run before the directory exists: {order}"
    assert ( tmp_path / "s" / sf.APP_FILE ).read_text() == APP + "\n"
    assert ( tmp_path / "s" / sf.TEST_FILE ).read_text() == TEST + "\n"
    text = out.getvalue()
    assert "db_app_password: written" in text and "db_test_password: written" in text
    assert APP not in text and TEST not in text


def test_a_failed_psql_writes_no_secret_file( tmp_path, pw, owners ):
    psql = Psql( rc=3 )
    assert db_roles.main( _argv( pw, tmp_path / "s", "--apply" ), run_fn=psql, out=io.StringIO(), geteuid=lambda: 0, chown=owners.chown ) == 3
    assert not ( tmp_path / "s" ).exists(), "the files must follow a successful database run"


def test_apply_without_the_flag_writes_no_secret_file( tmp_path, pw, owners ):
    argv = [ a for a in _argv( pw, tmp_path / "s", "--apply" ) if a not in ( "--secrets-dir", str( tmp_path / "s" ) ) ]
    assert db_roles.main( argv, run_fn=Psql(), out=io.StringIO(), geteuid=lambda: 0, chown=owners.chown ) == 0
    assert not ( tmp_path / "s" ).exists()


@pytest.mark.parametrize( "flag", [ "--rollback", "--grants-only", "--drop-template", "--reassign" ] )
def test_the_flag_is_refused_with_the_partial_runs( tmp_path, pw, flag ):
    with pytest.raises( SystemExit ): db_roles.main( _argv( pw, tmp_path / "s", flag ), run_fn=Psql(), out=io.StringIO() )


@pytest.fixture
def grants_clean( monkeypatch ):
    monkeypatch.setattr( db_grants, "check_with_psql", lambda *a, **k: ( 0, [ "grants ok" ] ) )


def test_the_check_adds_the_files_and_exits_one_on_a_gap( tmp_path, pw, grants_clean ):
    out = io.StringIO()
    argv = [ "--psql", "x", "--check", "--secrets-dir", str( tmp_path / "missing" ) ]
    assert db_roles.main( argv, run_fn=Psql(), out=out ) == 1
    assert "is absent" in out.getvalue() and "grants ok" in out.getvalue()


def test_the_check_is_clean_when_the_files_are_right_and_compares_the_content_when_given( tmp_path, pw, grants_clean, owners ):
    _write( tmp_path / "s", owners )
    out = io.StringIO()
    argv = [ "--psql", "x", "--check", "--secrets-dir", str( tmp_path / "s" ), "--app-pw-file", pw[ "app" ], "--test-pw-file", pw[ "test" ] ]
    assert db_roles.main( argv, run_fn=Psql(), out=out ) == 0, out.getvalue()
    _poke( tmp_path / "s" / sf.TEST_FILE, "changed\n" )
    out = io.StringIO()
    assert db_roles.main( argv, run_fn=Psql(), out=out ) == 1
    assert "does not hold the password" in out.getvalue()


def test_the_check_with_a_bad_password_file_exits_two( tmp_path, pw, grants_clean ):
    ( tmp_path / "app_pw" ).write_text( "" )
    out = io.StringIO()
    argv = [ "--psql", "x", "--check", "--secrets-dir", str( tmp_path ), "--app-pw-file", pw[ "app" ], "--test-pw-file", pw[ "test" ] ]
    assert db_roles.main( argv, run_fn=Psql(), out=out ) == 2
    assert "is empty" in out.getvalue()


def test_a_check_without_the_flag_does_not_touch_the_files( tmp_path, grants_clean ):
    out = io.StringIO()
    assert db_roles.main( [ "--psql", "x", "--check" ], run_fn=Psql(), out=out ) == 0
    assert "secret file" not in out.getvalue()
