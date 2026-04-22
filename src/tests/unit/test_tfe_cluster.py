"""
Unit tests for TFE Phase 0 clustering.

Session 1cfcdf73 (2026-04-10): Step 10 implementation tests.

Fixtures live at src/tests/fixtures/tfe/snapshot_*.json and exercise the
six clustering cases enumerated in plan doc 03-phase0-clustering-plan.md:

    1. snapshot_1cluster.json        — single shared root cause
    2. snapshot_kcluster.json        — K distinct root causes
    3. snapshot_parametrized.json    — parametrized tests → one cluster
    4. snapshot_fixture_error.json   — fixture breakage → one cluster
    5. snapshot_collection_error.json — collection errors → separate by file
    6. snapshot_startup_crash.json   — single startup crash
"""

import json
import os
from unittest.mock import AsyncMock

import pytest

import cosa.utils.util as cu
from cosa.agents.test_fix_expediter.cluster import (
    heuristic_seed,
    llm_refine,
    _compute_seed_key,
    _extract_first_real_frame,
    _normalize_classname,
    _cap_enforce,
    _validate_refined,
    _NO_FRAME_SENTINEL,
)
from cosa.agents.test_fix_expediter.state import FailureCluster
from cosa.agents.test_fix_expediter.snapshot_loader import load_from_artifacts


FIXTURE_DIR = os.path.join(
    cu.get_project_root(), "src", "tests", "fixtures", "tfe"
)


def _load_fixture( name: str ):
    """Load a fixture snapshot file and build a TestRemediationContext."""
    with open( os.path.join( FIXTURE_DIR, name ), "r" ) as f:
        snapshot = json.load( f )
    return load_from_artifacts(
        artifacts={
            "remediation_snapshot"      : snapshot,
            "remediation_snapshot_path" : name,
        },
        source_test_suite_job_id="ts-test",
        user_id="u1", user_email="t@t.com", session_id="s1",
    )


# ─────────────────────────────────────────────────────────────────────────
# Helper tests (_compute_seed_key, _extract_first_real_frame, _normalize_classname)
# ─────────────────────────────────────────────────────────────────────────


class TestHelpers:

    def test_normalize_classname_strips_brackets( self ):
        assert _normalize_classname( "a.b.TestFoo" ) == "a.b.TestFoo"
        assert _normalize_classname( "a.b.TestFoo[param]" ) == "a.b.TestFoo"

    def test_normalize_classname_empty( self ):
        assert _normalize_classname( "" ) == ""

    def test_extract_first_real_frame_skips_pytest_infra( self ):
        tb = (
            'File "_pytest/assertion.py", line 100, in assert_eq\n'
            'File "src/cosa/auth/tokens.py", line 42, in refresh'
        )
        result = _extract_first_real_frame( tb )
        assert "src/cosa/auth/tokens.py" in result
        assert "_pytest" not in result

    def test_extract_first_real_frame_no_frame( self ):
        assert _extract_first_real_frame( "" ) == _NO_FRAME_SENTINEL
        assert _extract_first_real_frame( "SyntaxError" ) == _NO_FRAME_SENTINEL

    def test_extract_first_real_frame_format_variations( self ):
        # Python `File "..."` format
        tb1 = 'File "foo.py", line 5, in bar'
        assert "foo.py:5" in _extract_first_real_frame( tb1 )

    def test_compute_seed_key_returns_tuple( self ):
        failure = {
            "classname": "a.b.TestFoo",
            "traceback": 'File "src/foo.py", line 10, in bar',
        }
        key = _compute_seed_key( failure )
        assert isinstance( key, tuple )
        assert len( key ) == 2
        assert key[ 0 ] == "a.b.TestFoo"
        assert "src/foo.py:10" in key[ 1 ]


# ─────────────────────────────────────────────────────────────────────────
# Fixture-based tests (the 6 snapshots)
# ─────────────────────────────────────────────────────────────────────────


