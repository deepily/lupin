#!/usr/bin/env python3
"""
Unit tests — task-store mirror correlation map artifact (Phase 2).

Venue: :7999-eligible / local — pure file IO under tmp_path.
Covers map_path / read_map / write_map / record_task / set_flagged to
100% lines/branches/functions.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import task_store_map as tm

EMPTY = { "tasks": { }, "flagged_at": None }


class TestMapPath:

    def test_per_session_filename( self, tmp_path ):
        assert tm.map_path( "sid-1", base_dir=tmp_path ).name == ".task-store-map-sid-1.json"

    def test_empty_session_collapses_to_unknown( self, tmp_path ):
        assert tm.map_path( "", base_dir=tmp_path ).name == ".task-store-map-unknown.json"

    def test_base_dir_none_resolves_project_root( self ):
        with pytest.MonkeyPatch.context() as mp:
            import cosa.utils.util as cu
            mp.setattr( cu, "get_project_root", lambda: "/proj/root" )
            assert str( tm.map_path( "s" ) ) == "/proj/root/.task-store-map-s.json"


class TestReadMap:

    def test_missing_file_is_empty_map( self, tmp_path ):
        assert tm.read_map( "absent", base_dir=tmp_path ) == EMPTY

    def test_round_trip( self, tmp_path ):
        tm.write_map( "s", { "tasks": { "1": { "item_id": "u", "last_status": "pending" } }, "flagged_at": "t0" }, tmp_path )
        assert tm.read_map( "s", base_dir=tmp_path ) == {
            "tasks": { "1": { "item_id": "u", "last_status": "pending" } }, "flagged_at": "t0",
        }

    def test_malformed_json_degrades_to_empty( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( "{bad" )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_non_dict_root_degrades_to_empty( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( "[1, 2]" )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_non_dict_tasks_normalized_empty( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( '{"tasks": "x", "flagged_at": null}' )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_non_dict_task_entries_dropped( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( '{"tasks": {"1": "junk", "2": {"item_id": "u"}}}' )
        assert tm.read_map( "s", base_dir=tmp_path )[ "tasks" ] == { "2": { "item_id": "u" } }

    def test_non_string_flagged_at_normalized_none( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( '{"tasks": {}, "flagged_at": 7}' )
        assert tm.read_map( "s", base_dir=tmp_path )[ "flagged_at" ] is None


class TestWriteMap:

    def test_atomic_write_leaves_no_tmp_files( self, tmp_path ):
        tm.write_map( "s", EMPTY, tmp_path )
        assert [ p.name for p in tmp_path.iterdir() ] == [ ".task-store-map-s.json" ]

    def test_unwritable_dir_raises_oserror( self, tmp_path ):
        with pytest.raises( OSError ):
            tm.write_map( "s", EMPTY, tmp_path / "no-such-subdir" )


class TestRecordTask:

    def test_inserts_entry_and_returns_map( self, tmp_path ):
        result = tm.record_task( "s", "3", "uuid-3", "pending", tmp_path )
        assert result[ "tasks" ][ "3" ] == { "item_id": "uuid-3", "last_status": "pending" }
        assert tm.read_map( "s", base_dir=tmp_path ) == result

    def test_upsert_preserves_other_entries_and_flag( self, tmp_path ):
        tm.record_task( "s", "1", "u1", "pending", tmp_path )
        tm.set_flagged( "s", "t0", tmp_path )
        tm.record_task( "s", "1", "u1", "in_progress", tmp_path )
        data = tm.read_map( "s", base_dir=tmp_path )
        assert data[ "tasks" ][ "1" ][ "last_status" ] == "in_progress"
        assert data[ "flagged_at" ] == "t0"

    def test_harness_id_stringified( self, tmp_path ):
        tm.record_task( "s", 7, "u7", "pending", tmp_path )
        assert "7" in tm.read_map( "s", base_dir=tmp_path )[ "tasks" ]


class TestSetFlagged:

    def test_set_then_clear( self, tmp_path ):
        tm.record_task( "s", "1", "u1", "pending", tmp_path )
        assert tm.set_flagged( "s", "t1", tmp_path )[ "flagged_at" ] == "t1"
        cleared = tm.set_flagged( "s", None, tmp_path )
        assert cleared[ "flagged_at" ] is None
        assert cleared[ "tasks" ][ "1" ][ "item_id" ] == "u1"
