#!/usr/bin/env python3
"""
Unit tests — heartbeat acked-inbound ledger (spec part (c)).

Venue: :7999-eligible / local — pure file IO under tmp_path, no server.
Covers acked_ledger_path / read_acked_qids / mark_acked + the smoke entrypoint
to 100% lines/branches.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import heartbeat_acked_ledger as al


class TestAckedLedgerPath:

    def test_per_session_filename( self, tmp_path ):
        assert al.acked_ledger_path( "sid-1", base_dir=tmp_path ).name == ".heartbeat-acked-sid-1.json"

    def test_empty_session_collapses_to_unknown( self, tmp_path ):
        assert al.acked_ledger_path( "", base_dir=tmp_path ).name == ".heartbeat-acked-unknown.json"

    def test_base_dir_none_resolves_project_root( self ):
        # base_dir=None delegates to heartbeat_hold._resolve_base_dir → cu.get_project_root.
        with pytest.MonkeyPatch.context() as mp:
            import cosa.utils.util as cu
            mp.setattr( cu, "get_project_root", lambda: "/proj/root" )
            assert str( al.acked_ledger_path( "s" ) ) == "/proj/root/.heartbeat-acked-s.json"


class TestReadAckedQids:

    def test_missing_file_is_empty_set( self, tmp_path ):
        assert al.read_acked_qids( "absent", base_dir=tmp_path ) == set()

    def test_valid_array_reads_back_as_set( self, tmp_path ):
        al.acked_ledger_path( "s", base_dir=tmp_path ).write_text( '["q1", "q2"]' )
        assert al.read_acked_qids( "s", base_dir=tmp_path ) == { "q1", "q2" }

    def test_non_string_members_skipped( self, tmp_path ):
        al.acked_ledger_path( "s", base_dir=tmp_path ).write_text( '["q1", 7, null, "q2"]' )
        assert al.read_acked_qids( "s", base_dir=tmp_path ) == { "q1", "q2" }

    def test_non_array_json_is_empty_set( self, tmp_path ):
        al.acked_ledger_path( "s", base_dir=tmp_path ).write_text( '{"not": "a list"}' )
        assert al.read_acked_qids( "s", base_dir=tmp_path ) == set()

    def test_malformed_json_is_degrade_safe_empty( self, tmp_path ):
        al.acked_ledger_path( "s", base_dir=tmp_path ).write_text( "{bad json" )
        assert al.read_acked_qids( "s", base_dir=tmp_path ) == set()


class TestMarkAcked:

    def test_write_then_read_round_trip( self, tmp_path ):
        assert al.mark_acked( "s", [ "q1", "q2" ], base_dir=tmp_path ) == [ "q1", "q2" ]
        assert al.read_acked_qids( "s", base_dir=tmp_path ) == { "q1", "q2" }

    def test_merge_is_union_no_clobber( self, tmp_path ):
        al.mark_acked( "s", [ "q1", "q2" ], base_dir=tmp_path )
        assert al.mark_acked( "s", [ "q2", "q3" ], base_dir=tmp_path ) == [ "q1", "q2", "q3" ]

    def test_non_string_members_ignored( self, tmp_path ):
        assert al.mark_acked( "s", [ "q1", 7, None ], base_dir=tmp_path ) == [ "q1" ]

    def test_returns_sorted( self, tmp_path ):
        assert al.mark_acked( "s", [ "qc", "qa", "qb" ], base_dir=tmp_path ) == [ "qa", "qb", "qc" ]

    def test_raises_oserror_on_unwritable_dir( self, tmp_path ):
        # tmp-write into a path whose parent does not exist → OSError propagates.
        with pytest.raises( OSError ):
            al.mark_acked( "s", [ "q1" ], base_dir=tmp_path / "does-not-exist" )


def test_quick_smoke_test_passes():
    assert al.quick_smoke_test() is True
