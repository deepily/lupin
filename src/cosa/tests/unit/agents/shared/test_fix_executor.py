"""
Unit tests for cosa.agents.shared.fix_executor (FixExecutor + helpers).

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, shared/ lane — finale).
FixExecutor is the shared Coder+Tester retry loop feeding BFE/TFE. The actual SDK
delegations (delegate_to_coder_fn / verify_fix_fn) and notify_fn are injected callbacks
→ supplied as AsyncMocks so NO real Claude Agent SDK / git / network fires. SafetyGuard
is real (pure in-process counters). FixResult is the real bfe.state type. ZERO spend.

SCOUT: read execute_fix's loop + both exception handlers hard — no prod bug found
(defensive throughout; the lazy FixResult import, the dedup-extend, and the
record_success/record_failure wiring are all correct). Registry pollution is avoided by
registering a unique test key in setUp and deleting it in tearDown.

Must run via run-sdk-cov.sh (fix_executor imports swe_team.safety_limits → SDK chain).
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from cosa.agents.swe_team.safety_limits import SafetyLimitError
import cosa.agents.shared.fix_executor as fe
from cosa.agents.shared.fix_executor import (
    FixExecutor, register_fix_prompts, FIX_PROMPT_BUILDERS, _tail_lines,
)

KEY = "test_exec_key"


# ===========================================================================
# _tail_lines
# ===========================================================================
class TestTailLines( unittest.TestCase ):

    def test_empty_returns_empty( self ):
        self.assertEqual( _tail_lines( None ), "" )
        self.assertEqual( _tail_lines( "" ), "" )

    def test_short_text_unchanged_tail( self ):
        self.assertEqual( _tail_lines( "a\nb\nc", max_lines=12 ), "a\nb\nc" )

    def test_truncates_to_last_lines( self ):
        text = "\n".join( str( i ) for i in range( 20 ) )
        out = _tail_lines( text, max_lines=3 )
        self.assertEqual( out, "17\n18\n19" )

    def test_char_cap_prepends_ellipsis( self ):
        text = "x" * 5000
        out = _tail_lines( text, max_lines=12, max_chars=100 )
        self.assertTrue( out.startswith( "…\n" ) )
        self.assertLessEqual( len( out ), 102 )


# ===========================================================================
# register_fix_prompts
# ===========================================================================
class TestRegisterFixPrompts( unittest.TestCase ):

    def tearDown( self ):
        FIX_PROMPT_BUILDERS.pop( "reg_key", None )

    def test_registers_bundle( self ):
        register_fix_prompts(
            "reg_key",
            build_fix_prompt=lambda *a: "f",
            build_verify_prompt=lambda *a: "v",
            build_redelegate_prompt=lambda *a: "r",
            coder_system_prompt="C",
            tester_system_prompt="T",
        )
        self.assertEqual( FIX_PROMPT_BUILDERS[ "reg_key" ][ "coder_system_prompt" ], "C" )
        self.assertIn( "build_redelegate_prompt", FIX_PROMPT_BUILDERS[ "reg_key" ] )


# ===========================================================================
# Shared base for FixExecutor construction + execute_fix
# ===========================================================================
class _ExecBase( unittest.IsolatedAsyncioTestCase ):

    def setUp( self ):
        self.build_fix        = MagicMock( return_value="FIX PROMPT" )
        self.build_redelegate = MagicMock( return_value="REDELEGATE PROMPT" )
        register_fix_prompts(
            KEY,
            build_fix_prompt=self.build_fix,
            build_verify_prompt=lambda *a: "V",
            build_redelegate_prompt=self.build_redelegate,
            coder_system_prompt="C",
            tester_system_prompt="T",
        )

    def tearDown( self ):
        FIX_PROMPT_BUILDERS.pop( KEY, None )

    def make_executor( self, max_attempts=2, delegate=None, verify=None,
                       is_cancelled=None, debug=False ):
        config = SimpleNamespace(
            max_fix_attempts=max_attempts, wall_clock_timeout_secs=60,
            feedback_timeout_seconds=30,
        )
        return FixExecutor(
            config=config,
            fix_context=SimpleNamespace( user_email="u@x.com" ),
            job_id="job-1",
            prompt_builder_key=KEY,
            voice_io_module=MagicMock(),
            cosa_interface_module=MagicMock(),
            notify_fn=AsyncMock(),
            is_cancelled_fn=is_cancelled or ( lambda: False ),
            delegate_to_coder_fn=delegate or AsyncMock( return_value=( "CODE", [ "a.py" ] ) ),
            verify_fix_fn=verify or AsyncMock( return_value=( True, "tester ok" ) ),
            debug=debug,
        )

    def selected_fix( self ):
        return SimpleNamespace( title="Fix X", fix_type="patch", risk_level="low" )


class TestConstruction( _ExecBase ):

    def test_unknown_key_raises( self ):
        config = SimpleNamespace( max_fix_attempts=1, wall_clock_timeout_secs=60, feedback_timeout_seconds=30 )
        with self.assertRaises( KeyError ):
            FixExecutor(
                config=config, fix_context=None, job_id="j", prompt_builder_key="nope",
                voice_io_module=None, cosa_interface_module=None,
                notify_fn=AsyncMock(), is_cancelled_fn=lambda: False,
                delegate_to_coder_fn=AsyncMock(), verify_fix_fn=AsyncMock(),
            )

    def test_valid_construction_defaults( self ):
        ex = self.make_executor()
        self.assertEqual( ex.prompt_builder_key, KEY )
        self.assertEqual( ex.last_coder_output, "" )
        self.assertEqual( ex.last_files_changed, [ ] )
        self.assertIsNone( ex.worktree_cwd )


class TestExecuteFix( _ExecBase ):

    async def test_coder_no_output_initial( self ):
        ex = self.make_executor( delegate=AsyncMock( return_value=( "", [ ] ) ) )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertFalse( result.success )
        self.assertEqual( result.details, "Coder produced no output" )

    async def test_pass_first_iteration( self ):
        ex = self.make_executor( debug=True, verify=AsyncMock( return_value=( True, "ok" ) ) )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertTrue( result.success )
        self.assertTrue( result.applied )
        self.assertEqual( result.attempts, 1 )
        self.assertEqual( ex.last_coder_output, "CODE" )

    async def test_cancelled_during_loop( self ):
        ex = self.make_executor( is_cancelled=lambda: True )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertTrue( result.applied )
        self.assertFalse( result.success )
        self.assertEqual( result.details, "Cancelled during verification" )

    async def test_auto_reject_after_max_iterations( self ):
        # max_attempts=1, verify always fails → iteration 1 >= 1 → auto-reject.
        ex = self.make_executor(
            max_attempts=1,
            verify=AsyncMock( return_value=( False, "FAILED\nline1\nline2" ) ),
        )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertFalse( result.success )
        self.assertIn( "Auto-rejected", result.details )
        self.assertEqual( result.attempts, 1 )
        self.assertIn( "FAILED", result.last_stderr )

    async def test_redelegate_then_pass( self ):
        # iter1 fail → re-delegate (new files incl dup) → iter2 pass.
        verify = AsyncMock( side_effect=[ ( False, "fail out" ), ( True, "pass out" ) ] )
        delegate = AsyncMock( side_effect=[ ( "CODE1", [ "a.py" ] ), ( "CODE2", [ "a.py", "b.py" ] ) ] )
        ex = self.make_executor( max_attempts=2, verify=verify, delegate=delegate )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertTrue( result.success )
        self.assertEqual( result.attempts, 2 )
        self.assertEqual( sorted( files ), [ "a.py", "b.py" ] )   # deduped extend
        self.build_redelegate.assert_called_once()

    async def test_redelegate_produces_no_output( self ):
        verify = AsyncMock( return_value=( False, "fail" ) )
        delegate = AsyncMock( side_effect=[ ( "CODE1", [ "a.py" ] ), ( "", [ ] ) ] )
        ex = self.make_executor( max_attempts=3, verify=verify, delegate=delegate )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertFalse( result.success )
        self.assertEqual( result.details, "Coder re-delegation failed" )

    async def test_max_attempts_zero_skips_loop( self ):
        # max_fix_attempts=0 → range(1,1) empty → loop body never runs (256->357
        # natural-exit arc). Coder ran once; result stays the applied=False default.
        ex = self.make_executor( max_attempts=0, delegate=AsyncMock( return_value=( "CODE", [ "a.py" ] ) ) )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertFalse( result.applied )
        self.assertFalse( result.success )
        self.assertEqual( files, [ "a.py" ] )

    async def test_safety_limit_error( self ):
        ex = self.make_executor( delegate=AsyncMock( side_effect=SafetyLimitError( "too many" ) ) )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertFalse( result.success )
        self.assertIn( "Safety limit", result.details )

    async def test_general_exception( self ):
        ex = self.make_executor( delegate=AsyncMock( side_effect=ValueError( "kaboom" ) ) )
        result, files = await ex.execute_fix( diagnosis=SimpleNamespace(), selected_fix=self.selected_fix() )
        self.assertFalse( result.success )
        self.assertEqual( result.details, "kaboom" )


if __name__ == "__main__":
    unittest.main()
