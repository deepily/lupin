"""
Pins get_voice_persona and get_idle_detection, the two dict-valued bridge readers.

Neither had a direct test. Both read one key and answer None unless it holds a non-empty dict.
"""

import json

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb

GETTERS = [
    ( sb.get_voice_persona,  "voice_persona" ),
    ( sb.get_idle_detection, "idle_detection" ),
]


class Bridge:
    """The bridge file plus the list of session ids the lookup was asked for."""

    def __init__( self, path ):
        self.path = path
        self.seen = []

    def write_text( self, text ):
        self.path.write_text( text )

    def exists( self ):
        return self.path.exists()


@pytest.fixture
def bridge( tmp_path, monkeypatch ):
    """A bridge file at tmp_path/cc-1.json that find_session_path_by_id resolves for 'sid' only."""
    path = Bridge( tmp_path / "cc-1.json" )
    seen = path.seen

    def fake_find( session_id ):
        seen.append( session_id )
        return path.path if session_id == "sid" else None

    monkeypatch.setattr( sb, "find_session_path_by_id", fake_find )
    return path


class TestDictGetters:

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_a_non_empty_dict_is_returned_as_stored( self, bridge, getter, key ):
        bridge.write_text( json.dumps( { key: { "a": 1, "b": [ 2 ] }, "other": { "x": 1 } } ) )
        assert getter( "sid" ) == { "a": 1, "b": [ 2 ] }

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_each_getter_reads_only_its_own_key( self, bridge, getter, key ):
        other = "idle_detection" if key == "voice_persona" else "voice_persona"
        bridge.write_text( json.dumps( { other: { "x": 1 } } ) )
        assert getter( "sid" ) is None

    @pytest.mark.parametrize( "getter, key", GETTERS )
    @pytest.mark.parametrize( "value", [ None, {}, [], [ 1 ], "text", "", 0, 7, True ] )
    def test_a_null_empty_or_non_dict_value_is_none( self, bridge, getter, key, value ):
        bridge.write_text( json.dumps( { key: value } ) )
        assert getter( "sid" ) is None

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_a_missing_field_is_none( self, bridge, getter, key ):
        bridge.write_text( json.dumps( { "session_id": "sid" } ) )
        assert getter( "sid" ) is None

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_an_unknown_session_is_none_and_the_file_is_not_opened( self, bridge, getter, key ):
        bridge.write_text( json.dumps( { key: { "a": 1 } } ) )
        assert getter( "other-sid" ) is None
        assert bridge.seen == [ "other-sid" ]

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_a_corrupt_file_is_none( self, bridge, getter, key ):
        bridge.write_text( "{not json" )
        assert getter( "sid" ) is None

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_a_file_that_vanished_after_the_lookup_is_none( self, bridge, getter, key ):
        assert not bridge.exists()
        assert getter( "sid" ) is None

    @pytest.mark.parametrize( "getter, key", GETTERS )
    def test_the_session_id_is_passed_to_the_lookup_unchanged( self, bridge, getter, key ):
        getter( "abc12345" )
        assert bridge.seen == [ "abc12345" ]
