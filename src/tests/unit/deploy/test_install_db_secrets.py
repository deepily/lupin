"""
The one-command installer of the test login's secret files.

These tests drive it against a scratch tree. Root, the account lookup, chown, visudo and the final run are
injected; the real sudo and visudo are proved in src/tests/smoke/test_install_db_secrets_real_sudo.py.
"""

import importlib.util
import io
import os
import sys
import types

import pytest

import cosa.utils.util as cu

SCRIPT  = os.path.join( cu.get_project_root(), "src/scripts/install_db_secrets.py" )
PAYLOAD = os.path.join( cu.get_project_root(), "src/scripts/lupin_install_db_secrets.py" )
spec    = importlib.util.spec_from_file_location( "install_db_secrets", SCRIPT )
ids     = importlib.util.module_from_spec( spec )
spec.loader.exec_module( ids )

SAMPLE_TEXT = "test-pw"


class Runner:
    """A recording stand-in for the command runner; a code per command word can be set."""
    def __init__( self ):
        self.calls = [ ]
        self.codes = { }
        self.seen  = [ ]
    def __call__( self, command, env=None ):
        self.calls.append( command )
        for word, ( code, text ) in self.codes.items():
            if word in command: return code, text
        return 0, "ok"


class Chowns:
    """A recording chown."""
    def __init__( self ): self.calls = [ ]
    def __call__( self, path, uid, gid ): self.calls.append( ( path, uid, gid ) )


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A scratch host: payload, secrets directory, operator home and injected root."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    ( secrets / "db_app_password" ).write_text( "app\n" )
    home = tmp_path / "home"
    ( home / ".lupin" ).mkdir( parents=True )
    source = home / ".lupin" / "db_test_pw"
    source.write_text( SAMPLE_TEXT + "\n" )
    source.chmod( 0o600 )
    ( tmp_path / "sbin" ).mkdir()
    ( tmp_path / "sudoers.d" ).mkdir()
    runner = Runner()
    chowns = Chowns()
    out    = io.StringIO()
    lookup = lambda uid: types.SimpleNamespace( pw_name="op", pw_dir=str( home ) )
    host   = ids.Host( geteuid=lambda: 0, lookup=lookup, which=lambda name: "/usr/sbin/visudo", runner=runner,
                       chown=chowns, out=out, payload_path=PAYLOAD, copy_path=str( tmp_path / "sbin/copy" ),
                       sudoers_path=str( tmp_path / "sudoers.d/lupin-x" ), secrets_dir=str( secrets ), python="/py" )
    env    = { "SUDO_UID": str( os.getuid() ), "SUDO_USER": "op" }
    real   = ids.owner_and_mode
    def fake_owner( path ):
        uid, gid, mode = real( path )
        return 0, ( 1002 if str( secrets ) in path else 0 ), mode
    monkeypatch.setattr( ids, "owner_and_mode", fake_owner )
    return types.SimpleNamespace( host=host, env=env, runner=runner, chowns=chowns, out=out, secrets=secrets,
                                  source=source, tmp=tmp_path )


def _finish_secrets( world ):
    """Make db_test_password the way the installed copy would: the password, mode 0440."""
    for name, text in ( ( "db_app_password", "app\n" ), ( "db_test_password", SAMPLE_TEXT + "\n" ) ):
        path = world.secrets / name
        path.write_text( text )
        path.chmod( 0o440 )


# ── small pieces ─────────────────────────────────────────────────────────────

def test_sudoers_line_names_the_one_file_and_forbids_arguments():
    assert ids.sudoers_line( "op", "/x/y" ) == 'op ALL=(root) NOPASSWD: /x/y ""\n'


def test_sha256_and_owner_and_mode_read_the_real_thing( tmp_path ):
    path = tmp_path / "f"
    path.write_bytes( b"abc" )
    path.chmod( 0o640 )
    assert ids.sha256_of( b"abc" ) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert ids.owner_and_mode( str( path ) ) == ( os.getuid(), os.getgid(), 0o640 )


