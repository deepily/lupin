"""
Each session_bridge reader fails soft on a bridge whose JSON is not an object.

Commit 82f37e0bf guarded two readers. The other 22 raised on a list, string or number.
All now load through `_load_bridge_object`, which raises the parse failure callers already handle.
Each test feeds one reader a list, a string and a number.
"""

import json

import pytest

from pathlib import Path

from lupin_cli.claude_code.hooks.lib import session_bridge as sb

PAYLOADS = [ "[ 1, 2 ]", "\"text\"", "7" ]


class FakeSessionDir:
    """A SESSION_DIR stand-in that yields its files in the order the test chooses."""

    def __init__( self, *paths ):
        self._paths = list( paths )

    def exists( self ):
        return True

    def glob( self, _pattern ):
        return iter( self._paths )


@pytest.fixture( params=PAYLOADS )
def bad( request, tmp_path, monkeypatch ):
    """A bridge named cc-<pid>.json holding non-object JSON, found by every lookup."""
    path = tmp_path / "cc-4242.json"
    path.write_text( request.param )
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda *_a, **_k: path )
    monkeypatch.setattr( sb, "SESSION_DIR", FakeSessionDir( path ) )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )
    monkeypatch.setattr( sb, "_is_pid_alive", lambda _pid: True )
    return path


class TestLoadBridgeObject:

    def test_an_object_is_returned( self, tmp_path ):
        path = tmp_path / "cc-1.json"
        path.write_text( json.dumps( { "a": 1 } ) )
        assert sb._load_bridge_object( path ) == { "a": 1 }

    def test_a_non_object_raises_the_parse_failure( self, bad ):
        with pytest.raises( json.JSONDecodeError ):
            sb._load_bridge_object( bad )


class TestReadersSurviveNonObjectJson:

    def test_find_session_file( self, bad, tmp_path, monkeypatch ):
        monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
        monkeypatch.setattr( sb.os, "getppid", lambda: 999_999_999 )
        assert sb._find_session_file() is None

    def test_read_session_file( self, bad ):
        assert sb._read_session_file( bad ) is None

    def test_resolve_stable_session_id( self, bad, monkeypatch ):
        monkeypatch.setattr( sb, "_find_session_file", lambda: ( bad, "ppid" ) )
        assert sb.resolve_stable_session_id( "transient" ) == "transient"

    def test_resolve_project_from_bridge_cwd( self, bad, monkeypatch ):
        monkeypatch.setattr( sb, "_find_session_file", lambda: ( bad, "ppid" ) )
        assert sb._resolve_project_from_bridge_cwd() is None

    def test_get_session_metadata( self, bad, monkeypatch ):
        monkeypatch.delenv( "CLAUDE_SESSION_ID", raising=False )
        monkeypatch.setattr( sb, "_find_session_file", lambda: ( bad, "ppid" ) )
        assert sb.get_session_metadata()[ "source" ] == "fallback"

    def test_find_session_by_id( self, bad ):
        assert sb.find_session_by_id( "anything" ) is None

    def test_iter_live_bridges( self, bad ):
        assert list( sb.iter_live_bridges() ) == []

    def test_find_dead_sessions( self, bad ):
        assert sb.find_dead_sessions( [ "anything" ] ) == set()

    def test_find_active_speakerphone_sessions( self, bad ):
        assert sb.find_active_speakerphone_sessions() == []

    def test_get_speakerphone( self, bad ):
        assert sb.get_speakerphone( "sid" ) is False

    def test_set_speakerphone( self, bad ):
        assert sb.set_speakerphone( "sid", True ) is False

    def test_set_manager_figure_implicit( self, bad ):
        assert sb.set_manager_figure_implicit( "sid", True ) is False

    def test_get_last_autonarrated_turn_id( self, bad ):
        assert sb.get_last_autonarrated_turn_id( "sid" ) is None

    def test_set_last_autonarrated_turn_id( self, bad ):
        assert sb.set_last_autonarrated_turn_id( "sid", "t1" ) is False

    def test_set_str_field( self, bad ):
        assert sb._set_str_field( "sid", "k", "v" ) is False

    def test_set_voice_persona( self, bad ):
        assert sb.set_voice_persona( "sid", { "name": "john" } ) is False

    def test_set_idle_detection_field( self, bad ):
        assert sb.set_idle_detection_field( "sid", waiter_pid=1 ) is False

    def test_clear_idle_waiter_pid( self, bad ):
        assert sb.clear_idle_waiter_pid( "sid" ) is None

    def test_prune_dead_persona_bridges( self, bad, monkeypatch ):
        monkeypatch.setattr( sb, "_is_pid_alive", lambda _pid: False )
        assert sb.prune_dead_persona_bridges() == 0

    def test_append_stale_bridge( self, bad ):
        out = []
        sb._append_stale_bridge( out, bad, 5.0, pid_alive=True )
        assert out[ 0 ][ "session_id" ] is None

    def test_find_active_sessions( self, bad ):
        assert sb.find_active_sessions( require_persona=False ) == []

    def test_find_session_by_tmux( self, bad ):
        assert sb.find_session_by_tmux( "any" ) is None
