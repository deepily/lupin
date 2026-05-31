"""
Unit tests for swe_team/orchestrator.py — SweTeamOrchestrator PHASE methods:
  _analyze_user_messages, run, _execute_dry_run, _execute_live,
  _decompose_task, _delegate_task, _verify_result, _redelegate_with_feedback.

sdk_query is mocked as an async-generator yielding REAL TextBlock / ToolUseBlock /
AssistantMessage objects + MagicMock(spec=ResultMessage/RateLimitEvent). The
"neither-type fall-through" elif-false arcs are covered with a bare MagicMock()
block/message. _execute_live drives its state machine with the sub-async-methods
(_decompose/_delegate/_verify/_redelegate/_gated_confirmation/_check_in) mocked.
NO real LLM/SDK/network/subprocess/fs.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, orchestrator).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.orchestrator as orch_mod
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.state import OrchestratorState, TaskSpec, DelegationResult, VerificationResult
from cosa.agents.swe_team.safety_limits import SafetyLimitError


def _run( coro ):
    return asyncio.run( coro )


def _sdk_stream( *messages ):
    """Return an async-generator function standing in for sdk_query."""
    async def _gen( *args, **kwargs ):
        for m in messages:
            yield m
    return _gen


def _text( s ):
    return orch_mod.TextBlock( text=s )


def _tool( name, file_path="x.py" ):
    return orch_mod.ToolUseBlock( id="t1", name=name, input={ "file_path": file_path } )


def _assistant( *blocks ):
    return orch_mod.AssistantMessage( content=list( blocks ), model="claude" )


def _mk_orch( dry_run=False, trust_mode="disabled", debug=False, **cfg_over ):
    cfg = SweTeamConfig( dry_run=dry_run, trust_mode=trust_mode, **cfg_over )
    return SweTeamOrchestrator( task_description="Build X", config=cfg, job_id="swe-1", debug=debug )


# ============================================================================
# _analyze_user_messages
# ============================================================================

class TestAnalyzeUserMessages( unittest.TestCase ):

    def _msgs( self ):
        return [ { "message": "use module Y", "priority": "normal" },
                 { "message": "be careful", "priority": "urgent" } ]

    def test_sdk_unavailable_fallback( self ):
        o = _mk_orch()
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            out = _run( o._analyze_user_messages( self._msgs(), MagicMock() ) )
        self.assertIn( "use module Y", out )

    def test_sdk_path_collects_text_and_neither_arcs( self ):
        o = _mk_orch()
        o.state[ "task_specs" ] = [ TaskSpec( title="T1", objective="o", output_format="f" ) ]
        o.state[ "current_task_index" ] = 0
        msgs = (
            _assistant( _text( "analysis " ), MagicMock() ),  # AssistantMessage w/ a neither-type block
            orch_mod.TextBlock( text="tail" ),                # bare TextBlock message
            MagicMock( spec=orch_mod.RateLimitEvent ),        # RateLimitEvent branch
            MagicMock(),                                       # neither-of-4-types message → elif-false
        )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ):
            out = _run( o._analyze_user_messages( self._msgs(), MagicMock() ) )
        self.assertIn( "analysis", out )

    def test_sdk_empty_output_falls_back_to_messages( self ):
        o = _mk_orch()
        with patch.object( orch_mod, "sdk_query", _sdk_stream() ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ):
            out = _run( o._analyze_user_messages( self._msgs(), MagicMock() ) )
        self.assertIn( "use module Y", out )   # empty collected → message fallback

    def test_sdk_exception_falls_back( self ):
        o = _mk_orch()
        def _boom( *a, **k ):
            raise RuntimeError( "sdk boom" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ):
            out = _run( o._analyze_user_messages( self._msgs(), MagicMock() ) )
        self.assertIn( "use module Y", out )

    def test_current_task_index_out_of_range_uses_unknown( self ):
        o = _mk_orch()
        o.state[ "task_specs" ] = []           # idx 0 >= len 0 → "unknown"
        o.state[ "current_task_index" ] = 0
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            out = _run( o._analyze_user_messages( self._msgs(), MagicMock() ) )
        self.assertIn( "use module Y", out )


# ============================================================================
# run
# ============================================================================

class TestRun( unittest.TestCase ):

    def test_run_dry_run_path( self ):
        o = _mk_orch( dry_run=True )
        with patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_execute_dry_run", AsyncMock( return_value="DRY OK" ) ):
            out = _run( o.run() )
        self.assertEqual( out, "DRY OK" )
        self.assertEqual( o.current_state, OrchestratorState.COMPLETED )

    def test_run_live_path( self ):
        o = _mk_orch( dry_run=False )
        with patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_execute_live", AsyncMock( return_value="LIVE OK" ) ):
            out = _run( o.run() )
        self.assertEqual( out, "LIVE OK" )

    def test_run_safety_limit_error_returns_none( self ):
        o = _mk_orch( dry_run=True )
        with patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_execute_dry_run", AsyncMock( side_effect=SafetyLimitError( "limit" ) ) ):
            out = _run( o.run() )
        self.assertIsNone( out )
        self.assertEqual( o.current_state, OrchestratorState.FAILED )

    def test_run_generic_exception_returns_none( self ):
        o = _mk_orch( dry_run=True )
        with patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_execute_dry_run", AsyncMock( side_effect=RuntimeError( "boom" ) ) ):
            out = _run( o.run() )
        self.assertIsNone( out )
        self.assertEqual( o.current_state, OrchestratorState.FAILED )


# ============================================================================
# _execute_dry_run
# ============================================================================

class TestExecuteDryRun( unittest.TestCase ):

    def test_dry_run_streams_phases( self ):
        o = _mk_orch( dry_run=True, debug=True )
        with patch.object( orch_mod.MockAgentSDKSession, "DELAY_MULTIPLIER", 0.0 ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ):
            out = _run( o._execute_dry_run( MagicMock() ) )
        self.assertIn( "Dry-run complete", out )

    def test_dry_run_stop_requested_breaks( self ):
        o = _mk_orch( dry_run=True )
        o._stop_requested = True
        with patch.object( orch_mod.MockAgentSDKSession, "DELAY_MULTIPLIER", 0.0 ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ):
            out = _run( o._execute_dry_run( MagicMock() ) )
        self.assertIn( "Dry-run complete", out )


# ============================================================================
# _decompose_task
# ============================================================================

class TestDecomposeTask( unittest.TestCase ):

    def test_decompose_parses_sdk_json( self ):
        o = _mk_orch( debug=True )
        raw = '[{"title":"a","objective":"o","output_format":"f"}]'
        msgs = (
            _assistant( _text( raw ), MagicMock() ),  # neither-type block inside content
            orch_mod.TextBlock( text="" ),            # bare TextBlock branch
            MagicMock( spec=orch_mod.RateLimitEvent ),
            MagicMock(),                               # neither-of-4 message
        )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ):
            specs = _run( o._decompose_task( MagicMock() ) )
        self.assertEqual( specs[ 0 ].title, "a" )

    def test_decompose_exception_falls_back( self ):
        o = _mk_orch()
        def _boom( *a, **k ): raise RuntimeError( "sdk boom" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ):
            specs = _run( o._decompose_task( MagicMock() ) )
        self.assertEqual( specs[ 0 ].objective, "Build X" )   # fallback single task


# ============================================================================
# _delegate_task
# ============================================================================

class TestDelegateTask( unittest.TestCase ):

    def _spec( self ):
        return TaskSpec( title="impl", objective="o", output_format="f" )

    def test_delegate_success_tracks_files_and_neither_arcs( self ):
        o = _mk_orch()
        msgs = (
            # Edit(a.py)=tracked, Read=non-Edit/Write block (1329->skip), Edit("")=empty
            # path (file_path falsy → skip append), Edit(a.py) dup (already in list),
            # bare MagicMock block = neither-type block arc.
            _assistant( _text( "done " ), _tool( "Edit", "a.py" ), _tool( "Read", "b.py" ),
                        _tool( "Edit", "" ), _tool( "Edit", "a.py" ), MagicMock() ),
            orch_mod.TextBlock( text="tail" ),
            MagicMock( spec=orch_mod.ResultMessage ),
            MagicMock( spec=orch_mod.RateLimitEvent ),
            MagicMock(),
        )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "notification_hook", AsyncMock() ):
            result = _run( o._delegate_task( self._spec(), 0, MagicMock() ) )
        self.assertEqual( result.status, "success" )
        self.assertIn( "a.py", result.files_changed )   # Edit tracked; Read not

    def test_delegate_stop_requested_breaks( self ):
        o = _mk_orch()
        o._stop_requested = True
        msgs = ( _assistant( _text( "x" ) ), )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ):
            result = _run( o._delegate_task( self._spec(), 0, MagicMock() ) )
        self.assertEqual( result.status, "success" )

    def test_delegate_safety_limit_error_propagates( self ):
        o = _mk_orch()
        with patch.object( orch_mod, "sdk_query", _sdk_stream( _assistant( _text( "x" ) ) ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o.guard, "check_timeout", side_effect=SafetyLimitError( "timeout" ) ):
            with self.assertRaises( SafetyLimitError ):
                _run( o._delegate_task( self._spec(), 0, MagicMock() ) )

    def test_delegate_generic_exception_returns_failure( self ):
        o = _mk_orch()
        def _boom( *a, **k ): raise RuntimeError( "sdk boom" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ):
            result = _run( o._delegate_task( self._spec(), 0, MagicMock() ) )
        self.assertEqual( result.status, "failure" )


# ============================================================================
# _verify_result
# ============================================================================

class TestVerifyResult( unittest.TestCase ):

    def _spec( self ):
        return TaskSpec( title="impl", objective="o", output_format="f" )

    def _coder( self, files=None ):
        return DelegationResult( task_index=0, task_title="impl", status="success",
                                 output="did it", files_changed=files or [] )

    def test_verify_pass_no_test_files( self ):
        o = _mk_orch()
        msgs = ( _assistant( _text( "all tests pass" ) ), )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ):
            vr = _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )
        self.assertTrue( vr.passed )

    def test_verify_runs_pytest_on_test_file_and_overrides_fail( self ):
        o = _mk_orch()
        # tester self-reports pass, but independent pytest fails → passed forced False.
        # Stream exercises: non-Edit/Write tool block (1459->next), empty-path Write
        # (1461->skip append), a non-test file ("notes.txt" → 1492->continue) BEFORE the
        # matching "test_foo.py", a bare TextBlock message (1466), neither-type message.
        msgs = (
            _assistant( _text( "pass" ), _tool( "Read", "z.py" ), _tool( "Write", "" ),
                        _tool( "Write", "notes.txt" ), _tool( "Write", "test_foo.py" ), MagicMock() ),
            orch_mod.TextBlock( text=" more" ),
            MagicMock( spec=orch_mod.ResultMessage ),
            MagicMock( spec=orch_mod.RateLimitEvent ),
            MagicMock(),
        )
        run_result = MagicMock( passed=False, total_tests=1, passed_count=0,
                                failed_count=1, error_count=0, timed_out=False )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "notification_hook", AsyncMock() ), \
             patch.object( orch_mod, "run_pytest", AsyncMock( return_value=run_result ) ):
            vr = _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )
        self.assertFalse( vr.passed )

    def test_verify_pytest_passes_keeps_verdict( self ):
        # 1503->1505: independent pytest PASSES → skip the passed=False override, break.
        o = _mk_orch()
        msgs = ( _assistant( _text( "all tests pass" ), _tool( "Write", "test_ok.py" ) ), )
        run_result = MagicMock( passed=True, total_tests=2, passed_count=2,
                                failed_count=0, error_count=0, timed_out=False )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "run_pytest", AsyncMock( return_value=run_result ) ):
            vr = _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )
        self.assertTrue( vr.passed )

    def test_verify_only_non_test_files_no_pytest( self ):
        # 1491->1507: for-loop over test_files exhausts with NO matching test file.
        o = _mk_orch()
        msgs = ( _assistant( _text( "all tests pass" ), _tool( "Write", "readme.md" ) ), )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "run_pytest", AsyncMock() ) as rp:
            vr = _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )
        rp.assert_not_awaited()   # no .py-test file → pytest never invoked
        self.assertTrue( vr.passed )

    def test_verify_safety_limit_propagates( self ):
        # 1519-1520: except SafetyLimitError: raise
        o = _mk_orch()
        with patch.object( orch_mod, "sdk_query", _sdk_stream( _assistant( _text( "x" ) ) ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o.guard, "check_timeout", side_effect=SafetyLimitError( "t" ) ):
            with self.assertRaises( SafetyLimitError ):
                _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )

    def test_verify_stop_requested_breaks( self ):
        o = _mk_orch()
        o._stop_requested = True
        with patch.object( orch_mod, "sdk_query", _sdk_stream( _assistant( _text( "pass" ) ) ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ):
            vr = _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )
        self.assertTrue( vr.passed )

    def test_verify_exception_returns_failed( self ):
        o = _mk_orch()
        def _boom( *a, **k ): raise RuntimeError( "sdk boom" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ):
            vr = _run( o._verify_result( self._spec(), self._coder(), 0, MagicMock() ) )
        self.assertFalse( vr.passed )


# ============================================================================
# _redelegate_with_feedback
# ============================================================================

class TestRedelegate( unittest.TestCase ):

    def _spec( self ):
        return TaskSpec( title="impl", objective="o", output_format="f" )

    def _coder( self ):
        return DelegationResult( task_index=0, task_title="impl", status="failure",
                                 output="prev", files_changed=[ "a.py" ] )

    def test_redelegate_success( self ):
        o = _mk_orch()
        msgs = (
            # Edit(a.py)=tracked, Read=non-Edit/Write block (1614->skip), Edit("")=empty
            # path (1616->skip append), bare MagicMock block = neither-type arc.
            _assistant( _text( "fixed " ), _tool( "Edit", "a.py" ), _tool( "Read", "z.py" ),
                        _tool( "Edit", "" ), MagicMock() ),
            orch_mod.TextBlock( text="t" ),
            MagicMock( spec=orch_mod.ResultMessage ),
            MagicMock( spec=orch_mod.RateLimitEvent ),
            MagicMock(),
        )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( *msgs ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( orch_mod, "post_tool_hook", AsyncMock() ), \
             patch.object( orch_mod, "notification_hook", AsyncMock() ):
            result = _run( o._redelegate_with_feedback( self._spec(), 0, self._coder(), "fb", 2, MagicMock() ) )
        self.assertEqual( result.status, "success" )

    def test_redelegate_stop_requested_breaks( self ):
        o = _mk_orch()
        o._stop_requested = True
        with patch.object( orch_mod, "sdk_query", _sdk_stream( _assistant( _text( "x" ) ) ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ):
            result = _run( o._redelegate_with_feedback( self._spec(), 0, self._coder(), "fb", 2, MagicMock() ) )
        self.assertEqual( result.status, "success" )

    def test_redelegate_safety_limit_propagates( self ):
        o = _mk_orch()
        with patch.object( orch_mod, "sdk_query", _sdk_stream( _assistant( _text( "x" ) ) ) ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o.guard, "check_timeout", side_effect=SafetyLimitError( "t" ) ):
            with self.assertRaises( SafetyLimitError ):
                _run( o._redelegate_with_feedback( self._spec(), 0, self._coder(), "fb", 2, MagicMock() ) )

    def test_redelegate_generic_exception_returns_failure( self ):
        o = _mk_orch()
        def _boom( *a, **k ): raise RuntimeError( "boom" )
        with patch.object( orch_mod, "sdk_query", _boom ), \
             patch.object( o, "_build_agent_options", return_value=MagicMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( o, "_notify", AsyncMock() ):
            result = _run( o._redelegate_with_feedback( self._spec(), 0, self._coder(), "fb", 2, MagicMock() ) )
        self.assertEqual( result.status, "failure" )


# ============================================================================
# _execute_live — the state machine
# ============================================================================

class _LiveFixture:
    """Patches all _execute_live collaborators; returns the orchestrator."""

    def __init__( self, test, o ):
        self.o = o
        self._patches = [
            patch.object( o, "_notify", AsyncMock() ),
            patch.object( o, "_emit_state", AsyncMock() ),
            patch.object( orch_mod, "ProgressLog", MagicMock() ),
            patch.object( orch_mod, "FeatureList", MagicMock() ),
            patch.object( orch_mod.cu, "get_project_root", MagicMock( return_value="/tmp" ) ),
        ]

    def __enter__( self ):
        for p in self._patches: p.start()
        return self.o

    def __exit__( self, *exc ):
        for p in self._patches: p.stop()
        return False


class TestExecuteLive( unittest.TestCase ):

    def _spec( self, title="t1" ):
        return TaskSpec( title=title, objective="o", output_format="f" )

    def _ok_coder( self, idx=0 ):
        return DelegationResult( task_index=idx, task_title="t1", status="success",
                                 output="done", files_changed=[ "a.py" ] )

    def _vr( self, passed, idx=0 ):
        return VerificationResult( task_index=idx, task_title="t1", passed=passed,
                                   tester_output="out", status="passed" if passed else "failed" )

    def test_sdk_unavailable_early_return( self ):
        o = _mk_orch()
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "not installed", out )

    def test_user_cancels_after_decomposition( self ):
        o = _mk_orch()
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=False ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "cancelled", out )

    def test_happy_path_verify_passes_first_iteration( self ):
        o = _mk_orch( enable_checkins=False )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( True ) ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )

    def test_require_test_pass_false_skips_verification( self ):
        o = _mk_orch( enable_checkins=False, require_test_pass=False )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )

    def test_delegate_failure_records_else_branch( self ):
        o = _mk_orch( enable_checkins=False )
        fail = DelegationResult( task_index=0, task_title="t1", status="failure",
                                 output="", errors=[ "nope" ] )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=fail ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 0/1", out )

    def test_verify_fails_then_redelegate_succeeds_then_passes( self ):
        o = _mk_orch( enable_checkins=False )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result",
                           AsyncMock( side_effect=[ self._vr( False ), self._vr( True ) ] ) ), \
             patch.object( o, "_redelegate_with_feedback", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )

    def test_verify_redelegate_fails_breaks( self ):
        o = _mk_orch( enable_checkins=False )
        bad = DelegationResult( task_index=0, task_title="t1", status="failure", output="" )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( False ) ) ), \
             patch.object( o, "_redelegate_with_feedback", AsyncMock( return_value=bad ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed", out )

    def _escalation( self, choice ):
        return { "answers": { "Escalation": choice } }

    def test_escalation_stop( self ):
        o = _mk_orch( enable_checkins=False )
        team = MagicMock(); team.request_decision = AsyncMock( return_value=self._escalation( "Stop and get help" ) )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( False ) ) ), \
             patch.object( o, "_redelegate_with_feedback", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( team ) )
        self.assertTrue( o._stop_requested )

    def test_escalation_skip_tests( self ):
        o = _mk_orch( enable_checkins=False )
        team = MagicMock(); team.request_decision = AsyncMock( return_value=self._escalation( "Skip tests for this task" ) )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( False ) ) ), \
             patch.object( o, "_redelegate_with_feedback", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( team ) )
        self.assertIn( "completed 1/1", out )

    def test_escalation_continue_counts_task_as_failed( self ):
        # A task abandoned via "Continue to next task" is marked failure in
        # state["delegation_results"] AND counted as failed in the final summary —
        # state and summary AGREE. This was a buggy-behavior pin paired with an armed
        # xfail-strict TRIPWIRE while the prod bug stood: orchestrator.py's escalation
        # updated state["delegation_results"][-1] but left the local `results` list (which
        # the summary sums) as the stale SUCCESS object → the summary over-reported 1/1.
        # De-armed once the fix landed (results[-1] = result alongside the state update).
        o = _mk_orch( enable_checkins=False )
        team = MagicMock(); team.request_decision = AsyncMock( return_value=self._escalation( "Continue to next task" ) )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( False ) ) ), \
             patch.object( o, "_redelegate_with_feedback", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( team ) )
        self.assertIn( "completed 0/1", out )   # summary now AGREES with state (was buggy 1/1)
        self.assertEqual( o.state[ "delegation_results" ][ -1 ].status, "failure" )

    def test_stop_requested_breaks_loop( self ):
        o = _mk_orch( enable_checkins=False )
        o._stop_requested = True
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 0/1", out )   # loop broke before delegating

    def test_urgent_interrupt_triggers_checkin_and_feedback_injection( self ):
        o = _mk_orch( enable_user_messages=True, enable_checkins=False )
        o._urgent_interrupt.set()
        checkin = AsyncMock( side_effect=[ "use urgent guidance", None ] )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( True ) ) ), \
             patch.object( o, "_check_in_with_user", checkin ):
            out = _run( o._execute_live( MagicMock() ) )
        # urgent feedback stored then injected into the spec (user_feedback cleared after)
        self.assertIn( "completed 1/1", out )

    def test_between_task_checkin_feedback( self ):
        o = _mk_orch( enable_checkins=True )
        # two tasks → between-task check-in fires after task 1.
        specs = [ self._spec( "t1" ), self._spec( "t2" ) ]
        checkin = AsyncMock( side_effect=[ "feedback for next", None ] )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=specs ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( side_effect=[ self._ok_coder( 0 ), self._ok_coder( 1 ) ] ) ), \
             patch.object( o, "_verify_result", AsyncMock( side_effect=[ self._vr( True, 0 ), self._vr( True, 1 ) ] ) ), \
             patch.object( o, "_check_in_with_user", checkin ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 2/2", out )

    def test_safety_limit_error_propagates_from_loop( self ):
        o = _mk_orch( enable_checkins=False )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( side_effect=SafetyLimitError( "limit" ) ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            with self.assertRaises( SafetyLimitError ):
                _run( o._execute_live( MagicMock() ) )

    def test_generic_exception_in_delegation_recorded( self ):
        o = _mk_orch( enable_checkins=False )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( side_effect=RuntimeError( "boom" ) ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 0/1", out )   # exception → failure result appended

    def test_narrate_progress_disabled( self ):
        # 860->865: narrate_progress False → on_log stays None.
        o = _mk_orch( enable_checkins=False, narrate_progress=False )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( True ) ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )

    def test_narrate_callback_fires_via_real_progress_log( self ):
        # 862: the _narrate body runs when the REAL ProgressLog invokes on_log.
        o = _mk_orch( enable_checkins=False, narrate_progress=True )
        with patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_emit_state", AsyncMock() ), \
             patch.object( orch_mod.cu, "get_project_root", return_value="/tmp/swe-narrate-test" ), \
             patch.object( orch_mod.asyncio, "ensure_future", MagicMock() ) as ef, \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( True ) ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )
        self.assertTrue( ef.called )   # _narrate scheduled at least one notify

    def test_urgent_interrupt_no_feedback_falls_through( self ):
        # 885->889: urgent set but check-in returns falsy → skip the feedback store.
        o = _mk_orch( enable_user_messages=True, enable_checkins=False )
        o._urgent_interrupt.set()
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=self._vr( True ) ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )

    def test_verify_pass_with_test_run_result_abstract( self ):
        # 939-940: verification.test_run_result truthy → test_abstract built.
        o = _mk_orch( enable_checkins=False )
        vr = VerificationResult( task_index=0, task_title="t1", passed=True,
                                 tester_output="out", status="passed",
                                 test_run_result={ "passed_count": 3, "failed_count": 0, "error_count": 0 } )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=[ self._spec() ] ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( return_value=self._ok_coder() ) ), \
             patch.object( o, "_verify_result", AsyncMock( return_value=vr ) ), \
             patch.object( o, "_check_in_with_user", AsyncMock( return_value=None ) ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 1/1", out )

    def test_between_task_none_then_post_completion_feedback( self ):
        # 1068->874: between-task check-in None → loop continues.
        # 1103: post-completion check-in truthy → progress_log.log.
        o = _mk_orch( enable_checkins=True )
        specs = [ self._spec( "t1" ), self._spec( "t2" ) ]
        checkin = AsyncMock( side_effect=[ None, "final feedback" ] )
        with _LiveFixture( self, o ), \
             patch.object( o, "_decompose_task", AsyncMock( return_value=specs ) ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ), \
             patch.object( o, "_delegate_task", AsyncMock( side_effect=[ self._ok_coder( 0 ), self._ok_coder( 1 ) ] ) ), \
             patch.object( o, "_verify_result", AsyncMock( side_effect=[ self._vr( True, 0 ), self._vr( True, 1 ) ] ) ), \
             patch.object( o, "_check_in_with_user", checkin ):
            out = _run( o._execute_live( MagicMock() ) )
        self.assertIn( "completed 2/2", out )


if __name__ == "__main__":
    unittest.main()