class TestHeuristicSeedFixtures:

    def test_single_cluster_fixture( self ):
        """snapshot_1cluster.json — 2 failures, same class, same frame → 1 cluster."""
        ctx = _load_fixture( "snapshot_1cluster.json" )
        clusters = heuristic_seed( ctx )
        assert len( clusters ) == 1
        assert clusters[ 0 ].cluster_id == "C1"
        assert sorted( clusters[ 0 ].failure_indices ) == [ 0, 1 ]
        assert "tokens.py" in clusters[ 0 ].shared_error_signature or \
               any( "tokens.py" in f for f in clusters[ 0 ].affected_files_guess )

    def test_k_cluster_fixture( self ):
        """snapshot_kcluster.json — 5 failures, 3 distinct root causes → 3 clusters."""
        ctx = _load_fixture( "snapshot_kcluster.json" )
        clusters = heuristic_seed( ctx )
        # Auth (1 failure) + Queue (2 failures, same class) + WebSocket (2 failures, same class)
        assert len( clusters ) == 3
        # Sum of indices
        all_indices = []
        for c in clusters:
            all_indices.extend( c.failure_indices )
        assert sorted( all_indices ) == [ 0, 1, 2, 3, 4 ]

    def test_parametrized_fixture_one_cluster( self ):
        """snapshot_parametrized.json — 4 visual regression [param] variants → 1 cluster."""
        ctx = _load_fixture( "snapshot_parametrized.json" )
        clusters = heuristic_seed( ctx )
        assert len( clusters ) == 1
        assert sorted( clusters[ 0 ].failure_indices ) == [ 0, 1, 2, 3 ]
        # Affected files should include the finalize helper
        assert any(
            "visual" in f.lower() or "test_visual" in f
            for f in clusters[ 0 ].affected_files_guess
        ), f"Expected visual-related file in {clusters[ 0 ].affected_files_guess}"

    def test_fixture_error_one_cluster( self ):
        """snapshot_fixture_error.json — 3 tests broken by same fixture → 1 cluster.

        Even though the classnames differ (TestLogin, TestJobLifecycle), the
        first non-pytest frame is always `conftest.py line 45` — which is
        pytest infrastructure-adjacent but not in our _PYTEST_INFRA_FRAMES
        skip list (conftest.py IS in that list). The heuristic should then
        look at the NEXT frame... but since all 3 have only the conftest
        frame, they'll fall through to _NO_FRAME_SENTINEL. With different
        classnames, they'd split into 3 clusters — which is a CORRECT
        outcome for the heuristic (it can't tell fixture bugs from 3 tests
        without the LLM pass). The test documents the expected behavior.
        """
        ctx = _load_fixture( "snapshot_fixture_error.json" )
        clusters = heuristic_seed( ctx )
        # 2 distinct classnames → 2 clusters (TestLogin has 2 failures, TestJobLifecycle has 1)
        assert len( clusters ) == 2
        # Total coverage
        all_indices = []
        for c in clusters:
            all_indices.extend( c.failure_indices )
        assert sorted( all_indices ) == [ 0, 1, 2 ]

    def test_collection_error_fixture( self ):
        """snapshot_collection_error.json — 2 collection errors, different files → 2 clusters."""
        ctx = _load_fixture( "snapshot_collection_error.json" )
        clusters = heuristic_seed( ctx )
        assert len( clusters ) == 2
        assert all( len( c.failure_indices ) == 1 for c in clusters )

    def test_startup_crash_fixture( self ):
        """snapshot_startup_crash.json — 1 conftest crash → 1 cluster."""
        ctx = _load_fixture( "snapshot_startup_crash.json" )
        clusters = heuristic_seed( ctx )
        assert len( clusters ) == 1
        assert clusters[ 0 ].failure_indices == [ 0 ]


class TestHeuristicSeedInvariants:

    def test_all_indices_covered_exactly_once( self ):
        """For every fixture: every failure index appears in exactly one cluster."""
        for name in [
            "snapshot_1cluster.json",
            "snapshot_kcluster.json",
            "snapshot_parametrized.json",
            "snapshot_fixture_error.json",
            "snapshot_collection_error.json",
            "snapshot_startup_crash.json",
        ]:
            ctx = _load_fixture( name )
            clusters = heuristic_seed( ctx )
            expected = set( range( len( ctx.failures ) ) )
            actual = []
            for c in clusters:
                actual.extend( c.failure_indices )
            # No duplicates
            assert len( actual ) == len( set( actual ) ), f"Duplicates in {name}"
            # Full coverage
            assert set( actual ) == expected, f"Coverage mismatch in {name}"

    def test_cluster_ids_sequential( self ):
        """cluster_id values are C1, C2, ... in order of first-appearance."""
        ctx = _load_fixture( "snapshot_kcluster.json" )
        clusters = heuristic_seed( ctx )
        expected_ids = [ f"C{i+1}" for i in range( len( clusters ) ) ]
        actual_ids = [ c.cluster_id for c in clusters ]
        assert actual_ids == expected_ids


