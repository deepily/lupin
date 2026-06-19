"""
Unit tests for cosa.agents.deep_research.narrowing_harness.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). Covers NarrowingResult, NarrowingHarness (theme clustering + the full
progressive-narrowing pipeline with every theme/topic/cancel branch), run_from_plan_file,
parse_args (argparse), run_cli (every dispatch arm), and _has_cli_args.

Boundary-mocked: the api_client is a MagicMock with an AsyncMock call_with_json_output
(deterministic theme responses), voice_io.notify / select_themes / select_topics are
AsyncMocks. run_cli's non-mock path patches ResearchAPIClient so NO real SDK client /
API key is ever constructed. ZERO network/voice/spend. Plan/output files use tempfiles.

Must run via run-sdk-cov.sh (narrowing_harness imports the SDK chain through api_client
in run_cli; api_client is patched there but the import still touches the chain).
"""

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import cosa.agents.deep_research.narrowing_harness as nh
from cosa.agents.deep_research.narrowing_harness import (
    NarrowingResult, NarrowingHarness, parse_args, run_cli, _has_cli_args,
)
import cosa.agents.deep_research.voice_io as voice_io_mod


SUBQ5 = [ { "topic": f"t{i}", "objective": "o" } for i in range( 5 ) ]


def make_harness( theme_response=None, cluster_error=None, **kw ):
    api = MagicMock()
    if cluster_error is not None:
        api.call_with_json_output = AsyncMock( side_effect=cluster_error )
    else:
        api.call_with_json_output = AsyncMock( return_value=theme_response )
    return NarrowingHarness( api_client=api, **kw )


def themes( *specs ):
    """specs: list of (name, indices) → theme response dict."""
    return { "themes": [
        { "name": n, "description": "d", "subquery_indices": idx } for n, idx in specs
    ] }


# ===========================================================================
# NarrowingResult
# ===========================================================================
class TestNarrowingResult( unittest.TestCase ):

    def test_defaults_and_to_dict( self ):
        r = NarrowingResult(
            original_subqueries=[ { "topic": "x" } ],
            themes=[ { "name": "T" } ],
        )
        r.candidate_subqueries = [ ( 0, { "topic": "x" } ) ]
        self.assertEqual( r.api_calls_made, 0 )
        self.assertFalse( r.cancelled )
        d = r.to_dict()
        self.assertEqual( d[ "candidate_subqueries" ], [ { "index": 0, "subquery": { "topic": "x" } } ] )
        self.assertIn( "final_subqueries", d )


# ===========================================================================
# __init__ + run_theme_clustering
# ===========================================================================
class TestThemeClustering( unittest.IsolatedAsyncioTestCase ):

    def test_init_debug_print( self ):
        make_harness( debug=True )   # covers 160-161 true arm
        make_harness( debug=False )  # false arm

    async def test_run_theme_clustering_debug( self ):
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ) ), debug=True )
        resp = await h.run_theme_clustering( SUBQ5 )
        self.assertIn( "themes", resp )
        h.api_client.call_with_json_output.assert_awaited_once()

    async def test_run_theme_clustering_no_debug( self ):
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ) ), debug=False )
        resp = await h.run_theme_clustering( SUBQ5 )
        self.assertIn( "themes", resp )