def test_run_command_joins_both_streams():
    code, text = ids.run_command( [ sys.executable, "-c", "import sys; print('a'); print('b', file=sys.stderr); sys.exit(3)" ] )
    assert code == 3 and "a" in text and "b" in text


def test_host_rejects_an_unknown_setting_and_defaults_to_the_real_places():
    with pytest.raises( TypeError ): ids.Host( nonsense=1 )
    real = ids.Host()
    assert real.copy_path == "/usr/local/sbin/lupin-install-db-secrets"
    assert real.sudoers_path == "/etc/sudoers.d/lupin-install-db-secrets"
    assert real.secrets_dir == "/etc/lupin/secrets"
    assert real.payload_path.endswith( "src/scripts/lupin_install_db_secrets.py" )


def test_the_names_agree_with_the_payload_and_the_runbook():
    payload = ids.load_payload( PAYLOAD )
    assert ids.SECRETS_DIR == payload.SECRETS_DIR
    assert ids.COPY_MODE == payload.SELF_MODE
    assert ids.COPY_PATH.endswith( "lupin-install-db-secrets" )
    assert ids.SUDOERS_PATH.endswith( "lupin-install-db-secrets" )


# ── preflight: each refusal, and nothing changed ─────────────────────────────

def _nothing_changed( world ):
    assert not os.path.lexists( world.host.copy_path )
    assert not os.path.lexists( world.host.sudoers_path )
    assert world.runner.calls == [ ]
    assert world.chowns.calls == [ ]


def _refusal( world, code, env=None ):
    with pytest.raises( ids.Refusal ) as caught:
        ids.preflight( world.env if env is None else env, world.host )
    assert caught.value.code == code
    _nothing_changed( world )
    return str( caught.value )


def test_preflight_passes_and_returns_the_facts( world ):
    facts = ids.preflight( world.env, world.host )
    assert facts[ "user" ] == "op"
    assert facts[ "payload_bytes" ] == open( PAYLOAD, "rb" ).read()
    assert facts[ "visudo" ] == "/usr/sbin/visudo"
    _nothing_changed( world )


def test_refuses_when_not_root( world ):
    world.host.geteuid = lambda: 1000
    assert "root" in _refusal( world, 20 )


@pytest.mark.parametrize( "env", [
    { },
    { "SUDO_UID": "notanumber", "SUDO_USER": "op" },
    { "SUDO_UID": "0", "SUDO_USER": "root" },
    { "SUDO_UID": str( os.getuid() ), "SUDO_USER": "somebody-else" },
    { "SUDO_UID": str( os.getuid() ) },
] )
def test_refuses_without_a_sudo_operator_whose_name_agrees( world, env ):
    _refusal( world, 21, env )


def test_refuses_root_s_own_shell_even_when_the_name_agrees( world ):
    env = { "SUDO_UID": "0", "SUDO_USER": "op" }
    assert "not from root's own shell" in _refusal( world, 21, env )


def test_refuses_a_name_that_cannot_go_into_a_sudoers_line( world ):
    world.host.lookup = lambda uid: types.SimpleNamespace( pw_name="Bad Name\nx", pw_dir="/" )
    env = { "SUDO_UID": str( os.getuid() ), "SUDO_USER": "Bad Name\nx" }
    assert "sudoers line" in _refusal( world, 21, env )


def test_refuses_a_missing_or_linked_payload( world, tmp_path ):
    world.host.payload_path = str( tmp_path / "nope.py" )
    _refusal( world, 22 )
    link = tmp_path / "link.py"
    link.symlink_to( PAYLOAD )
    world.host.payload_path = str( link )
    _refusal( world, 22 )


def test_refuses_without_visudo( world ):
    world.host.which = lambda name: None
    _refusal( world, 23 )


def test_refuses_a_bad_source_with_the_payloads_own_code( world ):
    world.source.chmod( 0o666 )
    _refusal( world, 16 )


@pytest.mark.parametrize( "how", [ "missing", "empty", "link" ] )
def test_refuses_a_bad_app_file_before_any_change( world, how ):
    app = world.secrets / "db_app_password"
    app.unlink()
    if how == "empty": app.write_text( "" )
    if how == "link":
        target = world.tmp / "elsewhere"
        target.write_text( "x" )
        app.symlink_to( target )
    _refusal( world, 17 )


