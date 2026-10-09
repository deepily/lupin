"""
The root-owned installer of the test login's secret files.

The script is copied by hand to a root-owned place and run through sudo with no arguments.
These tests drive it against a scratch directory. Root, the owner lookups and chown are injected.
"""

import ast
import importlib.util
import io
import os
import types

import pytest

import cosa.utils.util as cu
from cosa.utils import db_secret_files as sf

SCRIPT = os.path.join( cu.get_project_root(), "src/scripts/lupin_install_db_secrets.py" )
spec   = importlib.util.spec_from_file_location( "lupin_install_db_secrets", SCRIPT )
ids    = importlib.util.module_from_spec( spec )
spec.loader.exec_module( ids )

UID = os.getuid()
REAL_OWNER_OF = ids._owner_of


class Chowns:
    """A recording chown."""
    def __init__( self ): self.calls = [ ]
    def __call__( self, path, uid, gid ): self.calls.append( ( path, uid, gid ) )


def _stat( uid=0, mode=0o100755, folder_uid=0, folder_mode=0o040755 ):
    """A stat stand-in: the file first, then its directory."""
    def stat_fn( path ):
        if path.endswith( "-copy" ): return types.SimpleNamespace( st_uid=uid, st_mode=mode )
        return types.SimpleNamespace( st_uid=folder_uid, st_mode=folder_mode )
    return stat_fn


