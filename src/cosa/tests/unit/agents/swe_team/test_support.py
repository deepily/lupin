"""
Unit tests for the swe_team top-level support tier (non-proxy):
  - config.py       : SweTeamConfig dataclass — defaults + from_config type-dispatch + debug
  - mock_clients.py : MockAgentMessage + MockAgentSDKSession (dry-run query stream)
  - voice_io.py     : thin wrapper that configures + re-exports core voice_io
  - __init__.py     : package aggregator (__all__ + __version__)

config_mgr + asyncio.sleep are mocked at the boundary — no real INI, no real sleeps,
no LLM/SDK/network. quick_smoke_test + __main__ excluded via root pyproject coverage cfg.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, support tier).
"""

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.config as swe_config
import cosa.agents.swe_team.mock_clients as mock_clients
import cosa.agents.swe_team.voice_io as swe_voice_io
from cosa.agents.utils import voice_io as core_voice_io


def _run( coro ):
    return asyncio.run( coro )


# ============================================================================
# config.py — SweTeamConfig
# ============================================================================

def _echo_get( ini_key, default=None, return_type=None ):
    _echo_get.seen[ ini_key ] = return_type
    return default


class TestSweTeamConfigDefaults( unittest.TestCase ):

    def test_default_values( self ):
        c = swe_config.SweTeamConfig()
        self.assertEqual( c.lead_model,   "claude-opus-4-6" )
        self.assertEqual( c.worker_model, "claude-sonnet-4-6" )
        self.assertEqual( c.max_iterations_per_task, 10 )
        self.assertEqual( c.max_tokens_per_session, 500_000 )
        self.assertEqual( c.budget_usd, 5.00 )
        self.assertTrue( c.require_test_pass )
        self.assertFalse( c.enabled )
        self.assertFalse( c.dry_run )
        self.assertEqual( c.trust_mode, "shadow" )

    def test_custom_values( self ):
        c = swe_config.SweTeamConfig( lead_model="x", budget_usd=10.0, dry_run=True )
        self.assertEqual( c.lead_model, "x" )
        self.assertEqual( c.budget_usd, 10.0 )
        self.assertTrue( c.dry_run )


