"""
RED-first unit tests for the clobber-trap guard (store cda7bf8b leg 5).

The thing that would make these red CAN happen: a partial payload against a
live config is exactly the write shape that wiped configs in the 8093520f
record. Every refusal branch is exercised with a payload that a careless
runbook would actually produce.

100% line + branch + function on src/scripts/vertex_publisher_config_guard.py.
"""

import json
import sys
import os

import pytest

# src/scripts is not a package — bootstrap-exception path insert (LUPIN_ROOT required, fail loud)
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
_scripts_path = os.path.join( _lupin_root, "src", "scripts" )
if _scripts_path not in sys.path: sys.path.insert( 0, _scripts_path )

from vertex_publisher_config_guard import (
    find_missing_keys,
    find_added_keys,
    check_payload,
    main,
    quick_smoke_test,
)


LIVE = {
    "loggingConfig"       : { "enabled": True, "samplingRate": 1.0 },
    "claudeFeatureConfig" : { "advancedAiEnabled": False },
}


class TestFindMissingKeys:

    def test_complete_candidate_has_no_missing( self ):
        assert find_missing_keys( LIVE, json.loads( json.dumps( LIVE ) ) ) == []

    def test_top_level_omission_detected( self ):
        candidate = { "loggingConfig": { "enabled": True, "samplingRate": 1.0 } }
        assert find_missing_keys( LIVE, candidate ) == [ "claudeFeatureConfig" ]

    def test_nested_omission_detected_with_dotted_path( self ):
        candidate = {
            "loggingConfig"       : { "enabled": True },  # samplingRate dropped
            "claudeFeatureConfig" : { "advancedAiEnabled": False },
        }
        assert find_missing_keys( LIVE, candidate ) == [ "loggingConfig.samplingRate" ]

    def test_non_dict_nodes_terminate_recursion( self ):
        # live value is a scalar where candidate has a dict (and vice versa) — replaced-whole, no error
        assert find_missing_keys( { "a": 1 }, { "a": { "b": 2 } } ) == []
        assert find_missing_keys( { "a": { "b": 2 } }, { "a": 1 } ) == []

    def test_non_dict_roots_return_empty( self ):
        assert find_missing_keys( [ 1, 2 ], { "a": 1 } ) == []
        assert find_missing_keys( { "a": 1 }, "scalar" ) == []


class TestFindAddedKeys:

    def test_no_additions_on_identical( self ):
        assert find_added_keys( LIVE, json.loads( json.dumps( LIVE ) ) ) == []

    def test_top_level_addition_detected( self ):
        candidate = { **LIVE, "dataSharingEnabledProvider": "anthropic" }
        assert find_added_keys( LIVE, candidate ) == [ "dataSharingEnabledProvider" ]

    def test_nested_addition_detected_with_dotted_path( self ):
        candidate = {
            "loggingConfig"       : { "enabled": True, "samplingRate": 1.0, "extraKnob": 3 },
            "claudeFeatureConfig" : { "advancedAiEnabled": False },
        }
        assert find_added_keys( LIVE, candidate ) == [ "loggingConfig.extraKnob" ]

    def test_non_dict_roots_return_empty( self ):
        assert find_added_keys( "scalar", { "a": 1 } ) == []


class TestCheckPayload:

    def test_complete_candidate_allowed( self ):
        ok, report = check_payload( LIVE, json.loads( json.dumps( LIVE ) ) )
        assert ok is True
        assert report[ "reasons" ] == []

    def test_partial_candidate_refused_clobber_named( self ):
        ok, report = check_payload( LIVE, { "loggingConfig": { "enabled": False, "samplingRate": 1.0 } } )
        assert ok is False
        assert any( "CLOBBER" in r for r in report[ "reasons" ] )
        assert "claudeFeatureConfig" in report[ "missing" ]

    def test_addition_refused_without_flag( self ):
        candidate = { **json.loads( json.dumps( LIVE ) ), "dataSharingEnabledProvider": "anthropic" }
        ok, report = check_payload( LIVE, candidate )
        assert ok is False
        assert any( "SILENT OPT-IN" in r for r in report[ "reasons" ] )

    def test_addition_allowed_with_flag_but_still_reported( self ):
        candidate = { **json.loads( json.dumps( LIVE ) ), "dataSharingEnabledProvider": "anthropic" }
        ok, report = check_payload( LIVE, candidate, allow_additions=True )
        assert ok is True
        assert report[ "added" ] == [ "dataSharingEnabledProvider" ]

    def test_partial_and_additive_refused_with_both_reasons( self ):
        candidate = { "loggingConfig": { "enabled": True, "samplingRate": 1.0 }, "newField": 1 }
        ok, report = check_payload( LIVE, candidate )
        assert ok is False
        assert len( report[ "reasons" ] ) == 2


class TestMainCli:

    def _write( self, tmp_path, name, obj ):
        p = tmp_path / name
        p.write_text( json.dumps( obj ) )
        return str( p )

    def test_allow_exit_zero( self, tmp_path, capsys ):
        live = self._write( tmp_path, "live.json", LIVE )
        cand = self._write( tmp_path, "cand.json", LIVE )
        assert main( [ "--live", live, "--candidate", cand ] ) == 0
        assert "ALLOW" in capsys.readouterr().out

    def test_refuse_exit_one_on_partial( self, tmp_path, capsys ):
        live = self._write( tmp_path, "live.json", LIVE )
        cand = self._write( tmp_path, "cand.json", { "loggingConfig": { "enabled": True, "samplingRate": 1.0 } } )
        assert main( [ "--live", live, "--candidate", cand ] ) == 1
        assert "REFUSED" in capsys.readouterr().out

    def test_allow_additions_flag_prints_acknowledgement( self, tmp_path, capsys ):
        live = self._write( tmp_path, "live.json", LIVE )
        cand = self._write( tmp_path, "cand.json", { **LIVE, "extra": 1 } )
        assert main( [ "--live", live, "--candidate", cand, "--allow-additions" ] ) == 0
        out = capsys.readouterr().out
        assert "ALLOW" in out and "acknowledged additions" in out

    def test_unreadable_input_refused( self, tmp_path, capsys ):
        live = self._write( tmp_path, "live.json", LIVE )
        assert main( [ "--live", live, "--candidate", str( tmp_path / "absent.json" ) ] ) == 1
        assert "cannot load inputs" in capsys.readouterr().out

    def test_invalid_json_refused( self, tmp_path, capsys ):
        live = self._write( tmp_path, "live.json", LIVE )
        bad  = tmp_path / "bad.json"
        bad.write_text( "{not json" )
        assert main( [ "--live", live, "--candidate", str( bad ) ] ) == 1
        assert "cannot load inputs" in capsys.readouterr().out

    def test_bad_flags_systemexit( self ):
        with pytest.raises( SystemExit ):
            main( [ "--live-only-no-candidate" ] )


class TestQuickSmokeTest:

    def test_quick_smoke_test_runs_clean( self, capsys ):
        quick_smoke_test()
        out = capsys.readouterr().out
        assert "complete -> True" in out
        assert "partial  -> False" in out
        assert "additive -> False" in out
        assert "additive+flag -> True" in out
