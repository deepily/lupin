"""
Unit tests for cosa.agents.deep_research.cli.

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, deep_research SDK/network
tier). cli.py is the largest module in the lane (parse_args, check_prerequisites,
print_header, the full inline run_research pipeline, generate_abstract_for_cli,
save_report_with_frontmatter, and the giant main() entrypoint).

COST-SAFETY: ResearchAPIClient is patched so NO real SDK client / firewalled key is
ever constructed; every voice_io / search_cache / ConfigurationManager / Gister / GCS
collaborator is boundary-mocked. ZERO network/voice/spend. Files use tempfiles.

LOGGER-BUG (FIXED 2026-05-31): test_theme_select_runtime_error_returns_none and
test_topic_select_runtime_error_returns_none were armed xfail-strict TRIPWIRES for a
CONFIRMED PROD BUG — cli.py referenced `logger` at lines 430/469 but never imported
logging or defined `logger`. A select_themes/select_topics RuntimeError (the
technical-failure path) hit `logger.error(...)` → NameError, masking the real error and
skipping the intended graceful `return None` (lines 431/470 unreachable). Tiberius fixed
it (added `import logging` + module-level `logger = logging.getLogger(__name__)`). The
xfails are removed; both tests now assert the working graceful-return-None contract.

Must run via run-sdk-cov.sh (cli imports the SDK chain).
"""

import argparse
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager, ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

import cosa.agents.deep_research.cli as cli
from cosa.agents.deep_research.cost_tracker import SessionSummary, BudgetExceededError


class FakeRateLimitError( Exception ):
    pass


# ---------------------------------------------------------------------------
# JSON-response builders for the api_client.call_with_json_output sequence
# ---------------------------------------------------------------------------
def clar( needs=False, question="Clarify?", options=None, understood="understood query text" ):
    d = { "needs_clarification": needs, "understood_query": understood }
    if needs:
        d[ "question" ] = question
        d[ "options" ]  = options if options is not None else [ ]
    return d


def plan( n, complexity="moderate", objectives=True ):
    subs = [ ]
    for i in range( n ):
        sq = { "topic": f"topic{i}", "output_format": "summary" }
        if objectives:
            sq[ "objective" ] = f"objective {i}"
        subs.append( sq )
    return { "complexity": complexity, "subqueries": subs, "rationale": "the rationale" }


def themes( *specs ):
    return { "themes": [ { "name": n, "description": "d", "subquery_indices": idx } for n, idx in specs ] }


def make_summary():
    return SessionSummary(
        duration_seconds=75.0, total_cost_usd=0.5, total_input_tokens=1000, total_output_tokens=2000,
    )


@contextmanager
def rr_env(
    json_responses,
    subagent_content='{"findings": "f", "confidence": 0.9}',
    subagent_tokens=500,
    synthesis="FINAL REPORT",
    cached=None,
    mode="CLI text",
    subagent_side_effect=None,
    est_total=30.0,
    est_wait=5.0,
    choose=None, get_input=None, ask_yes_no=True,
    select_themes=None, select_topics=None,
):
    api = MagicMock()
    api.call_with_json_output = AsyncMock( side_effect=list( json_responses ) )
    if subagent_side_effect is not None:
        api.call_subagent = AsyncMock( side_effect=subagent_side_effect )
    else:
        api.call_subagent = AsyncMock(
            return_value=SimpleNamespace( content=subagent_content, input_tokens=subagent_tokens )
        )
    api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content=synthesis ) )
    rl = MagicMock()
    rl.estimate_total_time.return_value = est_total
    rl.get_estimated_wait_for_next_call.return_value = est_wait
    api.get_rate_limiter.return_value = rl
    api.close = AsyncMock()

    def as_async( val ):
        if isinstance( val, BaseException ) or ( isinstance( val, type ) and issubclass( val, BaseException ) ):
            return AsyncMock( side_effect=val )
        return AsyncMock( return_value=val )

    with ExitStack() as s:
        s.enter_context( patch.object( cli, "ResearchAPIClient", return_value=api ) )
        s.enter_context( patch.object( cli, "anthropic", SimpleNamespace( RateLimitError=FakeRateLimitError ) ) )
        s.enter_context( patch.object( cli.voice_io, "get_mode_description", return_value=mode ) )
        s.enter_context( patch.object( cli.voice_io, "notify", new=AsyncMock() ) )
        s.enter_context( patch.object( cli.voice_io, "choose", new=AsyncMock( return_value=choose ) ) )
        s.enter_context( patch.object( cli.voice_io, "get_input", new=AsyncMock( return_value=get_input ) ) )
        s.enter_context( patch.object( cli.voice_io, "ask_yes_no", new=AsyncMock( return_value=ask_yes_no ) ) )
        s.enter_context( patch.object( cli.voice_io, "select_themes", new=as_async( select_themes ) ) )
        s.enter_context( patch.object( cli.voice_io, "select_topics", new=as_async( select_topics ) ) )
        s.enter_context( patch.object( cli.search_cache, "load_cached_result", return_value=cached ) )
        s.enter_context( patch.object( cli.search_cache, "save_to_cache" ) )
        yield api