@pytest.fixture
def world( tmp_path ):
    """A scratch secrets directory, a home with the source, and the injected pieces."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    app = secrets / "db_app_password"
    app.write_text( "app-pw\n" )
    home = tmp_path / "home"
    ( home / ".lupin" ).mkdir( parents=True )
    source = home / ".lupin" / "db_test_pw"
    source.write_text( "test-pw\n" )
    source.chmod( 0o600 )
    chown = Chowns()
    def run( argv=None, env=None, euid=0, stat_fn=None, self_path="/usr/local/sbin/lupin-install-db-secrets-copy" ):
        out = io.StringIO()
        code = ids.main( argv or [ "prog" ], env if env is not None else { "SUDO_UID": str( UID ) }, geteuid=lambda: euid,
                         self_path=self_path, directory=str( secrets ), chown_fn=chown,
                         stat_fn=stat_fn or _stat(), lookup_fn=lambda uid: types.SimpleNamespace( pw_dir=str( home ) ), out=out )
        return code, out.getvalue()
    return types.SimpleNamespace( secrets=secrets, app=app, source=source, home=home, chown=chown, run=run )


@pytest.fixture( autouse=True )
def real_path_is_the_given_path( monkeypatch, world ):
    """Resolve the fake copy path to itself and report owners as the recording chown saw them."""
    monkeypatch.setattr( ids.os.path, "realpath", lambda p: p )
    def owner_of( path ):
        seen = [ c for c in world.chown.calls if c[ 0 ] == path or c[ 0 ] == path + ".new" ]
        return ( seen[ -1 ][ 1 ], seen[ -1 ][ 2 ] ) if seen else ( UID, UID )
    monkeypatch.setattr( ids, "_owner_of", owner_of )


def test_the_constants_match_the_repository_module_they_mirror():
    assert ( ids.SECRETS_DIR, ids.GROUP_ID, ids.FILE_MODE, ids.DIR_MODE, ids.APP_FILE, ids.TEST_FILE ) == \
           ( sf.DEFAULT_DIR, sf.GROUP_ID, sf.MODE, sf.DIR_MODE, sf.APP_FILE, sf.TEST_FILE )


def test_the_script_imports_only_the_standard_library():
    tree = ast.parse( open( SCRIPT ).read() )
    names = { a.name.split( "." )[ 0 ] for n in ast.walk( tree ) if isinstance( n, ast.Import ) for a in n.names }
    names |= { n.module.split( "." )[ 0 ] for n in ast.walk( tree ) if isinstance( n, ast.ImportFrom ) }
    assert names == { "os", "pwd", "stat", "sys" }, f"a root script imported {sorted( names )}"


def test_the_shebang_isolates_the_interpreter_from_the_environment():
    assert open( SCRIPT ).readline().strip() == "#!/usr/bin/python3 -I"


def test_the_first_run_writes_the_test_file_and_repairs_the_app_file( world ):
    world.app.chmod( 0o644 )
    code, out = world.run()
    assert code == 0, out
    test_file = world.secrets / "db_test_password"
    assert test_file.read_text() == "test-pw\n" and oct( test_file.stat().st_mode & 0o777 ) == "0o440"
    assert oct( world.app.stat().st_mode & 0o777 ) == "0o440" and world.app.read_text() == "app-pw\n"
    assert "db_test_password: written" in out and "db_app_password: repaired" in out
    assert "test-pw" not in out and "app-pw" not in out
    assert ( str( world.app ), 0, 1002 ) in world.chown.calls and ( str( world.secrets ), 0, 1002 ) in world.chown.calls


def test_a_second_run_changes_nothing( world ):
    world.run()
    before = len( world.chown.calls )
    code, out = world.run()
    assert code == 0 and "db_test_password: unchanged" in out and "db_app_password: unchanged" in out
    assert not any( c[ 0 ].endswith( ".new" ) for c in world.chown.calls[ before: ] ), "a second run rewrote the file"


def test_a_wrong_test_file_is_replaced_and_a_planted_temp_link_is_not_followed( world, tmp_path ):
    victim = tmp_path / "victim"
    victim.write_text( "keep\n" )
    ( world.secrets / "db_test_password" ).write_text( "stale\n" )
    os.symlink( victim, world.secrets / "db_test_password.new" )
    code, out = world.run()
    assert code == 0 and "db_test_password: repaired" in out
    assert victim.read_text() == "keep\n" and ( world.secrets / "db_test_password" ).read_text() == "test-pw\n"


def test_an_argument_is_refused_before_anything_is_checked_or_written( world ):
    code, out = world.run( argv=[ "prog", "--apply" ] )
    assert code == 2 and "takes no arguments" in out and not ( world.secrets / "db_test_password" ).exists()


@pytest.mark.parametrize( "kwargs, code, word", [
    ( dict( uid=1000 ),              10, "not root" ),
    ( dict( mode=0o100775 ),         11, "0775" ),
    ( dict( mode=0o100700 ),         11, "0700" ),
    ( dict( folder_uid=1000 ),       13, "not root's alone" ),
    ( dict( folder_mode=0o040775 ),  13, "not root's alone" ),
    ( dict( folder_mode=0o040757 ),  13, "not root's alone" ),
] )
def test_a_copy_with_the_wrong_owner_mode_or_directory_is_refused_and_writes_nothing( world, kwargs, code, word ):
    got, out = world.run( stat_fn=_stat( **kwargs ) )
    assert got == code and word in out, out
    assert not ( world.secrets / "db_test_password" ).exists() and world.chown.calls == [ ]


def test_a_copy_reached_through_a_link_is_refused( world, monkeypatch ):
    monkeypatch.setattr( ids.os.path, "realpath", lambda p: "/somewhere/else" )
    assert world.run()[ 0 ] == 14
    monkeypatch.setattr( ids.os.path, "realpath", lambda p: p )
    assert world.run( stat_fn=_stat( mode=0o120777 ) )[ 0 ] == 14


def test_a_caller_that_is_not_root_is_refused( world ):
    code, out = world.run( euid=1000 )
    assert code == 12 and "must run as root" in out and not ( world.secrets / "db_test_password" ).exists()


@pytest.mark.parametrize( "env", [ { }, { "SUDO_UID": "abc" }, { "SUDO_UID": "0" } ] )
def test_a_run_not_through_sudo_from_an_account_is_refused( world, env ):
    assert world.run( env=env )[ 0 ] == 15


def test_a_uid_with_no_account_is_refused( world ):
    out = io.StringIO()
    def nobody( uid ): raise KeyError( uid )
    code = ids.main( [ "prog" ], { "SUDO_UID": "4242" }, geteuid=lambda: 0, self_path="/x-copy", directory=str( world.secrets ),
                     chown_fn=world.chown, stat_fn=_stat(), lookup_fn=nobody, out=out )
    assert code == 15


def test_an_unsafe_source_is_refused( world, tmp_path ):
    world.source.chmod( 0o666 )
    assert world.run()[ 0 ] == 16
    world.source.chmod( 0o600 )
    world.source.write_text( "\n" )
    assert world.run()[ 0 ] == 16
    world.source.unlink()
    target = tmp_path / "elsewhere"
    target.write_text( "secret\n" )
    target.chmod( 0o600 )   # safe in every way except that it is reached through a link
    os.symlink( target, world.source )
    code, out = world.run()
    assert code == 16 and not ( world.secrets / "db_test_password" ).exists()


def test_a_source_owned_by_someone_else_is_refused( world ):
    assert world.run( env={ "SUDO_UID": str( UID + 1 ) } )[ 0 ] == 16


def test_a_source_that_is_not_a_regular_file_is_refused( world ):
    world.source.unlink()
    world.source.mkdir()
    assert world.run()[ 0 ] == 16


@pytest.mark.parametrize( "make", [ "absent", "empty", "link" ] )
def test_the_app_file_must_exist_first( world, tmp_path, make ):
    world.app.unlink()
    if make == "empty": world.app.write_text( "" )
    if make == "link":
        real = tmp_path / "real-app"
        real.write_text( "x\n" )
        os.symlink( real, world.app )
    code, out = world.run()
    assert code == 17 and not ( world.secrets / "db_test_password" ).exists()


def test_a_missing_directory_is_made_with_the_right_mode_and_group( world, tmp_path ):
    fresh = tmp_path / "fresh"
    out = io.StringIO()
    code = ids.main( [ "prog" ], { "SUDO_UID": str( UID ) }, geteuid=lambda: 0, self_path="/x-copy", directory=str( fresh ),
                     chown_fn=world.chown, stat_fn=_stat(), lookup_fn=lambda u: types.SimpleNamespace( pw_dir=str( world.home ) ), out=out )
    assert code == 17 and oct( fresh.stat().st_mode & 0o777 ) == "0o750", out.getvalue()
    assert ( str( fresh ), 0, 1002 ) in world.chown.calls


def test_the_real_owner_lookup_reads_the_file_system( tmp_path ):
    plain = tmp_path / "plain"
    plain.write_text( "x" )
    assert REAL_OWNER_OF( str( plain ) ) == ( os.getuid(), os.getgid() )
