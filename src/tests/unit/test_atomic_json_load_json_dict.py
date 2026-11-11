"""Unit tests for load_json_dict in cosa.utils.atomic_json."""
import pathlib

from cosa.utils.atomic_json import load_json_dict, write_json_atomic


def test_a_dict_file_round_trips_and_every_other_case_reads_as_empty( tmp_path ):
    path = tmp_path / "d" / "state.json"
    assert load_json_dict( path ) == {}, "absent file"
    write_json_atomic( path, { "k": "v" } )
    assert load_json_dict( str( path ) ) == { "k": "v" }
    path.write_text( "{not json" );        assert load_json_dict( path ) == {}
    path.write_text( "[1, 2]" );           assert load_json_dict( path ) == {}
    path.write_bytes( b"\xff\xfe\x00bad" ); assert load_json_dict( path ) == {}, "undecodable bytes"
    assert load_json_dict( tmp_path ) == {}, "a directory is an OSError"