class TestSweTeamConfigFromConfig( unittest.TestCase ):

    def setUp( self ):
        _echo_get.seen = {}
        self.cfg_mgr = MagicMock()
        self.cfg_mgr.get.side_effect = _echo_get

    def test_from_config_dispatches_all_return_types( self ):
        # One pass exercises all four return_type arms (str/int/bool/float fields
        # are all present in key_map) plus the false side of each type check.
        c = swe_config.SweTeamConfig.from_config( self.cfg_mgr, debug=False )
        self.assertEqual( c.lead_model, "claude-opus-4-6" )  # default fell through
        seen = _echo_get.seen
        self.assertEqual( seen[ "swe team lead model" ],              "string" )
        self.assertEqual( seen[ "swe team max iterations per task" ], "int" )
        self.assertEqual( seen[ "swe team require test pass" ],       "boolean" )
        self.assertEqual( seen[ "swe team budget usd" ],             "float" )

    def test_from_config_debug_prints( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            swe_config.SweTeamConfig.from_config( self.cfg_mgr, debug=True )
        self.assertIn( "[SweTeamConfig] lead_model", buf.getvalue() )


# ============================================================================
# mock_clients.py
# ============================================================================

class TestMockAgentMessage( unittest.TestCase ):

    def test_fields( self ):
        m = mock_clients.MockAgentMessage( role="assistant", content="hi", agent_name="coder" )
        self.assertEqual( m.role, "assistant" )
        self.assertEqual( m.content, "hi" )
        self.assertEqual( m.agent_name, "coder" )

    def test_agent_name_defaults_to_lead( self ):
        m = mock_clients.MockAgentMessage( role="assistant", content="hi" )
        self.assertEqual( m.agent_name, "lead" )


class TestMockAgentSDKSession( unittest.TestCase ):

    def test_init_session_id_format( self ):
        s = mock_clients.MockAgentSDKSession( "Build X", debug=False )
        self.assertEqual( s.task_description, "Build X" )
        self.assertTrue( s.session_id.startswith( "st-" ) )
        self.assertEqual( len( s.session_id ), 11 )  # "st-" + 8 hex
        self.assertEqual( s.messages_sent, 0 )

    def test_query_yields_six_phases_delay_skipped( self ):
        # DELAY_MULTIPLIER=0.0 → scaled_delay==0 → the `if scaled_delay > 0`
        # FALSE arc (no sleep). debug=False arc.
        with patch.object( mock_clients.MockAgentSDKSession, "DELAY_MULTIPLIER", 0.0 ):
            s = mock_clients.MockAgentSDKSession( "task", debug=False )

            async def collect():
                return [ m async for m in s.query() ]

            msgs = _run( collect() )
        self.assertEqual( len( msgs ), 6 )
        self.assertEqual( s.messages_sent, 6 )
        self.assertEqual( { m.agent_name for m in msgs },
                          { "lead", "coder", "tester", "reviewer" } )

    def test_query_delay_taken_and_debug_prints( self ):
        # DELAY_MULTIPLIER=1.0 → scaled_delay>0 → the TRUE arc (sleep awaited),
        # but asyncio.sleep is mocked so no real wall-clock cost. debug=True arc.
        with patch.object( mock_clients.MockAgentSDKSession, "DELAY_MULTIPLIER", 1.0 ), \
             patch.object( mock_clients.asyncio, "sleep", AsyncMock() ) as slept:
            s = mock_clients.MockAgentSDKSession( "a-very-long-task-description " * 5, debug=True )
            buf = io.StringIO()

            async def collect():
                return [ m async for m in s.query() ]

            with redirect_stdout( buf ):
                msgs = _run( collect() )
        self.assertEqual( len( msgs ), 6 )
        self.assertTrue( slept.await_count >= 1 )
        out = buf.getvalue()
        self.assertIn( "[MockSDK] Starting dry-run", out )

    def test_get_session_summary( self ):
        with patch.object( mock_clients.MockAgentSDKSession, "DELAY_MULTIPLIER", 0.0 ):
            s = mock_clients.MockAgentSDKSession( "x" * 200, debug=False )

            async def collect():
                return [ m async for m in s.query() ]

            _run( collect() )
        summ = s.get_session_summary()
        self.assertTrue( summ[ "dry_run" ] )
        self.assertEqual( summ[ "cost_usd" ], 0.0 )
        self.assertEqual( summ[ "tokens_used" ], 0 )
        self.assertEqual( summ[ "messages_sent" ], 6 )
        self.assertEqual( len( summ[ "task" ] ), 100 )  # truncated to [:100]


# ============================================================================
# voice_io.py — thin wrapper
# ============================================================================

class TestVoiceIoWrapper( unittest.TestCase ):

    def test_reexports_are_core_objects( self ):
        self.assertIs( swe_voice_io.set_cli_mode,        core_voice_io.set_cli_mode )
        self.assertIs( swe_voice_io.reset_voice_check,   core_voice_io.reset_voice_check )
        self.assertIs( swe_voice_io.is_voice_available,  core_voice_io.is_voice_available )
        self.assertIs( swe_voice_io.get_mode_description, core_voice_io.get_mode_description )
        self.assertIs( swe_voice_io.is_cli_mode,  core_voice_io.is_cli_mode )
        self.assertIs( swe_voice_io.set_job_id,   core_voice_io.set_job_id )
        self.assertIs( swe_voice_io.clear_job_id, core_voice_io.clear_job_id )
        self.assertIs( swe_voice_io.notify,          core_voice_io.notify )
        self.assertIs( swe_voice_io.ask_yes_no,      core_voice_io.ask_yes_no )
        self.assertIs( swe_voice_io.get_input,       core_voice_io.get_input )
        self.assertIs( swe_voice_io.choose,          core_voice_io.choose )
        self.assertIs( swe_voice_io.present_choices, core_voice_io.present_choices )

    def test_reconfigure_rebinds_core_interface( self ):
        with patch.object( core_voice_io, "configure" ) as cfg:
            swe_voice_io.reconfigure()
        cfg.assert_called_once_with( swe_voice_io._cosa_interface )


# ============================================================================
# __init__.py — package aggregator
# ============================================================================

class TestPackageInit( unittest.TestCase ):

    def test_version_and_all_surface( self ):
        import cosa.agents.swe_team as pkg
        self.assertEqual( pkg.__version__, "0.3.0" )
        for name in ( "SweTeamConfig", "OrchestratorState", "JobSubState",
                      "SweTeamState", "create_initial_state", "SAFETY_LIMITS",
                      "SafetyGuard", "AgentRole", "SweTeamOrchestrator",
                      "notify_progress", "MockAgentSDKSession", "TestRunResult",
                      "run_pytest", "notification_hook", "FeatureList",
                      "set_cli_mode", "voice_notify" ):
            self.assertIn( name, pkg.__all__ )
            self.assertTrue( hasattr( pkg, name ) )


if __name__ == "__main__":
    unittest.main()
