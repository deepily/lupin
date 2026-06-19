#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.cluster

Targets the Phase-0 clustering surface:
  - helpers: _normalize_classname, _extract_first_real_frame, _compute_seed_key,
             _signature_from_key, _guess_affected_files
  - public:  heuristic_seed, llm_refine
  - internals: _cap_enforce, _validate_refined

Pure-logic module — depends only on the in-package Pydantic state models
(FailureCluster / TestRemediationContext). NO LLM / SDK / network / disk.
The only async surface (llm_refine) is driven with plain async callables /
AsyncMock-style refine_fn stubs; zero spend.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Rachel 🕊️ (CoSA coverage campaign, TFE lane).
"""

import asyncio

import pytest

import cosa.agents.test_fix_expediter.cluster as cl
from cosa.agents.test_fix_expediter.cluster import (
    heuristic_seed,
    llm_refine,
    DEFAULT_MAX_CLUSTERS,
    _NO_FRAME_SENTINEL,
)
from cosa.agents.test_fix_expediter.state import FailureCluster, TestRemediationContext


# ----------------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------------
def _ctx( failures ):
    """Build a minimal valid TestRemediationContext around a failures list."""
    return TestRemediationContext(
        source_test_suite_job_id = "ts-x", snapshot_path="p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [], summary={ "all_passed": False },
        failures                 = failures,
        original_test_types      = [], user_id="u", user_email="e@e.com", session_id="s",
    )


def _cluster( cid, indices, files=None, conf=0.7 ):
    return FailureCluster(
        cluster_id             = cid,
        failure_indices        = indices,
        shared_error_signature = f"sig-{cid}",
        hypothesis             = "",
        affected_files_guess   = files if files is not None else [],
        confidence             = conf,
    )


# ----------------------------------------------------------------------------
# _normalize_classname
# ----------------------------------------------------------------------------
class TestNormalizeClassname:
    def test_empty_returns_empty( self ):
        assert cl._normalize_classname( "" ) == ""

    def test_plain_classname_unchanged( self ):
        assert cl._normalize_classname( "src.tests.test_foo.TestFoo" ) == "src.tests.test_foo.TestFoo"

    def test_bracketed_suffix_stripped( self ):
        assert cl._normalize_classname( "TestFoo[param-1]" ) == "TestFoo"


# ----------------------------------------------------------------------------
# _extract_first_real_frame
# ----------------------------------------------------------------------------
class TestExtractFirstRealFrame:
    def test_empty_traceback_returns_sentinel( self ):
        assert cl._extract_first_real_frame( "" ) == _NO_FRAME_SENTINEL

    def test_first_file_quote_pattern( self ):
        tb = 'File "src/cosa/auth/tokens.py", line 42, in refresh'
        assert cl._extract_first_real_frame( tb ) == "src/cosa/auth/tokens.py:42"

    def test_skips_pytest_infra_frame_then_returns_real( self ):
        tb = (
            'File "_pytest/runner.py", line 1, in run\n'
            'File "src/cosa/rest/queue.py", line 20, in g'
        )
        assert cl._extract_first_real_frame( tb ) == "src/cosa/rest/queue.py:20"

    def test_all_infra_frames_returns_sentinel( self ):
        tb = (
            'File "_pytest/runner.py", line 1, in a\n'
            'File "pluggy/hooks.py", line 2, in b'
        )
        assert cl._extract_first_real_frame( tb ) == _NO_FRAME_SENTINEL

    def test_fallback_pattern_used_when_no_quote_match( self ):
        # No `File "...", line N` form — exercises the fallback `(\S+\.py):(\d+)`
        tb = "boom at src/cosa/db/c.py:30 during teardown"
        assert cl._extract_first_real_frame( tb ) == "src/cosa/db/c.py:30"


# ----------------------------------------------------------------------------
# _compute_seed_key
# ----------------------------------------------------------------------------
class TestComputeSeedKey:
    def test_uses_classname_and_frame( self ):
        failure = {
            "classname": "src.tests.test_a.TestA[x]",
            "traceback": 'File "src/cosa/a.py", line 10, in f',
        }
        assert cl._compute_seed_key( failure ) == ( "src.tests.test_a.TestA", "src/cosa/a.py:10" )

    def test_missing_fields_default_empty( self ):
        # No classname / traceback keys -> ("", sentinel)
        assert cl._compute_seed_key( {} ) == ( "", _NO_FRAME_SENTINEL )


# ----------------------------------------------------------------------------
# _signature_from_key
# ----------------------------------------------------------------------------
class TestSignatureFromKey:
    def test_sentinel_frame_and_unknown_classname_no_message( self ):
        sig = cl._signature_from_key( ( "", _NO_FRAME_SENTINEL ) )
        assert "<unknown>" in sig
        assert "no source frame" in sig

    def test_real_frame_with_classname_and_message( self ):
        sig = cl._signature_from_key( ( "TestFoo", "x.py:5" ), sample_message="assert 1 == 2" )
        assert sig == "TestFoo at x.py:5: assert 1 == 2"

    def test_message_truncated_to_80_chars( self ):
        long_msg = "E" * 200
        sig = cl._signature_from_key( ( "TestFoo", "x.py:5" ), sample_message=long_msg )
        # 80-char message slice appears; the 81st 'E' does not push it past 80
        assert ( "E" * 80 ) in sig
        assert ( "E" * 81 ) not in sig


# ----------------------------------------------------------------------------
# _guess_affected_files
# ----------------------------------------------------------------------------
class TestGuessAffectedFiles:
    def test_classname_with_upper_class_drops_last_part( self ):
        key = ( "src.tests.unit.test_auth.TestLogin", "src/cosa/auth/tokens.py:42" )
        failures = [ { "traceback": 'File "src/cosa/auth/tokens.py", line 42, in f' } ]
        out = cl._guess_affected_files( key, failures, [ 0 ] )
        assert "src/tests/unit/test_auth.py" in out          # class part dropped
        assert "src/cosa/auth/tokens.py" in out              # frame file added

    def test_classname_lowercase_last_keeps_all_parts( self ):
        # last segment lowercase -> module_parts = parts (no drop)
        key = ( "src.tests.module_func", _NO_FRAME_SENTINEL )
        out = cl._guess_affected_files( key, [ { "traceback": "" } ], [ 0 ] )
        assert "src/tests/module_func.py" in out

    def test_classname_without_dot_skipped( self ):
        # no "." -> block 1 skipped; sentinel frame -> block 2 skipped
        out = cl._guess_affected_files( ( "TestFoo", _NO_FRAME_SENTINEL ), [ { "traceback": "" } ], [ 0 ] )
        assert out == []

    def test_frame_file_dedup_against_test_file( self ):
        # frame file equals the derived test file -> NOT appended twice
        key = ( "src.tests.test_x.TestX", "src/tests/test_x.py:9" )
        out = cl._guess_affected_files( key, [ { "traceback": "" } ], [ 0 ] )
        assert out.count( "src/tests/test_x.py" ) == 1

    def test_empty_frame_file_skipped( self ):
        # frame is ":5" -> frame_file == "" -> `if frame_file` false branch
        key = ( "", ":5" )
        out = cl._guess_affected_files( key, [ { "traceback": "" } ], [ 0 ] )
        assert out == []

    def test_empty_indices_skips_additional_block( self ):
        key = ( "", _NO_FRAME_SENTINEL )
        out = cl._guess_affected_files( key, [], [] )
        assert out == []

    def test_additional_frames_dedup_and_skip_infra( self ):
        # block 3's `additional` regex matches the `file.py:N` colon form.
        # first_tb has: a DUP of the frame file, a NEW file, and an INFRA file.
        key = ( "", "src/cosa/a.py:1" )
        tb  = "fail src/cosa/a.py:1 then src/cosa/b.py:2 and _pytest/runner.py:3 done"
        out = cl._guess_affected_files( key, [ { "traceback": tb } ], [ 0 ] )
        assert out == [ "src/cosa/a.py", "src/cosa/b.py" ]

    def test_caps_at_five_files( self ):
        key = ( "", _NO_FRAME_SENTINEL )
        tb  = " ".join( f"src/f{i}.py:{i}" for i in range( 8 ) )
        out = cl._guess_affected_files( key, [ { "traceback": tb } ], [ 0 ] )
        assert len( out ) == 5


# ----------------------------------------------------------------------------
# heuristic_seed
# ----------------------------------------------------------------------------
class TestHeuristicSeed:
    def test_empty_failures_returns_empty( self ):
        assert heuristic_seed( _ctx( [] ) ) == []

    def test_single_failure_one_cluster( self ):
        ctx = _ctx( [ {
            "classname": "src.tests.unit.test_auth.TestLogin",
            "name": "test_ok",
            "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
            "message": "assert 401 == 200",
        } ] )
        clusters = heuristic_seed( ctx )
        assert len( clusters ) == 1
        assert clusters[ 0 ].cluster_id == "C1"
        assert clusters[ 0 ].failure_indices == [ 0 ]
        assert clusters[ 0 ].confidence == 0.7
        assert "src/cosa/auth/tokens.py" in clusters[ 0 ].affected_files_guess

    def test_same_key_groups_one_cluster( self ):
        # two failures, identical (classname, frame) -> key reused (`if key not in` false arc)
        f = {
            "classname": "src.tests.test_v.TestV",
            "traceback": 'File "src/v.py", line 8, in z',
        }
        ctx = _ctx( [ dict( f, name="a", message="m1" ), dict( f, name="b", message="m2" ) ] )
        clusters = heuristic_seed( ctx )
        assert len( clusters ) == 1
        assert sorted( clusters[ 0 ].failure_indices ) == [ 0, 1 ]

    def test_distinct_keys_ordered_clusters( self ):
        ctx = _ctx( [
            { "classname": "src.test_a.TestA", "name": "t1", "message": "e1",
              "traceback": 'File "src/a.py", line 10, in f' },
            { "classname": "src.test_b.TestB", "name": "t2", "message": "e2",
              "traceback": 'File "src/b.py", line 20, in g' },
        ] )
        clusters = heuristic_seed( ctx )
        assert [ c.cluster_id for c in clusters ] == [ "C1", "C2" ]


# ----------------------------------------------------------------------------
# llm_refine
# ----------------------------------------------------------------------------
class TestLlmRefine:
    def _three_seeds( self ):
        return [
            _cluster( "C1", [ 0, 1, 2 ], files=[ "a.py" ] ),
            _cluster( "C2", [ 3 ],       files=[ "b.py" ] ),
            _cluster( "C3", [ 4 ],       files=[ "a.py", "c.py" ] ),
        ]

    def test_empty_seeds_returns_empty( self ):
        assert asyncio.run( llm_refine( _ctx( [] ), [] ) ) == []

    def test_under_cap_returns_seeds_unchanged( self ):
        seeds = self._three_seeds()
        out   = asyncio.run( llm_refine( _ctx( [] ), seeds, max_clusters=8 ) )
        assert len( out ) == 3
        assert out is not None

    def test_default_max_clusters_constant( self ):
        # The default value is wired to DEFAULT_MAX_CLUSTERS
        assert DEFAULT_MAX_CLUSTERS == 8
        out = asyncio.run( llm_refine( _ctx( [] ), self._three_seeds() ) )
        assert len( out ) == 3

    def test_max_clusters_below_one_clamped( self ):
        # max_clusters=0 -> clamped to 1 -> all merged into single cluster
        out = asyncio.run( llm_refine( _ctx( [] ), self._three_seeds(), max_clusters=0 ) )
        assert len( out ) == 1
        all_idx = []
        for c in out: all_idx.extend( c.failure_indices )
        assert sorted( all_idx ) == [ 0, 1, 2, 3, 4 ]

    def test_cap_enforce_merges_smallest( self ):
        out = asyncio.run( llm_refine( _ctx( [] ), self._three_seeds(), max_clusters=2 ) )
        assert len( out ) == 2
        all_idx = []
        for c in out: all_idx.extend( c.failure_indices )
        assert sorted( all_idx ) == [ 0, 1, 2, 3, 4 ]
        assert "Mixed" in out[ -1 ].shared_error_signature

    def test_refine_fn_valid_result_used( self ):
        seeds = self._three_seeds()
        merged = [ _cluster( "R1", [ 0, 1, 2, 3, 4 ] ) ]

        async def refine_fn( ctx, sc, mc ):
            return merged

        out = asyncio.run( llm_refine( _ctx( [] ), seeds, max_clusters=3, refine_fn=refine_fn ) )
        assert out is merged

    def test_refine_fn_invalid_result_falls_back( self ):
        seeds = self._three_seeds()

        async def refine_fn( ctx, sc, mc ):
            # Drops index 4 -> set mismatch -> invalid -> fall back to cap-enforce
            return [ _cluster( "R1", [ 0, 1, 2, 3 ] ) ]

        out = asyncio.run( llm_refine( _ctx( [] ), seeds, max_clusters=3, refine_fn=refine_fn ) )
        # Fallback cap-enforce keeps all 3 seeds (under cap 3)
        assert len( out ) == 3
        all_idx = []
        for c in out: all_idx.extend( c.failure_indices )
        assert sorted( all_idx ) == [ 0, 1, 2, 3, 4 ]

    def test_refine_fn_raises_falls_back( self ):
        seeds = self._three_seeds()

        async def refine_fn( ctx, sc, mc ):
            raise RuntimeError( "boom" )

        out = asyncio.run( llm_refine( _ctx( [] ), seeds, max_clusters=3, refine_fn=refine_fn ) )
        assert len( out ) == 3


# ----------------------------------------------------------------------------
# _cap_enforce
# ----------------------------------------------------------------------------
class TestCapEnforce:
    def test_under_cap_returns_input_identity( self ):
        clusters = [ _cluster( "C1", [ 0 ] ), _cluster( "C2", [ 1 ] ) ]
        out = cl._cap_enforce( clusters, max_clusters=5 )
        assert out is clusters

    def test_merge_dedups_affected_files( self ):
        # Two small clusters merged share "a.py" -> deduped in the tail cluster
        clusters = [
            _cluster( "C1", [ 0, 1, 2 ], files=[ "big.py" ] ),      # largest -> kept
            _cluster( "C2", [ 3 ],       files=[ "a.py", "x.py" ] ),
            _cluster( "C3", [ 4 ],       files=[ "a.py", "y.py" ] ),  # dup "a.py"
        ]
        out = cl._cap_enforce( clusters, max_clusters=2 )
        assert len( out ) == 2
        tail = out[ -1 ]
        assert tail.cluster_id == "C2"
        assert tail.affected_files_guess.count( "a.py" ) == 1       # deduped
        assert tail.confidence == 0.4
        # kept cluster re-sequenced to C1
        assert out[ 0 ].cluster_id == "C1"
        assert out[ 0 ].failure_indices == [ 0, 1, 2 ]


# ----------------------------------------------------------------------------
# _validate_refined
# ----------------------------------------------------------------------------
class TestValidateRefined:
    def _seeds( self ):
        return [ _cluster( "C1", [ 0, 1 ] ), _cluster( "C2", [ 2 ] ) ]

    def test_empty_refined_false( self ):
        assert cl._validate_refined( [], self._seeds(), max_clusters=3 ) is False

    def test_too_many_clusters_false( self ):
        refined = [ _cluster( "R1", [ 0 ] ), _cluster( "R2", [ 1 ] ), _cluster( "R3", [ 2 ] ) ]
        assert cl._validate_refined( refined, self._seeds(), max_clusters=2 ) is False

    def test_duplicate_indices_false( self ):
        refined = [ _cluster( "R1", [ 0, 1 ] ), _cluster( "R2", [ 1, 2 ] ) ]   # 1 duplicated
        assert cl._validate_refined( refined, self._seeds(), max_clusters=3 ) is False

    def test_index_set_mismatch_false( self ):
        refined = [ _cluster( "R1", [ 0, 1, 99 ] ) ]   # extra index 99
        assert cl._validate_refined( refined, self._seeds(), max_clusters=3 ) is False

    def test_valid_true( self ):
        refined = [ _cluster( "R1", [ 0 ] ), _cluster( "R2", [ 1, 2 ] ) ]
        assert cl._validate_refined( refined, self._seeds(), max_clusters=3 ) is True