# ===========================================================================
# run_full_narrowing — the pipeline
# ===========================================================================
class TestFullNarrowing( unittest.IsolatedAsyncioTestCase ):

    async def test_auto_approve_multi_theme_keep_all( self ):
        # >1 theme, auto_approve → select all; >2 candidates auto-kept. debug=False.
        h = make_harness( theme_response=themes( ( "A", [ 0, 1 ] ), ( "B", [ 2 ] ), ( "C", [ 3, 4 ] ) ),
                          auto_approve=True, debug=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertFalse( result.cancelled )
        self.assertEqual( sorted( result.final_indices ), [ 0, 1, 2, 3, 4 ] )
        self.assertEqual( result.api_calls_made, 1 )

    async def test_auto_approve_debug_prints( self ):
        # debug=True covers the 271 + 315 `if self.debug` true arms.
        h = make_harness( theme_response=themes( ( "A", [ 0, 1 ] ), ( "B", [ 2, 3, 4 ] ) ),
                          auto_approve=True, debug=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertFalse( result.cancelled )

    async def test_single_theme_auto_select_verbose( self ):
        # len==1 → auto-select [0] with verbose notify (260-266). >2 candidates auto-kept.
        h = make_harness( theme_response=themes( ( "Solo", [ 0, 1, 2 ] ) ),
                          auto_approve=True, verbose=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( result.selected_theme_indices, [ 0 ] )
        self.assertEqual( sorted( result.final_indices ), [ 0, 1, 2 ] )

    async def test_interactive_theme_select_then_le2_candidates( self ):
        # auto_approve=False → interactive select_themes; 2 candidates → else branch 349-351.
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ) ),
                          auto_approve=False, verbose=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "select_themes", new=AsyncMock( return_value=[ 0, 1 ] ) ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( sorted( result.final_indices ), [ 0, 1 ] )
        self.assertEqual( result.selected_topic_indices, [ 0, 1 ] )

    async def test_theme_select_runtime_error_cancels( self ):
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ) ), auto_approve=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "select_themes", new=AsyncMock( side_effect=RuntimeError( "x" ) ) ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertTrue( result.cancelled )
        self.assertIn( "Theme selection failed", result.cancellation_reason )

    async def test_no_themes_selected_cancels( self ):
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ) ), auto_approve=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "select_themes", new=AsyncMock( return_value=[ ] ) ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertTrue( result.cancelled )
        self.assertEqual( result.cancellation_reason, "No themes selected by user" )

    async def test_interactive_topic_select_success( self ):
        # single theme covering all 5 → auto-select theme; interactive topic refinement.
        h = make_harness( theme_response=themes( ( "Solo", [ 0, 1, 2, 3, 4 ] ) ),
                          auto_approve=False, verbose=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "select_topics", new=AsyncMock( return_value=[ 0, 2, 4 ] ) ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( result.final_indices, [ 0, 2, 4 ] )

    async def test_topic_select_runtime_error_cancels( self ):
        h = make_harness( theme_response=themes( ( "Solo", [ 0, 1, 2, 3, 4 ] ) ), auto_approve=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "select_topics", new=AsyncMock( side_effect=RuntimeError( "y" ) ) ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertTrue( result.cancelled )
        self.assertIn( "Topic selection failed", result.cancellation_reason )

    async def test_no_topics_selected_cancels( self ):
        h = make_harness( theme_response=themes( ( "Solo", [ 0, 1, 2, 3, 4 ] ) ), auto_approve=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
             patch.object( voice_io_mod, "select_topics", new=AsyncMock( return_value=[ ] ) ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertTrue( result.cancelled )
        self.assertEqual( result.cancellation_reason, "No topics selected by user" )

    async def test_empty_themes_fallback_debug( self ):
        h = make_harness( theme_response={ "themes": [ ] }, auto_approve=True, debug=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( result.themes[ 0 ][ "name" ], "All Topics" )

    async def test_empty_themes_fallback_no_debug( self ):
        h = make_harness( theme_response={ "themes": [ ] }, auto_approve=True, debug=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( result.themes[ 0 ][ "name" ], "All Topics" )

    async def test_too_many_themes_truncated_debug( self ):
        # 7 themes → truncate to 6; indices stay within SUBQ5's 0-4 range (i % 5).
        spec = [ ( f"T{i}", [ i % 5 ] ) for i in range( 7 ) ]
        h = make_harness( theme_response=themes( *spec ), auto_approve=True, debug=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( len( result.themes ), 6 )

    async def test_too_many_themes_truncated_no_debug( self ):
        spec = [ ( f"T{i}", [ i % 5 ] ) for i in range( 7 ) ]
        h = make_harness( theme_response=themes( *spec ), auto_approve=True, debug=False )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            result = await h.run_full_narrowing( SUBQ5 )
        self.assertEqual( len( result.themes ), 6 )

    async def test_exception_path_sets_cancelled_and_reraises( self ):
        h = make_harness( cluster_error=ValueError( "api boom" ), auto_approve=True )
        with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            with self.assertRaises( ValueError ):
                await h.run_full_narrowing( SUBQ5 )


# ===========================================================================
# run_from_plan_file
# ===========================================================================
class TestRunFromPlanFile( unittest.IsolatedAsyncioTestCase ):

    async def test_missing_file_raises( self ):
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ) ) )
        with self.assertRaises( FileNotFoundError ):
            await h.run_from_plan_file( "/nonexistent/plan.json" )

    async def test_empty_subqueries_raises( self ):
        h = make_harness( theme_response=themes( ( "A", [ 0 ] ) ) )
        with tempfile.NamedTemporaryFile( "w", suffix=".json", delete=False ) as f:
            json.dump( { "subqueries": [ ] }, f )
            path = f.name
        try:
            with self.assertRaises( ValueError ):
                await h.run_from_plan_file( path )
        finally:
            Path( path ).unlink()

    async def test_loads_and_runs_debug( self ):
        h = make_harness( theme_response=themes( ( "Solo", [ 0 ] ) ), auto_approve=True, debug=True )
        with tempfile.NamedTemporaryFile( "w", suffix=".json", delete=False ) as f:
            json.dump( { "subqueries": [ { "topic": "only" } ] }, f )
            path = f.name
        try:
            with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
                result = await h.run_from_plan_file( path )
            self.assertFalse( result.cancelled )
        finally:
            Path( path ).unlink()

    async def test_loads_and_runs_no_debug( self ):
        # debug=False covers the 395->398 `if self.debug` false arm.
        h = make_harness( theme_response=themes( ( "Solo", [ 0 ] ) ), auto_approve=True, debug=False )
        with tempfile.NamedTemporaryFile( "w", suffix=".json", delete=False ) as f:
            json.dump( { "subqueries": [ { "topic": "only" } ] }, f )
            path = f.name
        try:
            with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
                result = await h.run_from_plan_file( path )
            self.assertFalse( result.cancelled )
        finally:
            Path( path ).unlink()


# ===========================================================================
# parse_args + _has_cli_args
# ===========================================================================
class TestArgParsing( unittest.TestCase ):

    def test_parse_args_defaults( self ):
        with patch.object( sys, "argv", [ "narrowing_harness" ] ):
            args = parse_args()
        self.assertEqual( args.phase, "full" )
        self.assertEqual( args.sample, 5 )
        self.assertFalse( args.mock )

    def test_has_cli_args_true( self ):
        args = argparse.Namespace(
            input=None, output=None, mock=True, cli_mode=False, auto_approve=False,
            verbose=False, debug=False, phase="full", sample=5,
        )
        self.assertTrue( _has_cli_args( args ) )

    def test_has_cli_args_false( self ):
        args = argparse.Namespace(
            input=None, output=None, mock=False, cli_mode=False, auto_approve=False,
            verbose=False, debug=False, phase="full", sample=5,
        )
        self.assertFalse( _has_cli_args( args ) )


# ===========================================================================
# run_cli
# ===========================================================================
def cli_args( **over ):
    base = dict(
        input=None, output=None, phase="full", mock=False, cli_mode=False,
        auto_approve=False, debug=False, verbose=False, sample=5,
    )
    base.update( over )
    return argparse.Namespace( **base )


class TestRunCli( unittest.IsolatedAsyncioTestCase ):

    async def test_mock_themes_phase_cli_mode( self ):
        # cli_mode true (500-502), mock client (505-507), no input sample5 (522-526),
        # themes phase (535-538).
        with patch.object( voice_io_mod, "set_cli_mode" ), \
             patch.object( voice_io_mod, "notify", new=AsyncMock() ):
            await run_cli( cli_args( mock=True, cli_mode=True, phase="themes", debug=True ) )

    async def test_mock_full_phase_sample8_with_output( self ):
        # no input sample8 (525 true), full phase, output write (556-560), final print.
        with tempfile.NamedTemporaryFile( "w", suffix=".json", delete=False ) as f:
            out_path = f.name
        try:
            with patch.object( voice_io_mod, "notify", new=AsyncMock() ):
                await run_cli( cli_args( mock=True, phase="full", sample=8, output=out_path, verbose=True ) )
            written = json.loads( Path( out_path ).read_text() )
            self.assertIn( "final_subqueries", written )
        finally:
            Path( out_path ).unlink()

    async def test_nonmock_with_input_file_single_theme( self ):
        # non-mock path (508-510) with patched ResearchAPIClient → 1 theme, 1 candidate
        # (≤2 → else branch, no voice interaction). with-input (527-532), no output.
        mock_api = MagicMock()
        mock_api.call_with_json_output = AsyncMock(
            return_value=themes( ( "Solo", [ 0 ] ) )
        )
        with tempfile.NamedTemporaryFile( "w", suffix=".json", delete=False ) as f:
            json.dump( { "subqueries": [ { "topic": "only" } ] }, f )
            in_path = f.name
        try:
            with patch( "cosa.agents.deep_research.api_client.ResearchAPIClient", return_value=mock_api ), \
                 patch.object( voice_io_mod, "notify", new=AsyncMock() ):
                await run_cli( cli_args( mock=False, phase="full", input=in_path ) )
        finally:
            Path( in_path ).unlink()

    async def test_nonmock_cancelled_result( self ):
        # cancelled branch (552-553): interactive theme select returns [] → cancelled.
        mock_api = MagicMock()
        mock_api.call_with_json_output = AsyncMock(
            return_value=themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ) )
        )
        with tempfile.NamedTemporaryFile( "w", suffix=".json", delete=False ) as f:
            json.dump( { "subqueries": [ { "topic": "a" }, { "topic": "b" } ] }, f )
            in_path = f.name
        try:
            with patch( "cosa.agents.deep_research.api_client.ResearchAPIClient", return_value=mock_api ), \
                 patch.object( voice_io_mod, "notify", new=AsyncMock() ), \
                 patch.object( voice_io_mod, "select_themes", new=AsyncMock( return_value=[ ] ) ):
                await run_cli( cli_args( mock=False, phase="full", input=in_path ) )
        finally:
            Path( in_path ).unlink()


if __name__ == "__main__":
    unittest.main()
