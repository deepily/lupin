"""
The cosa-voice installer keeps the reuse-check settings when it is run again.

The installer removes the old registration and adds a new one, so a setting that lived only in the old entry used to be dropped.
Each test runs the real script and the real `claude` command against a throwaway home folder, so the real ~/.claude.json is never opened.
"""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

import cosa.utils.util as cu
from lupin_mcp import reuse_ledger as rl

SRC    = pathlib.Path( cu.get_project_root() ) / "src"
SCRIPT = SRC / "scripts/install-cosa-voice.sh"
PACK, CEILING = "LUPIN_REUSE_JEV_PACK_SIZE", "LUPIN_REUSE_JEV_TOKEN_CEILING"
CLAUDE = shutil.which( "claude" )

pytestmark = pytest.mark.skipif( CLAUDE is None, reason="the claude command is not on PATH, so the installer cannot register anything" )


@pytest.fixture
def home( tmp_path ):
    """Ensures: a throwaway home and tree that pass the installer's checks."""
    root = tmp_path / "root"
    ( root / ".venv/bin" ).mkdir( parents=True )
    ( root / ".venv/bin/python" ).write_text( "", encoding="utf-8" )
    ( root / "src" ).mkdir( parents=True )
    ( root / "src/lupin_mcp" ).symlink_to( SRC / "lupin_mcp" )                 # the real package, so the constant the installer reads is the real one
    ( root / "src/conf/keys" ).mkdir( parents=True )
    ( root / "src/conf/keys/notification-api-claude-code-dev" ).write_text( "key\n", encoding="utf-8" )
    ( root / "src/scripts/lib" ).mkdir( parents=True )
    ( root / "src/scripts/lib/installer-notify-step.sh" ).write_text( "run_test_notification() { :; }\n", encoding="utf-8" )
    ( tmp_path / "home/.lupin" ).mkdir( parents=True )
    ( tmp_path / "home/.lupin/config" ).write_text( "[local]\napi_url = http://127.0.0.1:9\n", encoding="utf-8" )
    ( tmp_path / "bin" ).mkdir()
    ( tmp_path / "bin/claude" ).symlink_to( CLAUDE )
    return tmp_path


def install( home, **settings ):
    """Ensures: runs the installer against the throwaway home and returns the finished process."""
    env = { "HOME": str( home / "home" ), "PATH": f"{home / 'bin'}:/usr/bin:/bin", "LUPIN_ROOT": str( home / "root" ),
            "LUPIN_APP_SERVER_URL": "http://127.0.0.1:9", **settings }
    return subprocess.run( [ "bash", str( SCRIPT ) ], env=env, cwd=str( home ), capture_output=True, text=True, timeout=120 )


def registered( home ):
    """Ensures: returns the entry's environment from the throwaway config, or None."""
    config = home / "home/.claude.json"
    if not config.exists(): return None
    entry = json.loads( config.read_text( encoding="utf-8" ) ).get( "mcpServers", {} ).get( "cosa-voice" )
    return None if entry is None else entry[ "env" ]


def test_the_settings_in_the_shell_are_written_to_the_entry_beside_the_usual_three( home ):
    done = install( home, **{ PACK: "50", CEILING: "70000" } )
    env  = registered( home )
    assert done.returncode == 0, done.stdout[ -600: ]
    assert env[ PACK ] == "50" and env[ CEILING ] == "70000"
    assert set( env ) == { "PYTHONPATH", "LUPIN_ROOT", "LUPIN_CONFIG_MGR_CLI_ARGS", PACK, CEILING }, "the three usual settings are still there"
    assert str( home / "root" ) in env[ "LUPIN_ROOT" ], "the run used the throwaway tree, not the real one"


def test_the_ceiling_it_writes_by_default_is_the_ledger_constant_the_capacity_check_reads( home ):
    assert install( home ).returncode == 0
    assert registered( home )[ CEILING ] == str( rl.LOOKUP_CEILING_TOKENS ), "the two cannot drift: the installer reads the constant, not a typed number"
    assert PACK not in registered( home ), "a pack size is never invented"


def test_the_installer_writes_whatever_the_constant_says_not_a_number_of_its_own( home ):
    package = home / "root/src/lupin_mcp"
    package.unlink()
    package.mkdir()
    ( package / "__init__.py" ).write_text( "", encoding="utf-8" )
    ( package / "cosa_voice_mcp.py" ).write_text( "", encoding="utf-8" )
    source = ( SRC / "lupin_mcp/reuse_ledger.py" ).read_text( encoding="utf-8" )
    line   = next( l for l in source.splitlines() if l.startswith( "LOOKUP_CEILING_TOKENS" ) )
    ( package / "reuse_ledger.py" ).write_text( source.replace( line, "LOOKUP_CEILING_TOKENS = 123_456" ), encoding="utf-8" )
    assert install( home ).returncode == 0 and registered( home )[ CEILING ] == "123456", "a copy of the ledger with another constant gives another ceiling"


def test_running_it_again_with_nothing_set_keeps_the_pack_size_and_takes_the_ceiling_from_the_constant( home ):
    assert install( home, **{ PACK: "50", CEILING: "70000" } ).returncode == 0
    again = install( home )
    assert again.returncode == 0
    assert registered( home )[ PACK ] == "50", "re-running used to drop it"
    assert registered( home )[ CEILING ] == str( rl.LOOKUP_CEILING_TOKENS ), "an older ceiling in the old entry is not carried over"
    assert "kept in the registration" in again.stdout


def test_a_value_in_the_shell_replaces_the_old_one_and_the_pack_size_is_kept( home ):
    assert install( home, **{ PACK: "50" } ).returncode == 0
    assert install( home, **{ CEILING: "70000" } ).returncode == 0
    assert registered( home )[ PACK ] == "50" and registered( home )[ CEILING ] == "70000"
    assert install( home, **{ PACK: "25" } ).returncode == 0 and registered( home )[ PACK ] == "25" and registered( home )[ CEILING ] == str( rl.LOOKUP_CEILING_TOKENS )


def test_an_installer_that_cannot_read_the_constant_warns_and_writes_no_ceiling( home ):
    ( home / "root/src/lupin_mcp" ).unlink()
    ( home / "root/src/lupin_mcp" ).mkdir()
    ( home / "root/src/lupin_mcp/cosa_voice_mcp.py" ).write_text( "", encoding="utf-8" )
    done = install( home )
    assert done.returncode == 0 and "could not read reuse_ledger.LOOKUP_CEILING_TOKENS" in done.stdout and CEILING not in registered( home )


@pytest.mark.parametrize( "bad", [ "0", "-5", "fifty", "5.5", "50 000", "007x" ] )
def test_a_wrong_value_stops_the_install_before_anything_is_removed( home, bad ):
    assert install( home, **{ PACK: "50" } ).returncode == 0
    before = registered( home )
    done   = install( home, **{ CEILING: bad } )
    assert done.returncode == 1 and "must be a positive whole number" in done.stdout and CEILING in done.stdout
    assert registered( home ) == before, "the old entry is whole"