# ── write_file ───────────────────────────────────────────────────────────────

def test_write_file_written_unchanged_repaired( world, tmp_path ):
    path = str( tmp_path / "f" )
    assert ids.write_file( path, b"one", 0o755, world.host ) == "written"
    assert oct( os.stat( path ).st_mode & 0o7777 ) == "0o755"
    assert ids.write_file( path, b"one", 0o755, world.host ) == "unchanged"
    assert ids.write_file( path, b"two", 0o755, world.host ) == "repaired"
    assert open( path, "rb" ).read() == b"two"
    os.chmod( path, 0o600 )
    assert ids.write_file( path, b"two", 0o755, world.host ) == "repaired"
    assert world.chowns.calls[ 0 ] == ( path + ".new", 0, 0 )


def test_write_file_replaces_a_link_and_a_stale_temporary( world, tmp_path ):
    target = tmp_path / "target"
    target.write_text( "keep me" )
    path = tmp_path / "f"
    path.symlink_to( target )
    ( tmp_path / "f.new" ).write_text( "stale" )
    assert ids.write_file( str( path ), b"new", 0o755, world.host ) == "repaired"
    assert not path.is_symlink() and path.read_bytes() == b"new"
    assert target.read_text() == "keep me"


# ── the three steps ──────────────────────────────────────────────────────────

def test_install_copy_puts_the_payload_bytes_at_the_copy_path( world ):
    facts = ids.preflight( world.env, world.host )
    assert ids.install_copy( facts, world.host ) == "written"
    assert open( world.host.copy_path, "rb" ).read() == open( PAYLOAD, "rb" ).read()
    assert ids.install_copy( facts, world.host ) == "unchanged"


def test_sudoers_is_checked_before_it_is_installed_and_again_after( world ):
    facts = ids.preflight( world.env, world.host )
    seen  = [ ]
    def runner( command, env=None ):
        seen.append( ( list( command ), os.path.exists( world.host.sudoers_path ),
                       open( command[ -1 ] ).read() if command[ 1 ] == "-cf" else None ) )
        return 0, "parsed OK"
    world.host.runner = runner
    assert ids.install_sudoers( facts, world.host ) == "written"
    ( first, second ) = seen
    assert first[ 0 ] == [ "/usr/sbin/visudo", "-cf", world.host.sudoers_path + ".new" ]
    assert first[ 1 ] is False                      # the live file did not exist yet
    assert first[ 2 ] == 'op ALL=(root) NOPASSWD: ' + world.host.copy_path + ' ""\n'
    assert second[ 0 ] == [ "/usr/sbin/visudo", "-c" ] and second[ 1 ] is True
    assert not os.path.exists( world.host.sudoers_path + ".new" )
    assert oct( os.stat( world.host.sudoers_path ).st_mode & 0o7777 ) == "0o440"
    assert ids.install_sudoers( facts, world.host ) == "unchanged"


def test_sudoers_refused_by_the_line_check_installs_nothing_and_leaves_no_temporary( world ):
    facts = ids.preflight( world.env, world.host )
    world.runner.codes[ "-cf" ] = ( 1, "syntax error" )
    with pytest.raises( ids.Refusal ) as caught: ids.install_sudoers( facts, world.host )
    assert caught.value.code == 26 and "syntax error" in str( caught.value )
    assert not os.path.lexists( world.host.sudoers_path )
    assert not os.path.lexists( world.host.sudoers_path + ".new" )
    assert world.runner.calls == [ [ "/usr/sbin/visudo", "-cf", world.host.sudoers_path + ".new" ] ]


def test_sudoers_refused_by_the_whole_set_check_is_taken_out_again( world ):
    facts = ids.preflight( world.env, world.host )
    world.runner.codes[ "-c" ] = ( 1, "bad set" )
    with pytest.raises( ids.Refusal ) as caught: ids.install_sudoers( facts, world.host )
    assert caught.value.code == 27 and "bad set" in str( caught.value )
    assert not os.path.lexists( world.host.sudoers_path )