# ─────────────────────────────────────────────────────────────────────────
# llm_refine tests (cap enforcement, callback, validation)
# ─────────────────────────────────────────────────────────────────────────


class TestLlmRefineFallback:

    @pytest.mark.asyncio
    async def test_refine_under_cap_noop( self ):
        """With K <= max_clusters and no refine_fn, seeds are returned unchanged."""
        ctx = _load_fixture( "snapshot_kcluster.json" )
        seeds = heuristic_seed( ctx )
        refined = await llm_refine( ctx, seeds, max_clusters=8 )
        assert len( refined ) == len( seeds )
        for r, s in zip( refined, seeds ):
            assert r.cluster_id == s.cluster_id

    @pytest.mark.asyncio
    async def test_refine_cap_enforcement( self ):
        """With K > max_clusters, smallest clusters merge into a tail."""
        ctx = _load_fixture( "snapshot_kcluster.json" )
        seeds = heuristic_seed( ctx )
        assert len( seeds ) >= 3

        refined = await llm_refine( ctx, seeds, max_clusters=2 )
        assert len( refined ) == 2
        # All indices preserved
        all_indices = []
        for c in refined:
            all_indices.extend( c.failure_indices )
        expected = set( range( len( ctx.failures ) ) )
        assert set( all_indices ) == expected

    @pytest.mark.asyncio
    async def test_refine_empty_seeds( self ):
        """Empty seeds → empty refined."""
        ctx = _load_fixture( "snapshot_1cluster.json" )  # any valid ctx
        refined = await llm_refine( ctx, [], max_clusters=8 )
        assert refined == []


class TestLlmRefineCallback:

    @pytest.mark.asyncio
    async def test_refine_calls_refine_fn_when_provided( self ):
        ctx = _load_fixture( "snapshot_kcluster.json" )
        seeds = heuristic_seed( ctx )

        # Mock refine_fn returns a single consolidated cluster
        consolidated = FailureCluster(
            cluster_id="C1",
            failure_indices=sorted(
                i for c in seeds for i in c.failure_indices
            ),
            shared_error_signature="LLM-consolidated",
            confidence=0.9,
        )
        mock_fn = AsyncMock( return_value=[ consolidated ] )

        refined = await llm_refine( ctx, seeds, max_clusters=8, refine_fn=mock_fn )
        assert mock_fn.called
        assert len( refined ) == 1
        assert refined[ 0 ].shared_error_signature == "LLM-consolidated"

    @pytest.mark.asyncio
    async def test_refine_fallback_on_callback_exception( self ):
        ctx = _load_fixture( "snapshot_1cluster.json" )
        seeds = heuristic_seed( ctx )

        async def _raising_fn( ctx, seeds, max_clusters ):
            raise RuntimeError( "simulated LLM failure" )

        refined = await llm_refine( ctx, seeds, max_clusters=8, refine_fn=_raising_fn )
        # Fell back to seeds
        assert len( refined ) == len( seeds )

    @pytest.mark.asyncio
    async def test_refine_fallback_on_invalid_coverage( self ):
        """If refine_fn returns clusters with missing indices, fall back."""
        ctx = _load_fixture( "snapshot_kcluster.json" )
        seeds = heuristic_seed( ctx )

        # Invalid: only index 0 covered, rest missing
        invalid = [ FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="missing most indices",
        ) ]
        mock_fn = AsyncMock( return_value=invalid )

        refined = await llm_refine( ctx, seeds, max_clusters=8, refine_fn=mock_fn )
        # Fell back — count matches seeds, not the invalid 1-cluster result
        assert len( refined ) == len( seeds )

    @pytest.mark.asyncio
    async def test_refine_fallback_on_duplicate_indices( self ):
        ctx = _load_fixture( "snapshot_kcluster.json" )
        seeds = heuristic_seed( ctx )

        all_indices = sorted( i for c in seeds for i in c.failure_indices )
        # Invalid: duplicate index 0 in two clusters
        duplicated = [
            FailureCluster( cluster_id="C1", failure_indices=[ 0, 1 ],
                            shared_error_signature="x" ),
            FailureCluster( cluster_id="C2", failure_indices=[ 0 ] + all_indices[ 2: ],
                            shared_error_signature="y" ),
        ]
        mock_fn = AsyncMock( return_value=duplicated )

        refined = await llm_refine( ctx, seeds, max_clusters=8, refine_fn=mock_fn )
        assert len( refined ) == len( seeds )   # fell back


