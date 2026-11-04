"""
Unit tests for session_bridge._get_dict_field and _set_str_field.

They replaced the copied bodies of get_voice_persona, get_idle_detection, set_user_id and set_owner_user_id.
"""

import json

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


@pytest.fixture
def bridge_file( tmp_path, monkeypatch ):
    path = tmp_path / "cc-1.json"
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda sid: path if sid == "sid" else None )
    return path


class TestGetDictField:

    def test_it_reads_the_named_key_only( self, bridge_file ):
        bridge_file.write_text( json.dumps( { "a": { "x": 1 }, "b": { "y": 2 } } ) )
        assert sb._get_dict_field( "sid", "a" ) == { "x": 1 }
        assert sb._get_dict_field( "sid", "b" ) == { "y": 2 }
        assert sb._get_dict_field( "sid", "c" ) is None

    def test_an_empty_dict_a_scalar_and_a_corrupt_file_are_none( self, bridge_file ):
        bridge_file.write_text( json.dumps( { "a": {}, "b": 3 } ) )
        assert sb._get_dict_field( "sid", "a" ) is None
        assert sb._get_dict_field( "sid", "b" ) is None
        bridge_file.write_text( "{nope" )
        assert sb._get_dict_field( "sid", "a" ) is None

    def test_no_bridge_or_no_file_is_none( self, bridge_file ):
        assert sb._get_dict_field( "unknown", "a" ) is None
        assert sb._get_dict_field( "sid", "a" ) is None


class TestSetStrField:

    def test_it_writes_the_string_form_and_keeps_every_other_field( self, bridge_file ):
        bridge_file.write_text( json.dumps( { "keep": { "n": 1 }, "k": "old" } ) )
        assert sb._set_str_field( "sid", "k", 12345 ) is True
        assert json.loads( bridge_file.read_text() ) == { "keep": { "n": 1 }, "k": "12345" }

    @pytest.mark.parametrize( "session_id, value", [ ( "", "v" ), ( None, "v" ), ( "sid", "" ), ( "sid", None ), ( "sid", 0 ) ] )
    def test_an_empty_argument_returns_false_and_leaves_the_file_alone( self, bridge_file, session_id, value ):
        bridge_file.write_text( json.dumps( { "k": "old" } ) )
        assert sb._set_str_field( session_id, "k", value ) is False
        assert json.loads( bridge_file.read_text() ) == { "k": "old" }

    def test_a_missing_bridge_a_corrupt_file_and_an_unreadable_file_return_false( self, bridge_file ):
        assert sb._set_str_field( "unknown", "k", "v" ) is False
        assert sb._set_str_field( "sid", "k", "v" ) is False
        bridge_file.write_text( "{nope" )
        assert sb._set_str_field( "sid", "k", "v" ) is False

    def test_the_write_goes_through_atomic_write_json_and_its_answer_is_returned( self, bridge_file, monkeypatch ):
        bridge_file.write_text( json.dumps( {} ) )
        calls = []
        monkeypatch.setattr( sb, "atomic_write_json", lambda path, data: calls.append( ( path, data ) ) or False )
        assert sb._set_str_field( "sid", "k", "v" ) is False
        assert calls == [ ( bridge_file, { "k": "v" } ) ]

    @pytest.mark.parametrize( "setter, key", [ ( sb.set_user_id, "user_id" ), ( sb.set_owner_user_id, "owner_user_id" ) ] )
    def test_each_public_setter_writes_its_own_key( self, bridge_file, setter, key ):
        bridge_file.write_text( json.dumps( {} ) )
        assert setter( "sid", "u-1" ) is True
        assert json.loads( bridge_file.read_text() ) == { key: "u-1" }