def test_sudoers_refused_by_the_whole_set_check_restores_the_previous_file( world ):
    facts = ids.preflight( world.env, world.host )
    with open( world.host.sudoers_path, "w" ) as handle: handle.write( "# older\n" )
    world.runner.codes[ "-c" ] = ( 1, "bad set" )
    with pytest.raises( ids.Refusal ) as caught: ids.install_sudoers( facts, world.host )
    assert caught.value.code == 27
    assert open( world.host.sudoers_path ).read() == "# older\n"


def test_a_stale_sudoers_temporary_is_replaced( world ):
    facts = ids.preflight( world.env, world.host )
    with open( world.host.sudoers_path + ".new", "w" ) as handle: handle.write( "stale" )
    assert ids.install_sudoers( facts, world.host ) == "written"


def test_run_installed_passes_the_copys_lines_and_its_refusal_code( world ):
    facts = ids.preflight( world.env, world.host )
    world.runner.codes[ "/py" ] = ( 0, "line one\n" )
    assert ids.run_installed( facts, world.env, world.host ) == "line one"
    assert world.runner.calls[ -1 ] == [ "/py", "-I", world.host.copy_path ]
    world.runner.codes[ "/py" ] = ( 17, "refused: no app file\n" )
    with pytest.raises( ids.Refusal ) as caught: ids.run_installed( facts, world.env, world.host )
    assert caught.value.code == 17 and "no app file" in str( caught.value )


# ── install(): the whole run and what it says ────────────────────────────────

def test_install_runs_all_three_steps_and_reports_each( world ):
    world.runner.codes[ "/py" ] = ( 0, "lupin-install-db-secrets: x: written" )
    assert ids.install( world.env, world.host ) == 0
    text = world.out.getvalue()
    assert "copy of the payload: written" in text and "sudoers line: written" in text
    assert "run of the installed copy:" in text and "x: written" in text


def test_a_preflight_refusal_says_nothing_was_done_and_names_all_three( world ):
    world.host.geteuid = lambda: 1
    assert ids.install( world.env, world.host ) == 20
    text = world.out.getvalue()
    assert "refused: must run as root" in text
    assert "done: nothing; did not: copy of the payload, sudoers line, run of the installed copy" in text
    _nothing_changed( world )


def test_a_sudoers_refusal_says_the_copy_was_made_and_the_rest_was_not( world ):
    world.runner.codes[ "-cf" ] = ( 1, "syntax error" )
    assert ids.install( world.env, world.host ) == 26
    assert "done: copy of the payload; did not: sudoers line, run of the installed copy" in world.out.getvalue()


def test_a_refusal_by_the_installed_copy_passes_its_code_through( world ):
    world.runner.codes[ "/py" ] = ( 16, "refused: source" )
    assert ids.install( world.env, world.host ) == 16
    assert "done: copy of the payload, sudoers line; did not: run of the installed copy" in world.out.getvalue()


def test_a_rerun_reports_unchanged( world ):
    world.runner.codes[ "/py" ] = ( 0, "fine" )
    ids.install( world.env, world.host )
    world.out.truncate( 0 ); world.out.seek( 0 )
    assert ids.install( world.env, world.host ) == 0
    assert world.out.getvalue().count( "unchanged" ) == 2


# ── --check ──────────────────────────────────────────────────────────────────

def _rewrite( path, text ):
    """Replace the content of a read-only file and put its mode back."""
    mode = os.stat( path ).st_mode & 0o7777
    os.chmod( path, 0o600 )
    with open( path, "w" ) as handle: handle.write( text )
    os.chmod( path, mode )


def _installed( world ):
    world.runner.codes[ "/py" ] = ( 0, "fine" )
    assert ids.install( world.env, world.host ) == 0
    _finish_secrets( world )
    world.out.truncate( 0 ); world.out.seek( 0 )


def test_check_on_a_finished_host_is_all_ok_and_changes_nothing( world ):
    _installed( world )
    before = world.runner.calls[ : ]
    assert ids.check( world.env, world.host ) == 0
    lines = world.out.getvalue().strip().splitlines()
    assert len( lines ) == 3 and all( ": ok" in line for line in lines )
    assert world.runner.calls == before


