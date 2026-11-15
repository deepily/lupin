"""
Unit tests for the worker voice mode module and its spawn_sessions seam.

Rick's ruling: a spawned worker starts quiet. A manager, whatever its role, keeps the mode-aware
default. The key has no default in code.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import worker_voice_mode as wvm
from lupin_mcp.session_spawner import spawn_sessions
from test_spawn_sessions import FakeRunner, _stated_fleet

STAMP = "manager_figure_implicit"


class _Cfg:
    def __init__( self, value ): self.value = value
    def get( self, key, default=None, **kw ):
        assert key == wvm.INI_KEY
        return self.value if self.value is not None else default


@pytest.mark.parametrize( "raw,expected", [ ( "quiet", "quiet" ), ( " Speakerphone ", "speakerphone" ), ( "INHERIT", "inherit" ) ] )
def test_each_of_the_three_words_resolves( raw, expected ):
    assert wvm.resolve_worker_voice_mode( _Cfg( raw ) ) == expected


@pytest.mark.parametrize( "raw", [ None, "", "   ", "loud" ] )
def test_blank_absent_or_unknown_refuses_naming_the_key( raw ):
    with pytest.raises( ValueError, match = "cc session worker default voice mode" ):
        wvm.resolve_worker_voice_mode( _Cfg( raw ) )


def test_worker_role_forwards_the_key_and_manager_role_forwards_inherit_without_reading_ini():
    assert wvm.worker_voice_env( "author", lambda: _Cfg( "quiet" ) ) == { wvm.ENV_VAR: "quiet" }
    def _boom(): raise AssertionError( "a manager spawn must not read the INI" )
    assert wvm.worker_voice_env( "manager", _boom ) == { wvm.ENV_VAR: "inherit" }
    # exact match: manager-aide is a worker
    assert wvm.worker_voice_env( "manager-aide", lambda: _Cfg( "quiet" ) ) == { wvm.ENV_VAR: "quiet" }


@pytest.mark.parametrize( "mode,inherit,expected", [
    ( "quiet", True, False ), ( "speakerphone", False, True ),
    ( "inherit", True, True ), ( "inherit", False, False ),
    ( None, True, False ), ( "bogus", True, False ),
] )
def test_mode_to_speakerphone( mode, inherit, expected ):
    assert wvm.speakerphone_for_mode( mode, lambda: inherit ) is expected


@pytest.mark.parametrize( "bridge,expected", [
    # a plain spawned worker
    ( { "spawned_by": "m", "role": "author", STAMP: False, "speakerphone_on": False }, True ),
    # Cheech's shape: spawned role author, but a standing manager by persona stamp
    ( { "spawned_by": "m", "role": "author", STAMP: True, "speakerphone_on": False }, False ),
    # Maria's shape: spawned as a manager
    ( { "spawned_by": "m", "role": "manager", STAMP: True, "speakerphone_on": False }, False ),
    ( { "spawned_by": "m", "role": "manager", STAMP: False, "speakerphone_on": False }, False ),
    # manager-aide is not a manager
    ( { "spawned_by": "m", "role": "manager-aide", STAMP: False, "speakerphone_on": False }, True ),
    # not spawned
    ( { "role": "author", STAMP: False, "speakerphone_on": False }, False ),
    # legacy bridge, stamp absent: never quieted
    ( { "spawned_by": "m", "role": "author", "speakerphone_on": False }, False ),
    # Rick flipped the worker to speakerphone
    ( { "spawned_by": "m", "role": "author", STAMP: False, "speakerphone_on": True }, False ),
    # speakerphone field absent
    ( { "spawned_by": "m", "role": "author", STAMP: False }, False ),
] )
def test_quiet_worker_predicate( bridge, expected ):
    assert wvm.is_quiet_worker_bridge( bridge, STAMP ) is expected


def test_predicate_never_raises_on_a_non_dict():
    assert wvm.is_quiet_worker_bridge( None, STAMP ) is False


@pytest.mark.parametrize( "role,key,expected", [
    ( "author", "quiet", "quiet" ), ( "author", "speakerphone", "speakerphone" ),
    ( "author", "inherit", "inherit" ), ( "manager", "quiet", "inherit" ),
] )
def test_spawn_sessions_env_carries_the_mode( tmp_path, role, key, expected ):
    runner = FakeRunner()
    spawn_sessions( 1, "t", "sid-1", script_path="/s.sh", role=role, runner=runner,
                    session_dir=tmp_path, voice_config_fn=lambda: _Cfg( key ), **_stated_fleet() )
    assert runner.calls[ 0 ][ 1 ][ wvm.ENV_VAR ] == expected


def test_spawn_sessions_refuses_a_bad_key_before_spawning_anyone( tmp_path ):
    runner = FakeRunner()
    with pytest.raises( ValueError, match = "cc session worker default voice mode" ):
        spawn_sessions( 2, "t", "sid-1", script_path="/s.sh", role="author", runner=runner,
                        session_dir=tmp_path, voice_config_fn=lambda: _Cfg( "loud" ), **_stated_fleet() )
    assert runner.calls == []


def test_spawn_sessions_default_source_reads_the_real_ini( tmp_path ):
    runner = FakeRunner()
    spawn_sessions( 1, "t", "sid-1", script_path="/s.sh", role="author", runner=runner,
                    session_dir=tmp_path, **_stated_fleet() )
    assert runner.calls[ 0 ][ 1 ][ wvm.ENV_VAR ] == "quiet"