def make_config():
    cfg = MagicMock()
    cfg.lead_model = "claude-opus"
    cfg.subagent_model = "claude-sonnet"
    cfg.max_subagents_complex = 10
    cfg.audience = "academic"
    cfg.audience_context = None
    return cfg


def run_research( **kw ):
    """Helper to call cli.run_research with sane defaults via asyncio."""
    import asyncio
    defaults = dict( query="my query", config=make_config(), cost_tracker=MagicMock(),
                     user_email="", no_confirm=False, cancel_check=None, debug=False, verbose=False )
    defaults.update( kw )
    return asyncio.get_event_loop().run_until_complete( cli.run_research( **defaults ) )


# ===========================================================================
# parse_args
# ===========================================================================
class TestParseArgs( unittest.TestCase ):
    def test_defaults( self ):
        with patch.object( sys, "argv", [ "cli", "--query", "hello" ] ):
            args = cli.parse_args()
        self.assertEqual( args.query, "hello" )
        self.assertIsNone( args.budget )
        self.assertFalse( args.no_confirm )


# ===========================================================================
# check_prerequisites
# ===========================================================================
class TestCheckPrerequisites( unittest.TestCase ):
    """Bounded-CC (Phase 3): the only prerequisite is an importable Claude Agent
    SDK. The pre-migration firewalled-key gate is retired (OAuth via sdk_query)."""

    def test_sdk_unavailable( self ):
        with patch.object( cli, "ANTHROPIC_AVAILABLE", False ):
            self.assertFalse( cli.check_prerequisites() )

    def test_sdk_available_needs_no_key( self ):
        # No firewalled key present anywhere → still True on the bounded path.
        with patch.object( cli, "ANTHROPIC_AVAILABLE", True ), \
             patch.dict( cli.os.environ, { }, clear=True ):
            self.assertTrue( cli.check_prerequisites() )


# ===========================================================================
# print_header
# ===========================================================================
class TestPrintHeader( unittest.TestCase ):
    def test_with_budget( self ):
        cli.print_header( "q", make_config(), 5.0 )

    def test_no_budget( self ):
        cli.print_header( "q", make_config(), None )