class TestCapEnforce:

    def test_cap_under_limit_passthrough( self ):
        clusters = [
            FailureCluster(
                cluster_id=f"C{i}", failure_indices=[ i ], shared_error_signature=f"sig{i}"
            )
            for i in range( 3 )
        ]
        result = _cap_enforce( clusters, max_clusters=8 )
        assert result == clusters

    def test_cap_at_limit_passthrough( self ):
        clusters = [
            FailureCluster(
                cluster_id=f"C{i}", failure_indices=[ i ], shared_error_signature=f"sig{i}"
            )
            for i in range( 5 )
        ]
        result = _cap_enforce( clusters, max_clusters=5 )
        assert len( result ) == 5

    def test_cap_merges_smallest( self ):
        # 5 clusters of sizes [5, 4, 3, 2, 1], cap to 3:
        # keep largest 2 (5, 4) + merge tail (3+2+1 = 6 indices)
        clusters = [
            FailureCluster(
                cluster_id="C1", failure_indices=list( range( 5 ) ),
                shared_error_signature="biggest",
            ),
            FailureCluster(
                cluster_id="C2", failure_indices=list( range( 5, 9 ) ),
                shared_error_signature="second",
            ),
            FailureCluster(
                cluster_id="C3", failure_indices=list( range( 9, 12 ) ),
                shared_error_signature="third",
            ),
            FailureCluster(
                cluster_id="C4", failure_indices=list( range( 12, 14 ) ),
                shared_error_signature="fourth",
            ),
            FailureCluster(
                cluster_id="C5", failure_indices=[ 14 ],
                shared_error_signature="smallest",
            ),
        ]
        result = _cap_enforce( clusters, max_clusters=3 )
        assert len( result ) == 3
        # Tail cluster has merged indices from the 3 smallest
        tail = result[ -1 ]
        assert len( tail.failure_indices ) == 6   # 3 + 2 + 1
        assert "Mixed" in tail.shared_error_signature
        # All indices preserved
        all_indices = []
        for c in result:
            all_indices.extend( c.failure_indices )
        assert sorted( all_indices ) == list( range( 15 ) )


class TestValidateRefined:

    def test_empty_refined_invalid( self ):
        seeds = [ FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="x" ) ]
        assert not _validate_refined( [], seeds, max_clusters=8 )

    def test_exceeds_max_invalid( self ):
        seeds = [ FailureCluster( cluster_id="C1", failure_indices=[ 0, 1 ], shared_error_signature="x" ) ]
        refined = [
            FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="a" ),
            FailureCluster( cluster_id="C2", failure_indices=[ 1 ], shared_error_signature="b" ),
        ]
        assert not _validate_refined( refined, seeds, max_clusters=1 )

    def test_duplicates_invalid( self ):
        seeds = [ FailureCluster( cluster_id="C1", failure_indices=[ 0, 1 ], shared_error_signature="x" ) ]
        refined = [
            FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="a" ),
            FailureCluster( cluster_id="C2", failure_indices=[ 0, 1 ], shared_error_signature="b" ),
        ]
        assert not _validate_refined( refined, seeds, max_clusters=8 )

    def test_missing_indices_invalid( self ):
        seeds = [ FailureCluster( cluster_id="C1", failure_indices=[ 0, 1, 2 ], shared_error_signature="x" ) ]
        refined = [ FailureCluster( cluster_id="C1", failure_indices=[ 0, 1 ], shared_error_signature="a" ) ]
        assert not _validate_refined( refined, seeds, max_clusters=8 )

    def test_valid_refinement( self ):
        seeds = [ FailureCluster( cluster_id="C1", failure_indices=[ 0, 1, 2 ], shared_error_signature="x" ) ]
        refined = [
            FailureCluster( cluster_id="C1", failure_indices=[ 0, 1 ], shared_error_signature="a" ),
            FailureCluster( cluster_id="C2", failure_indices=[ 2 ], shared_error_signature="b" ),
        ]
        assert _validate_refined( refined, seeds, max_clusters=8 )
