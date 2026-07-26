#!/usr/bin/env python3
"""
Unit tests — task-store mirror correlation map artifact (Phase 2 + bug 9b23d5bc).

Venue: :7999-eligible / local — pure file IO under tmp_path.
Covers map_path / map_key / read_map / write_map / record_task / lookup_task /
current_generation / bump_generation / set_flagged to 100%
lines/branches/functions, including the generation-keyed schema and the
LEGACY-MAP RESET (no-migration doctrine) introduced for bug 9b23d5bc.
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

EMPTY = { "tasks": { }, "flagged_at": None, "generation": 0 }


class TestMapPath:

    def test_per_session_filename( self, tmp_path ):
        assert tm.map_path( "sid-1", base_dir=tmp_path ).name == ".task-store-map-sid-1.json"

    def test_empty_session_collapses_to_unknown( self, tmp_path ):
        assert tm.map_path( "", base_dir=tmp_path ).name == ".task-store-map-unknown.json"

    def test_base_dir_none_resolves_the_FLEET_DATA_ROOT( self ):
        """
        Row 8758d0b1 / f56fc63b — runtime state moved OUT of the repo.

        `base_dir=None` no longer means the project root: it means
        `<DEEPILY_DATA_DIR>/<repo-name>`. A gitignored path INSIDE the tree is on
        `git clean -xdf`'s kill list rather than shielded by it (measured: a dry run
        listed 448 runtime files as "would remove", cargo-bearing holds among them).
        """
        with pytest.MonkeyPatch.context() as mp:
            import cosa.utils.util as cu
            mp.setattr( cu, "get_project_root", lambda: "/proj/root" )
            mp.setenv( "DEEPILY_DATA_DIR", "/data" )
            assert str( tm.map_path( "s" ) ) == "/data/root/.task-store-map-s.json"


class TestMapKey:

    def test_composes_generation_and_counter( self ):
        assert tm.map_key( 0, "5" ) == "0:5"
        assert tm.map_key( 3, "1" ) == "3:1"

    def test_stringifies_non_string_counter( self ):
        assert tm.map_key( 2, 7 ) == "2:7"


class TestReadMap:

    def test_missing_file_is_empty_map( self, tmp_path ):
        assert tm.read_map( "absent", base_dir=tmp_path ) == EMPTY

    def test_round_trip( self, tmp_path ):
        tm.write_map( "s", { "tasks": { "0:1": { "item_id": "u", "last_status": "pending" } },
                             "flagged_at": "t0", "generation": 2 }, tmp_path )
        assert tm.read_map( "s", base_dir=tmp_path ) == {
            "tasks": { "0:1": { "item_id": "u", "last_status": "pending" } },
            "flagged_at": "t0", "generation": 2,
        }

    def test_malformed_json_degrades_to_empty( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( "{bad" )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_non_dict_root_degrades_to_empty( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( "[1, 2]" )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_non_dict_tasks_normalized_empty( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( '{"tasks": "x", "flagged_at": null, "generation": 0}' )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_non_dict_task_entries_dropped( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text(
            '{"tasks": {"0:1": "junk", "0:2": {"item_id": "u"}}, "generation": 0}' )
        assert tm.read_map( "s", base_dir=tmp_path )[ "tasks" ] == { "0:2": { "item_id": "u" } }

    def test_non_string_flagged_at_normalized_none( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text( '{"tasks": {}, "flagged_at": 7, "generation": 0}' )
        assert tm.read_map( "s", base_dir=tmp_path )[ "flagged_at" ] is None

    def test_valid_generation_preserved( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text(
            '{"tasks": {"4:1": {"item_id": "u"}}, "flagged_at": null, "generation": 4}' )
        data = tm.read_map( "s", base_dir=tmp_path )
        assert data[ "generation" ] == 4
        assert data[ "tasks" ] == { "4:1": { "item_id": "u" } }


class TestLegacyMapReset:
    """bug 9b23d5bc — a pre-fix map (no valid generation) RESETS its tasks."""

    def test_missing_generation_resets_tasks_preserves_flag( self, tmp_path ):
        # Pre-fix shape: counter-only keys, NO generation field.
        tm.map_path( "s", tmp_path ).write_text(
            '{"tasks": {"1": {"item_id": "old", "last_status": "in_progress"}}, "flagged_at": "t9"}' )
        data = tm.read_map( "s", base_dir=tmp_path )
        assert data == { "tasks": { }, "flagged_at": "t9", "generation": 0 }

    def test_non_int_generation_resets( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text(
            '{"tasks": {"1": {"item_id": "old"}}, "flagged_at": null, "generation": "two"}' )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_bool_generation_resets( self, tmp_path ):
        # JSON true → Python bool (an int subclass) — must NOT be accepted.
        tm.map_path( "s", tmp_path ).write_text(
            '{"tasks": {"1": {"item_id": "old"}}, "flagged_at": null, "generation": true}' )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY

    def test_negative_generation_resets( self, tmp_path ):
        tm.map_path( "s", tmp_path ).write_text(
            '{"tasks": {"1": {"item_id": "old"}}, "flagged_at": null, "generation": -3}' )
        assert tm.read_map( "s", base_dir=tmp_path ) == EMPTY


class TestWriteMap:

    def test_atomic_write_leaves_no_tmp_files( self, tmp_path ):
        tm.write_map( "s", EMPTY, tmp_path )
        assert [ p.name for p in tmp_path.iterdir() ] == [ ".task-store-map-s.json" ]

    def test_unwritable_dir_raises_oserror( self, tmp_path ):
        with pytest.raises( OSError ):
            tm.write_map( "s", EMPTY, tmp_path / "no-such-subdir" )


class TestCurrentGeneration:

    def test_fresh_map_is_zero( self, tmp_path ):
        assert tm.current_generation( "s", base_dir=tmp_path ) == 0

    def test_reads_persisted_generation( self, tmp_path ):
        tm.write_map( "s", { "tasks": { }, "flagged_at": None, "generation": 5 }, tmp_path )
        assert tm.current_generation( "s", base_dir=tmp_path ) == 5


class TestBumpGeneration:

    def test_bump_increments_and_returns( self, tmp_path ):
        assert tm.bump_generation( "s", base_dir=tmp_path ) == 1
        assert tm.bump_generation( "s", base_dir=tmp_path ) == 2
        assert tm.current_generation( "s", base_dir=tmp_path ) == 2

    def test_bump_preserves_tasks_and_flag( self, tmp_path ):
        tm.record_task( "s", 0, "1", "u1", "pending", tmp_path )
        tm.set_flagged( "s", "t0", tmp_path )
        tm.bump_generation( "s", base_dir=tmp_path )
        data = tm.read_map( "s", base_dir=tmp_path )
        assert data[ "generation" ] == 1
        assert data[ "tasks" ][ "0:1" ][ "item_id" ] == "u1"
        assert data[ "flagged_at" ] == "t0"


class TestRecordTask:

    def test_inserts_entry_under_gen_key_and_returns_map( self, tmp_path ):
        result = tm.record_task( "s", 0, "3", "uuid-3", "pending", tmp_path )
        assert result[ "tasks" ][ "0:3" ] == { "item_id": "uuid-3", "last_status": "pending" }
        assert tm.read_map( "s", base_dir=tmp_path ) == result

    def test_distinct_generations_do_not_collide( self, tmp_path ):
        tm.record_task( "s", 0, "1", "old-uuid", "in_progress", tmp_path )
        tm.record_task( "s", 1, "1", "new-uuid", "pending", tmp_path )
        data = tm.read_map( "s", base_dir=tmp_path )
        assert data[ "tasks" ][ "0:1" ][ "item_id" ] == "old-uuid"
        assert data[ "tasks" ][ "1:1" ][ "item_id" ] == "new-uuid"

    def test_upsert_preserves_other_entries_flag_and_generation( self, tmp_path ):
        tm.record_task( "s", 0, "1", "u1", "pending", tmp_path )
        tm.set_flagged( "s", "t0", tmp_path )
        tm.bump_generation( "s", base_dir=tmp_path )            # generation → 1
        tm.record_task( "s", 1, "1", "u1", "in_progress", tmp_path )
        data = tm.read_map( "s", base_dir=tmp_path )
        assert data[ "tasks" ][ "1:1" ][ "last_status" ] == "in_progress"
        assert data[ "tasks" ][ "0:1" ][ "last_status" ] == "pending"
        assert data[ "flagged_at" ] == "t0"
        assert data[ "generation" ] == 1

    def test_harness_id_stringified( self, tmp_path ):
        tm.record_task( "s", 0, 7, "u7", "pending", tmp_path )
        assert "0:7" in tm.read_map( "s", base_dir=tmp_path )[ "tasks" ]


class TestLookupTask:

    def test_hit_returns_entry( self, tmp_path ):
        tm.record_task( "s", 2, "5", "u5", "pending", tmp_path )
        assert tm.lookup_task( "s", 2, "5", tmp_path ) == { "item_id": "u5", "last_status": "pending" }

    def test_miss_returns_none( self, tmp_path ):
        assert tm.lookup_task( "s", 0, "404", tmp_path ) is None

    def test_wrong_generation_is_a_miss( self, tmp_path ):
        tm.record_task( "s", 0, "1", "u1", "pending", tmp_path )
        assert tm.lookup_task( "s", 1, "1", tmp_path ) is None


class TestSetFlagged:

    def test_set_then_clear_preserves_tasks_and_generation( self, tmp_path ):
        tm.record_task( "s", 0, "1", "u1", "pending", tmp_path )
        tm.bump_generation( "s", base_dir=tmp_path )
        assert tm.set_flagged( "s", "t1", tmp_path )[ "flagged_at" ] == "t1"
        cleared = tm.set_flagged( "s", None, tmp_path )
        assert cleared[ "flagged_at" ] is None
        assert cleared[ "tasks" ][ "0:1" ][ "item_id" ] == "u1"
        assert cleared[ "generation" ] == 1