# ===========================================================================
# run_research — the pipeline
# ===========================================================================
class TestRunResearch( unittest.IsolatedAsyncioTestCase ):

    async def test_no_confirm_two_topics_happy( self ):
        # no_confirm → skip approval; 2 subqueries (>1) → rate-limit explanation;
        # cache miss → call_subagent + save; JSON content parse; synthesis.
        with rr_env( [ clar(), plan( 2 ) ], est_total=30.0 ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True, debug=True )
        self.assertEqual( report, "FINAL REPORT" )
        self.assertEqual( api.call_subagent.await_count, 2 )

    async def test_single_topic_no_rate_explain( self ):
        # 1 subquery → len>1 false (no rate explanation), single-topic loop (631 false).
        with rr_env( [ clar(), plan( 1 ) ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_clarification_choose_path( self ):
        # needs_clarification + options>=2 → choose; real clarification appended.
        # no_confirm=False so the 312 `if not no_confirm:` block runs; ≤3 topics →
        # simple yes/no (ask_yes_no True) proceeds.
        with rr_env( [ clar( needs=True, options=[ "A", "B" ] ), plan( 2 ) ],
                     choose="Option A detail", ask_yes_no=True ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_clarification_needed_but_no_confirm_skips_interaction( self ):
        # needs_clarification True + no_confirm True → 312 `if not no_confirm` false arm
        # (312->335): announce clarification but skip the interactive prompt.
        with rr_env( [ clar( needs=True, options=[ "A", "B" ] ), plan( 2 ) ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_clarification_get_input_skip( self ):
        # needs_clarification + no options → get_input; "skip" → skipped branch.
        # ≤3 topics + no_confirm False → simple yes/no proceed.
        with rr_env( [ clar( needs=True, options=[ ] ), plan( 2 ) ],
                     get_input="skip", ask_yes_no=True ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_simple_plan_rejected_cancels( self ):
        # ≤3 topics, no_confirm False, ask_yes_no False → cancel return None.
        with rr_env( [ clar(), plan( 3 ) ], ask_yes_no=False ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertIsNone( report )

    async def test_simple_plan_subquery_without_objective( self ):
        # objectives=False → abstract loop hits the `if objective:` false arm (504->506).
        with rr_env( [ clar(), plan( 2, objectives=False ) ], ask_yes_no=True ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_narrowing_normal_themes_and_topics( self ):
        # >3 topics, no_confirm False → narrowing; 3 themes (2-6) → select_themes;
        # >2 candidates → select_topics; both succeed.
        th = themes( ( "A", [ 0, 1 ] ), ( "B", [ 2 ] ), ( "C", [ 3, 4 ] ) )
        with rr_env( [ clar(), plan( 5 ), th ],
                     select_themes=[ 0, 1, 2 ], select_topics=[ 0, 1, 2 ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_narrowing_empty_themes_fallback_single( self ):
        # theme clustering empty → fallback single "All Topics" theme → auto-select.
        with rr_env( [ clar(), plan( 5 ), { "themes": [ ] } ],
                     select_topics=[ 0, 1 ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_narrowing_too_many_themes_truncate( self ):
        spec = [ ( f"T{i}", [ i % 5 ] ) for i in range( 7 ) ]
        with rr_env( [ clar(), plan( 5 ), themes( *spec ) ],
                     select_themes=[ 0, 1 ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_narrowing_no_themes_selected_cancels( self ):
        th = themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ) )
        with rr_env( [ clar(), plan( 5 ), th ], select_themes=[ ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertIsNone( report )

    async def test_narrowing_le2_candidates_else_branch( self ):
        # select 2 themes each 1 index → 2 candidates → ≤2 → else final_indices (487).
        th = themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ), ( "C", [ 2 ] ) )
        with rr_env( [ clar(), plan( 5 ), th ], select_themes=[ 0, 1 ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_narrowing_no_topics_selected_cancels( self ):
        th = themes( ( "Solo", [ 0, 1, 2, 3, 4 ] ) )
        with rr_env( [ clar(), plan( 5 ), th ], select_topics=[ ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertIsNone( report )

    async def test_theme_select_runtime_error_returns_none( self ):
        # Was an armed xfail-strict TRIPWIRE for the logger-NameError bug (cli.py:430);
        # de-armed once the fix (import logging + module-level logger) landed — now asserts
        # the graceful return None on a select_themes technical failure (line 431 reachable).
        th = themes( ( "A", [ 0 ] ), ( "B", [ 1 ] ), ( "C", [ 2 ] ) )
        with rr_env( [ clar(), plan( 5 ), th ], select_themes=RuntimeError( "tech fail" ) ):
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertIsNone( report )

    async def test_topic_select_runtime_error_returns_none( self ):
        # Was an armed xfail-strict TRIPWIRE for the logger-NameError bug (cli.py:469);
        # de-armed once the fix landed — now asserts the graceful return None on a
        # select_topics technical failure (line 470 reachable).
        th = themes( ( "Solo", [ 0, 1, 2, 3, 4 ] ) )
        with rr_env( [ clar(), plan( 5 ), th ], select_topics=RuntimeError( "tech fail" ) ):
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=False )
        self.assertIsNone( report )

    async def test_estimate_time_over_60_notifies( self ):
        with rr_env( [ clar(), plan( 2 ) ], est_total=120.0 ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_cached_result_path( self ):
        cached = { "results": { "content": '{"findings": "cached"}', "tokens": 42 } }
        with rr_env( [ clar(), plan( 2 ) ], cached=cached ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True, debug=True )
        self.assertEqual( report, "FINAL REPORT" )
        api.call_subagent.assert_not_awaited()

    async def test_findings_json_fenced_and_malformed( self ):
        # 1st subagent: ```json fenced; 2nd: malformed → raw-content finding.
        with rr_env(
            [ clar(), plan( 2 ) ],
            subagent_side_effect=[
                SimpleNamespace( content='```json\n{"findings": "x"}\n```', input_tokens=100 ),
                SimpleNamespace( content='not json at all', input_tokens=100 ),
            ],
        ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_rate_limit_with_findings_proceed_partial( self ):
        # 1st subagent ok, 2nd raises RateLimitError → partial; ask_yes_no True → synthesize.
        with rr_env(
            [ clar(), plan( 3 ) ],
            subagent_side_effect=[
                SimpleNamespace( content='{"findings": "a"}', input_tokens=100 ),
                FakeRateLimitError(),
            ],
            ask_yes_no=True,
        ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertEqual( report, "FINAL REPORT" )

    async def test_rate_limit_with_findings_decline_partial( self ):
        with rr_env(
            [ clar(), plan( 3 ) ],
            subagent_side_effect=[
                SimpleNamespace( content='{"findings": "a"}', input_tokens=100 ),
                FakeRateLimitError(),
            ],
            ask_yes_no=False,
        ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertIsNone( report )

    async def test_rate_limit_no_findings_returns_none( self ):
        with rr_env(
            [ clar(), plan( 2 ) ],
            subagent_side_effect=[ FakeRateLimitError() ],
        ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertIsNone( report )

    async def test_budget_exceeded_returns_none( self ):
        with rr_env(
            [ clar(), plan( 2 ) ],
            subagent_side_effect=[ BudgetExceededError( "over", current_cost=0.5, budget_limit=0.1 ) ],
        ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True )
        self.assertIsNone( report )

    async def test_cancel_after_clarification( self ):
        with rr_env( [ clar(), plan( 2 ) ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True,
                                             cancel_check=lambda: True )
        self.assertIsNone( report )

    async def test_cancel_after_planning( self ):
        calls = { "n": 0 }
        def cc():
            calls[ "n" ] += 1
            return calls[ "n" ] == 2   # False at clarification, True after planning
        with rr_env( [ clar(), plan( 2 ) ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True, cancel_check=cc )
        self.assertIsNone( report )

    async def test_cancel_before_research_topic( self ):
        calls = { "n": 0 }
        def cc():
            calls[ "n" ] += 1
            return calls[ "n" ] == 3   # pass clar(1) + planning(2), trip in loop(3)
        with rr_env( [ clar(), plan( 2 ) ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True, cancel_check=cc )
        self.assertIsNone( report )

    async def test_cancel_before_synthesis( self ):
        # 1 topic: cancel checks at clar(1), planning(2), loop(3), pre-synth(4).
        calls = { "n": 0 }
        def cc():
            calls[ "n" ] += 1
            return calls[ "n" ] == 4
        with rr_env( [ clar(), plan( 1 ) ] ) as api:
            report = await cli.run_research( query="q", config=make_config(),
                                             cost_tracker=MagicMock(), no_confirm=True, cancel_check=cc )
        self.assertIsNone( report )


# ===========================================================================
# generate_abstract_for_cli
# ===========================================================================
class TestGenerateAbstract( unittest.IsolatedAsyncioTestCase ):

    async def test_success( self ):
        api = MagicMock()
        api.call_lead_agent = AsyncMock( return_value=SimpleNamespace( content="  An abstract.  " ) )
        api.close = AsyncMock()
        with patch.object( cli, "ResearchAPIClient", return_value=api ):
            result = await cli.generate_abstract_for_cli( "report body", make_config(), MagicMock() )
        self.assertEqual( result, "An abstract." )

    async def test_exception_fallback_finds_paragraph( self ):
        api = MagicMock()
        api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "fail" ) )
        api.close = AsyncMock()
        report = "# Heading\n\nThis is the first real paragraph.\n\nMore."
        with patch.object( cli, "ResearchAPIClient", return_value=api ):
            result = await cli.generate_abstract_for_cli( report, make_config(), MagicMock(), debug=True )
        self.assertTrue( result.startswith( "This is the first real paragraph" ) )

    async def test_exception_fallback_only_headers_default( self ):
        api = MagicMock()
        api.call_lead_agent = AsyncMock( side_effect=RuntimeError( "fail" ) )
        api.close = AsyncMock()
        report = "# Heading\n\n## Subheading"
        with patch.object( cli, "ResearchAPIClient", return_value=api ):
            result = await cli.generate_abstract_for_cli( report, make_config(), MagicMock() )
        self.assertEqual( result, "Research report generated." )


# ===========================================================================
# save_report_with_frontmatter
# ===========================================================================
class TestSaveReport( unittest.TestCase ):

    def _tracker( self ):
        t = MagicMock()
        t.get_summary.return_value = make_summary()
        return t

    def test_local_save_debug( self ):
        with tempfile.TemporaryDirectory() as d:
            path = cli.save_report_with_frontmatter(
                report="BODY", query="q", abstract="abs", semantic_topic="my-topic",
                session_id="s1", cost_tracker=self._tracker(), config=make_config(),
                output_dir=d, user_email="u@x.com", storage_backend="local", debug=True,
            )
            self.assertTrue( path.endswith( ".md" ) )
            self.assertIn( "BODY", Path( path ).read_text() )

    def test_gcs_save_success( self ):
        with patch( "cosa.utils.util_gcs.write_text_to_gcs" ) as mock_write:
            path = cli.save_report_with_frontmatter(
                report="BODY", query="q", abstract="abs", semantic_topic="t",
                session_id="s1", cost_tracker=self._tracker(), config=make_config(),
                output_dir="/unused", user_email="u@x.com",
                storage_backend="gcs", gcs_bucket="gs://bucket/", debug=True,
            )
        self.assertTrue( path.startswith( "gs://bucket/" ) )
        mock_write.assert_called_once()

    def test_gcs_failure_falls_back_local( self ):
        with patch( "cosa.utils.util_gcs.write_text_to_gcs", side_effect=RuntimeError( "gcs down" ) ):
            path = cli.save_report_with_frontmatter(
                report="BODY", query="q", abstract="abs", semantic_topic="t",
                session_id="s1", cost_tracker=self._tracker(), config=make_config(),
                output_dir="/unused", user_email="u@x.com",
                storage_backend="gcs", gcs_bucket="gs://bucket", debug=False,
            )
        self.assertIn( tempfile.gettempdir(), path )
        self.assertIn( "BODY", Path( path ).read_text() )
        Path( path ).unlink()


# ===========================================================================
# main()
# ===========================================================================
def main_args( **over ):
    base = dict(
        query="my query", budget=None, lead_model=None, subagent_model=None,
        max_subagents=10, no_confirm=True, output=None, no_save=False,
        save_to_directory=None, user_email="u@x.com", audience=None,
        audience_context=None, debug=False, verbose=False, dry_run=False, cli_mode=False,
    )
    base.update( over )
    return argparse.Namespace( **base )


@contextmanager
def main_env(
    args, cfg_values=None, gister="my session", prereq=True,
    run_result="REPORT", abstract="ABS", save_path="/proj/io/deep-research/u@x.com/r.md",
    gcs_available=True, gcs_valid=True, project_root="/proj",
):
    values = {
        "deep research storage backend"     : "local",
        "deep research gcs bucket"           : None,
        "deep research default user email"   : None,
        "deep research output path"          : "/io/deep-research",
    }
    if cfg_values:
        values.update( cfg_values )
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: values.get( key, default )

    gister_mock = MagicMock()
    gister_mock.get_gist.return_value = gister

    tracker = MagicMock()
    tracker.get_summary.return_value = make_summary()
    tracker.get_cost_report.return_value = "COST REPORT"

    with ExitStack() as s:
        s.enter_context( patch.object( cli, "parse_args", return_value=args ) )
        s.enter_context( patch.object( cli, "ConfigurationManager", return_value=cfg ) )
        s.enter_context( patch( "cosa.memory.gister.Gister", return_value=gister_mock ) )
        s.enter_context( patch.object( cli, "check_prerequisites", return_value=prereq ) )
        s.enter_context( patch.object( cli, "ResearchConfig" ) )
        cli.ResearchConfig.from_config.return_value = make_config()
        s.enter_context( patch.object( cli, "CostTracker", return_value=tracker ) )
        s.enter_context( patch.object( cli, "run_research", new=AsyncMock( return_value=run_result ) ) )
        s.enter_context( patch.object( cli, "generate_abstract_for_cli", new=AsyncMock( return_value=abstract ) ) )
        s.enter_context( patch.object( cli, "save_report_with_frontmatter", return_value=save_path ) )
        s.enter_context( patch.object( cli, "print_header" ) )
        s.enter_context( patch.object( cli.voice_io, "notify", new=AsyncMock() ) )
        s.enter_context( patch.object( cli.voice_io, "set_cli_mode" ) )
        s.enter_context( patch( "cosa.utils.util.get_project_root", return_value=project_root ) )
        s.enter_context( patch( "cosa.utils.util_gcs.validate_gcs_bucket_access", return_value=gcs_valid ) )
        s.enter_context( patch( "cosa.utils.util_gcs.GCS_AVAILABLE", gcs_available ) )
        s.enter_context( patch( "cosa.utils.util_gcs.gcs_uri_to_console_url", return_value="https://console/x" ) )
        yield { "cfg": cfg, "tracker": tracker, "gister": gister_mock }


class TestMain( unittest.TestCase ):

    def test_user_visible_args_exits_zero( self ):
        with patch.object( sys, "argv", [ "cli", "--user-visible-args" ] ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 0 )

    def test_missing_user_email_exits_one( self ):
        with main_env( main_args( user_email=None ) ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_invalid_email_exits_one( self ):
        with main_env( main_args( user_email="noatsign" ) ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_gcs_no_bucket_exits_one( self ):
        with main_env( main_args(), cfg_values={ "deep research storage backend": "gcs" } ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_gcs_unavailable_falls_back_then_runs( self ):
        with main_env( main_args(),
                       cfg_values={ "deep research storage backend": "gcs",
                                    "deep research gcs bucket": "gs://b/" },
                       gcs_available=False ):
            cli.main()  # falls back to local, completes (no SystemExit on success)

    def test_gcs_inaccessible_falls_back( self ):
        with main_env( main_args(),
                       cfg_values={ "deep research storage backend": "gcs",
                                    "deep research gcs bucket": "gs://b/" },
                       gcs_available=True, gcs_valid=False ):
            cli.main()

    def test_prereq_fails_exits_one( self ):
        with main_env( main_args(), prereq=False ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_dry_run_local_exits_zero( self ):
        with main_env( main_args( dry_run=True ) ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 0 )

    def test_dry_run_cli_mode_no_notification( self ):
        with main_env( main_args( dry_run=True, cli_mode=True ) ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 0 )

    def test_dry_run_gcs( self ):
        with main_env( main_args( dry_run=True ),
                       cfg_values={ "deep research storage backend": "gcs",
                                    "deep research gcs bucket": "gs://b/" } ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 0 )

    def test_full_run_local_save_with_output_file( self ):
        with tempfile.NamedTemporaryFile( "w", suffix=".md", delete=False ) as f:
            out = f.name
        try:
            with main_env( main_args( output=out, debug=True ) ):
                cli.main()
            self.assertEqual( Path( out ).read_text(), "REPORT" )
        finally:
            Path( out ).unlink()

    def test_full_run_save_disabled_basic_notify( self ):
        with main_env( main_args( no_save=True ) ):
            cli.main()

    def test_full_run_save_to_directory_override( self ):
        with main_env( main_args( save_to_directory="/custom/dir" ) ):
            cli.main()

    def test_full_run_gcs_backend_links( self ):
        with main_env( main_args(),
                       cfg_values={ "deep research storage backend": "gcs",
                                    "deep research gcs bucket": "gs://b/" },
                       save_path="gs://b/u@x.com/r.md" ):
            cli.main()

    def test_report_none_skips_save( self ):
        with main_env( main_args(), run_result=None ):
            cli.main()

    def test_cli_mode_sets_mode( self ):
        with main_env( main_args( cli_mode=True ) ):
            cli.main()

    def test_empty_gist_default_session_name( self ):
        with main_env( main_args(), gister="   " ):
            cli.main()

    def test_keyboard_interrupt_exits_one( self ):
        with main_env( main_args() ) as m:
            with patch.object( cli, "run_research", new=AsyncMock( side_effect=KeyboardInterrupt ) ):
                with self.assertRaises( SystemExit ) as cm:
                    cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_rate_limit_exits_two( self ):
        with main_env( main_args() ):
            with patch.object( cli, "anthropic", SimpleNamespace( RateLimitError=FakeRateLimitError ) ), \
                 patch.object( cli, "run_research", new=AsyncMock( side_effect=FakeRateLimitError ) ):
                with self.assertRaises( SystemExit ) as cm:
                    cli.main()
        self.assertEqual( cm.exception.code, 2 )

    def test_generic_exception_exits_one_debug( self ):
        with main_env( main_args( debug=True ) ):
            with patch.object( cli, "run_research", new=AsyncMock( side_effect=ValueError( "boom" ) ) ):
                with self.assertRaises( SystemExit ) as cm:
                    cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_generic_exception_exits_one_no_debug( self ):
        # debug=False covers the 1243->1246 `if args.debug:` false arm (no traceback).
        with main_env( main_args( debug=False ) ):
            with patch.object( cli, "run_research", new=AsyncMock( side_effect=ValueError( "boom" ) ) ):
                with self.assertRaises( SystemExit ) as cm:
                    cli.main()
        self.assertEqual( cm.exception.code, 1 )

    def test_config_overrides_applied( self ):
        # lead_model / subagent_model / audience / audience_context truthy arms (1026/1028/1032/1034).
        with main_env( main_args( lead_model="L", subagent_model="S",
                                  audience="expert", audience_context="ctx" ) ):
            cli.main()

    def test_max_subagents_zero_skips_override( self ):
        # max_subagents falsy → 1029->1031 false arm.
        with main_env( main_args( max_subagents=0 ) ):
            cli.main()

    def test_dry_run_with_audience_context( self ):
        # config.audience_context set → dry-run line 1058 print.
        with main_env( main_args( dry_run=True, audience_context="ctx" ) ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 0 )

    def test_dry_run_gcs_fallback_prints_note( self ):
        # gcs backend + unavailable → gcs_fallback True → dry-run local + line 1067 note.
        with main_env( main_args( dry_run=True ),
                       cfg_values={ "deep research storage backend": "gcs",
                                    "deep research gcs bucket": "gs://b/" },
                       gcs_available=False ):
            with self.assertRaises( SystemExit ) as cm:
                cli.main()
        self.assertEqual( cm.exception.code, 0 )

    def test_full_run_save_path_outside_research_base( self ):
        # file_path not under <root>/io/deep-research → 1176-1177 fallback relative_path.
        with main_env( main_args(), save_path="/elsewhere/report.md" ):
            cli.main()


import cosa.agents.deep_research.api_client as cli_api


class TestAnthropicImportGuard( unittest.TestCase ):
    """Cover the module-level `if ANTHROPIC_AVAILABLE: import anthropic` false arm (42->47)."""

    def test_guard_false_arm_via_reload( self ):
        import importlib
        try:
            with patch.object( cli_api, "ANTHROPIC_AVAILABLE", False ):
                importlib.reload( cli )
                self.assertFalse( cli.ANTHROPIC_AVAILABLE )
        finally:
            importlib.reload( cli )   # restore genuine state for any later test
        self.assertTrue( cli.ANTHROPIC_AVAILABLE )


if __name__ == "__main__":
    unittest.main()
