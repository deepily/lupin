#!/usr/bin/env python3
"""
Unit tests — task-store mirror C8 failure spool (Phase 2).

Venue: :7999-eligible / local — pure file IO under tmp_path.
Covers spool_path / append_entry / read_entries / rewrite_entries /
partition_expired to 100% lines/branches/functions.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import task_store_spool as sp


class TestSpoolPath:

    def test_per_session_filename( self, tmp_path ):
        assert sp.spool_path( "sid-1", base_dir=tmp_path ).name == ".task-store-spool-sid-1.jsonl"

    def test_empty_session_collapses_to_unknown( self, tmp_path ):
        assert sp.spool_path( "", base_dir=tmp_path ).name == ".task-store-spool-unknown.jsonl"

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
            assert str( sp.spool_path( "s" ) ) == "/data/root/.task-store-spool-s.jsonl"


class TestAppendAndRead:

    def test_fifo_round_trip( self, tmp_path ):
        sp.append_entry( "s", { "op": "create", "ts": 1.0 }, tmp_path )
        sp.append_entry( "s", { "op": "transition", "ts": 2.0 }, tmp_path )
        assert [ e[ "op" ] for e in sp.read_entries( "s", base_dir=tmp_path ) ] == [ "create", "transition" ]

    def test_missing_file_reads_empty( self, tmp_path ):
        assert sp.read_entries( "absent", base_dir=tmp_path ) == [ ]

    def test_malformed_and_blank_lines_dropped( self, tmp_path ):
        sp.spool_path( "s", tmp_path ).write_text( '{"op": "a", "ts": 1}\n\n{bad json\n[1,2]\n{"op": "b", "ts": 2}\n' )
        assert [ e[ "op" ] for e in sp.read_entries( "s", base_dir=tmp_path ) ] == [ "a", "b" ]

    def test_append_to_unwritable_dir_raises( self, tmp_path ):
        with pytest.raises( OSError ):
            sp.append_entry( "s", { "op": "a", "ts": 1 }, tmp_path / "no-such-subdir" )


class TestRewriteEntries:

    def test_empty_entries_removes_file( self, tmp_path ):
        sp.append_entry( "s", { "op": "a", "ts": 1 }, tmp_path )
        sp.rewrite_entries( "s", [ ], tmp_path )
        assert not sp.spool_path( "s", tmp_path ).exists()

    def test_empty_entries_on_missing_file_is_noop( self, tmp_path ):
        sp.rewrite_entries( "s", [ ], tmp_path )
        assert not sp.spool_path( "s", tmp_path ).exists()

    def test_rewrite_preserves_fifo_atomically( self, tmp_path ):
        sp.append_entry( "s", { "op": "a", "ts": 1 }, tmp_path )
        sp.rewrite_entries( "s", [ { "op": "b", "ts": 2 }, { "op": "c", "ts": 3 } ], tmp_path )
        assert [ e[ "op" ] for e in sp.read_entries( "s", base_dir=tmp_path ) ] == [ "b", "c" ]
        assert [ p.name for p in tmp_path.iterdir() ] == [ ".task-store-spool-s.jsonl" ]

    def test_rewrite_to_unwritable_dir_raises( self, tmp_path ):
        with pytest.raises( OSError ):
            sp.rewrite_entries( "s", [ { "op": "a", "ts": 1 } ], tmp_path / "no-such-subdir" )


class TestPartitionExpired:

    def test_live_vs_expired_split_preserves_order( self ):
        entries = [
            { "op": "a", "ts": 100.0 },   # age 50 → live
            { "op": "b", "ts": 10.0 },    # age 140 → expired
            { "op": "c", "ts": 120.0 },   # age 30 → live
        ]
        live, expired = sp.partition_expired( entries, now_epoch=150.0, ttl_seconds=60 )
        assert [ e[ "op" ] for e in live ] == [ "a", "c" ]
        assert [ e[ "op" ] for e in expired ] == [ "b" ]

    def test_boundary_age_exactly_ttl_is_live( self ):
        live, expired = sp.partition_expired( [ { "ts": 90.0 } ], now_epoch=150.0, ttl_seconds=60 )
        assert live and not expired

    @pytest.mark.parametrize( "bad_ts", [ None, "100", True ] )
    def test_untrustworthy_ts_counts_as_expired( self, bad_ts ):
        live, expired = sp.partition_expired( [ { "op": "a", "ts": bad_ts } ], 150.0, 60 )
        assert not live and len( expired ) == 1

    def test_missing_ts_counts_as_expired( self ):
        live, expired = sp.partition_expired( [ { "op": "a" } ], 150.0, 60 )
        assert not live and len( expired ) == 1

    def test_empty_input( self ):
        assert sp.partition_expired( [ ], 150.0, 60 ) == ( [ ], [ ] )
