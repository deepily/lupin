"""
Pins the last scan edges of session_bridge that no other unit file reached.

Each test drives one early exit: a missing directory, an empty id, a skipped name, a vanished file.
"""

import json

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


class GonePath:
    """A bridge path whose stat fails, as if a racing SessionEnd deleted it."""

    name = "cc-4242.json"

    def stat( self ):
        raise FileNotFoundError( "gone" )


class FakeDir:
    """A SESSION_DIR stand-in yielding a fixed list of paths."""

    def __init__( self, *paths ):
        self._paths = list( paths )

    def exists( self ):
        return True

    def glob( self, _pattern ):
        return iter( self._paths )


class TestScanEdges:

    def test_index_of_a_missing_directory_is_empty( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( sb, "SESSION_DIR", tmp_path / "absent" )
        assert sb.build_live_bridge_index() == []

    def test_an_empty_session_id_matches_nothing( self ):
        assert sb.find_in_bridge_index( [ ( "p", {}, [ "abc" ] ) ], "" ) is None

    def test_buffer_and_listener_files_are_skipped( self, tmp_path, monkeypatch ):
        names = [ "cc-buffer-1.json", "cc-listener-1.json" ]
        for name in names:
            ( tmp_path / name ).write_text( json.dumps( { "session_id": "sid", "voice_persona": { "n": 1 } } ) )
        monkeypatch.setattr( sb, "SESSION_DIR", FakeDir( *[ tmp_path / n for n in names ] ) )
        monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
        assert sb.find_active_sessions() == []

    def test_a_bridge_that_vanishes_before_stat_is_skipped( self, monkeypatch ):
        monkeypatch.setattr( sb, "SESSION_DIR", FakeDir( GonePath() ) )
        monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
        assert sb.find_active_sessions() == []

    def test_a_bridge_without_a_persona_is_skipped_when_one_is_required( self, tmp_path, monkeypatch ):
        path = tmp_path / "cc-4242.json"
        path.write_text( json.dumps( { "session_id": "sid" } ) )
        monkeypatch.setattr( sb, "SESSION_DIR", FakeDir( path ) )
        monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
        assert sb.find_active_sessions( require_persona=True ) == []
