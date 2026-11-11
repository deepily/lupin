"""
Tests for the modes of the test VM's secrets folder.

The push-env fragment is cut out of lupin-vm.sh and run in a scratch home folder.
The preflight block runs through the real runner, pointed at a scratch folder.
"""

import os
import stat
import subprocess

import pytest

ROOT   = os.environ[ "LUPIN_ROOT" ]
LIB    = os.path.join( ROOT, "src/scripts/lib/preflight-vm-lib.sh" )
RUNNER = os.path.join( ROOT, "src/scripts/preflight-vm.sh" )
VMSH   = os.path.join( ROOT, "src/scripts/lupin-vm.sh" )


def _fragment():
    text  = open( VMSH ).read()
    start = text.index( "echo '== ensure ~/.lupin/config exists" )
    end   = text.index( "echo '== done — open a fresh shell" )
    # the fragment sits inside a double-quoted string in lupin-vm.sh: undo that quoting
    return text[ start:end ].replace( '\\"', '"' ).replace( "\\$", "$" )


def _run_fragment( home ):
    return subprocess.run( [ "bash", "-c", _fragment() ], env={ "HOME": str( home ), "PATH": os.environ[ "PATH" ] }, capture_output=True, text=True, timeout=30 )


def _mode( path ): return stat.S_IMODE( os.stat( path ).st_mode )


def _within( observed, ceiling ):
    r = subprocess.run( [ "bash", "-c", f"source '{LIB}'; pfv_mode_within '{observed}' '{ceiling}'" ], capture_output=True, text=True, timeout=30 )
    return r.returncode


@pytest.mark.parametrize( "observed,ceiling,rc", [
    ( "750", "750", 0 ), ( "700", "750", 0 ), ( "640", "640", 0 ), ( "600", "640", 0 ), ( "0640", "640", 0 ),
    ( "755", "750", 1 ), ( "775", "750", 1 ), ( "664", "640", 1 ), ( "644", "640", 1 ), ( "2750", "750", 1 ),
    ( "", "750", 2 ), ( "75x", "750", 2 ), ( "750", "", 2 ), ( "750", "9", 2 ),
] )
def test_mode_within_names_looser_ok_and_unknown( observed, ceiling, rc ):
    assert _within( observed, ceiling ) == rc


def test_push_env_creates_the_directory_at_750_and_the_config_at_640_under_a_loose_umask( tmp_path ):
    old = os.umask( 0o002 )
    try: r = _run_fragment( tmp_path )
    finally: os.umask( old )
    assert r.returncode == 0, r.stderr
    assert _mode( tmp_path / ".lupin" ) == 0o750
    assert _mode( tmp_path / ".lupin/config" ) == 0o640
    assert "created ~/.lupin/config" in r.stdout


def test_push_env_tightens_loose_existing_files_and_leaves_the_content( tmp_path ):
    d = tmp_path / ".lupin"; d.mkdir(); os.chmod( d, 0o775 )
    ( d / "config" ).write_text( "keep me\n" ); os.chmod( d / "config", 0o664 )
    ( d / "notification-api.key" ).write_text( "k" ); os.chmod( d / "notification-api.key", 0o664 )
    r = _run_fragment( tmp_path )
    assert r.returncode == 0, r.stderr
    assert ( _mode( d ), _mode( d / "config" ), _mode( d / "notification-api.key" ) ) == ( 0o755 & ~0o005, 0o640, 0o640 )
    assert ( d / "config" ).read_text() == "keep me\n" and "already present" in r.stdout


def test_push_env_never_loosens_a_stricter_mode_and_tolerates_a_missing_key( tmp_path ):
    d = tmp_path / ".lupin"; d.mkdir(); os.chmod( d, 0o700 )
    ( d / "config" ).write_text( "x" ); os.chmod( d / "config", 0o600 )
    r = _run_fragment( tmp_path )
    assert r.returncode == 0, r.stderr
    assert ( _mode( d ), _mode( d / "config" ) ) == ( 0o700, 0o600 )
    assert not ( d / "notification-api.key" ).exists()


def _runner_lines( cfg ):
    """Run the real runner; the mode block is the only part this test reads, so keep its lines."""
    r = subprocess.run( [ "bash", RUNNER, "--phase", "pre" ], env={ **os.environ, "LUPIN_HOME_CONFIG_DIR": str( cfg ) }, capture_output=True, text=True, timeout=120 )
    return [ l for l in ( r.stdout + r.stderr ).splitlines() if str( cfg ) in l and "chmod " not in l and "ls -ld" not in l ]


def _cfg( tmp_path, dmode, fmode, key=True ):
    d = tmp_path / "lupin"; d.mkdir(); os.chmod( d, dmode )
    ( d / "config" ).write_text( "x" ); os.chmod( d / "config", fmode )
    if key: ( d / "notification-api.key" ).write_text( "k" ); os.chmod( d / "notification-api.key", fmode )
    return d


def test_runner_is_green_for_750_and_640( tmp_path ):
    lines = _runner_lines( _cfg( tmp_path, 0o750, 0o640 ) )
    assert len( lines ) == 3 and all( "no looser than" in l for l in lines ), lines


def test_runner_is_red_for_a_loose_directory_and_loose_files( tmp_path ):
    lines = _runner_lines( _cfg( tmp_path, 0o775, 0o664 ) )
    assert len( lines ) == 3 and all( "looser than" in l and "no looser" not in l for l in lines ), lines
    assert any( "775" in l for l in lines ) and sum( "664" in l for l in lines ) == 2


def test_runner_names_a_missing_file_as_unknown_not_green( tmp_path ):
    lines = _runner_lines( _cfg( tmp_path, 0o750, 0o640, key=False ) )
    assert sum( "could not read the mode" in l for l in lines ) == 1 and sum( "no looser than" in l for l in lines ) == 2, lines