def test_check_on_an_empty_host_says_missing_for_the_copy_and_the_sudoers_line( world ):
    assert ids.check( world.env, world.host ) == 1
    text = world.out.getvalue()
    assert "copy of the payload: missing" in text and "sudoers line: missing" in text
    assert not os.path.lexists( world.host.copy_path )


def test_check_without_the_payload_cannot_look( world, tmp_path ):
    world.host.payload_path = str( tmp_path / "nope" )
    assert ids.check( world.env, world.host ) == 2
    assert "payload: cannot look" in world.out.getvalue()


def test_check_not_root_looks_only_at_the_copy( world ):
    _installed( world )
    world.host.geteuid = lambda: 1000
    assert ids.check( world.env, world.host ) == 2
    text = world.out.getvalue()
    assert "copy of the payload: ok" in text and text.count( "cannot look (not root)" ) == 2


@pytest.mark.parametrize( "damage, expect", [
    ( lambda w: os.chmod( w.host.copy_path, 0o700 ),                     "mode 0700" ),
    ( lambda w: open( w.host.copy_path, "ab" ).write( b"# changed" ),    "different: sha256" ),
    ( lambda w: ( os.unlink( w.host.copy_path ), os.symlink( PAYLOAD, w.host.copy_path ) ), "a link" ),
    ( lambda w: _rewrite( w.host.sudoers_path, "other\n" ),              "not the expected one" ),
    ( lambda w: os.chmod( w.host.sudoers_path, 0o444 ),                  "mode 0444" ),
    ( lambda w: ( os.unlink( w.host.sudoers_path ), os.symlink( PAYLOAD, w.host.sudoers_path ) ), "sudoers line: different: a link" ),
    ( lambda w: ( w.secrets / "db_test_password" ).unlink(),             "db_test_password missing" ),
    ( lambda w: ( w.secrets / "db_test_password" ).chmod( 0o600 ),       "db_test_password owner" ),
    ( lambda w: _rewrite( str( w.secrets / "db_test_password" ), "other\n" ), "does not hold the password" ),
] )
def test_check_reports_each_difference( world, damage, expect ):
    _installed( world )
    damage( world )
    assert ids.check( world.env, world.host ) == 1
    assert expect in world.out.getvalue()


def test_check_a_missing_secrets_directory_and_a_linked_secret( world ):
    _installed( world )
    link = world.secrets / "db_test_password"
    link.unlink()
    link.symlink_to( world.secrets / "db_app_password" )
    assert ids.check( world.env, world.host ) == 1
    assert "db_test_password missing" in world.out.getvalue()
    world.host.secrets_dir = str( world.tmp / "gone" )
    world.out.truncate( 0 ); world.out.seek( 0 )
    assert ids.check( world.env, world.host ) == 1
    assert "missing: the directory" in world.out.getvalue()


def test_check_cannot_judge_the_password_without_the_operators_file( world ):
    _installed( world )
    world.source.chmod( 0o666 )
    assert ids.check( world.env, world.host ) == 2
    assert "secret files: cannot look" in world.out.getvalue()


def test_check_without_sudo_does_not_guess_the_sudoers_line( world ):
    _installed( world )
    assert ids.check( { }, world.host ) == 2
    assert "operator is unknown" in world.out.getvalue()


# ── main ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "argv", [ [ "x", "--nonsense" ], [ "x", "--check", "more" ] ] )
def test_main_refuses_an_unknown_argument( world, argv ):
    assert ids.main( argv, world.env, world.host ) == 2
    assert "usage" in world.out.getvalue()
    _nothing_changed( world )


def test_main_routes_check_and_install( world ):
    assert ids.main( [ "x", "--check" ], world.env, world.host ) == 1
    world.runner.codes[ "/py" ] = ( 0, "fine" )
    assert ids.main( [ "x" ], world.env, world.host ) == 0


def test_main_defaults_come_from_the_process( monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "x", "--nonsense" ] )
    assert ids.main() == 2
    assert "usage" in capsys.readouterr().out
