"""
Unit tests for the TestFixExpediter facade + config modules:
  - voice_io.py      : re-exports BFE voice_io functions (shared core)
  - __init__.py      : package aggregator (__all__ + __version__)
  - cosa_interface.py: SENDER_ID const + _get_sender_id + 4 async delegating wrappers
  - config.py        : TestFixExpediterConfig dataclass — defaults, __post_init__
                       budget mirror, from_config() type-coercion dispatch, and the
                       TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE env-var override
                       (unset / valid / malformed × debug on/off)

config_mgr + the BFE cosa-voice facade are mocked at the boundary — no real
notification / INI / network. quick_smoke_test + __main__ excluded via pyproject.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import asyncio
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.test_fix_expediter.voice_io as tfe_vio
import cosa.agents.test_fix_expediter.cosa_interface as tfe_ci
import cosa.agents.test_fix_expediter.config as tfe_config
from cosa.agents.bug_fix_expediter import voice_io as bfe_vio

# Alias under a non-"Test" name: a module global literally named
# TestFixExpediterConfig would trip pytest's test-class collection
# (PytestCollectionWarning), since the class starts with "Test".
_Config = tfe_config.TestFixExpediterConfig


def _run( coro ):
    return asyncio.run( coro )


class TestVoiceIoReExports( unittest.TestCase ):
    """TFE voice_io re-exports the SAME callables as BFE's voice_io."""

    def test_reexports_are_bfe_objects( self ):
        self.assertIs( tfe_vio.set_cli_mode,        bfe_vio.set_cli_mode )
        self.assertIs( tfe_vio.reset_voice_check,   bfe_vio.reset_voice_check )
        self.assertIs( tfe_vio.is_voice_available,  bfe_vio.is_voice_available )
        self.assertIs( tfe_vio.get_mode_description, bfe_vio.get_mode_description )
        self.assertIs( tfe_vio.notify,     bfe_vio.notify )
        self.assertIs( tfe_vio.ask_yes_no, bfe_vio.ask_yes_no )
        self.assertIs( tfe_vio.get_input,  bfe_vio.get_input )
        self.assertIs( tfe_vio.choose,     bfe_vio.choose )


class TestPackageInit( unittest.TestCase ):

    def test_version_and_all_surface( self ):
        import cosa.agents.test_fix_expediter as pkg
        self.assertEqual( pkg.__version__, "0.1.0" )
        for name in ( "TestFixExpediterConfig", "TFEPhase", "TestRemediationContext",
                      "FailureCluster", "create_initial_state", "SENDER_ID",
                      "load_from_path", "heuristic_seed", "TFEOrchestrator",
                      "TestFixExpediterJob" ):
            self.assertIn( name, pkg.__all__ )
            self.assertTrue( hasattr( pkg, name ) )


class TestCosaInterface( unittest.TestCase ):

    def test_sender_id_constant_and_helper( self ):
        self.assertEqual( tfe_ci.SENDER_ID, "test_fix_expediter@lupin.deepily.ai" )
        self.assertEqual( tfe_ci._get_sender_id(), tfe_ci.SENDER_ID )

    def test_notify_progress_delegates_to_bfe( self ):
        with patch.object( tfe_ci, "_bfe_notify_progress", AsyncMock( return_value="NP" ) ) as m:
            out = _run( tfe_ci.notify_progress( "msg", priority="high" ) )
        self.assertEqual( out, "NP" )
        m.assert_awaited_once_with( "msg", priority="high" )

    def test_ask_confirmation_delegates_to_bfe( self ):
        with patch.object( tfe_ci, "_bfe_ask_confirmation", AsyncMock( return_value=True ) ) as m:
            out = _run( tfe_ci.ask_confirmation( "ok?", default="yes" ) )
        self.assertTrue( out )
        m.assert_awaited_once_with( "ok?", default="yes" )

    def test_get_feedback_delegates_to_bfe( self ):
        with patch.object( tfe_ci, "_bfe_get_feedback", AsyncMock( return_value="fb" ) ) as m:
            out = _run( tfe_ci.get_feedback( "prompt", timeout=5 ) )
        self.assertEqual( out, "fb" )
        m.assert_awaited_once_with( "prompt", timeout=5 )

    def test_present_choices_delegates_to_bfe( self ):
        with patch.object( tfe_ci, "_bfe_present_choices", AsyncMock( return_value={ "a": 1 } ) ) as m:
            out = _run( tfe_ci.present_choices( [ { "q": 1 } ], title="T" ) )
        self.assertEqual( out, { "a": 1 } )
        m.assert_awaited_once_with( [ { "q": 1 } ], title="T" )


def _echo_get( ini_key, default=None, return_type=None ):
    _echo_get.seen[ ini_key ] = return_type
    return default


class TestConfig( unittest.TestCase ):

    def test_defaults_and_budget_mirror( self ):
        c = _Config()
        self.assertEqual( c.lead_model, "claude-opus-4-6" )
        self.assertTrue( c.auto_fix_enabled )
        self.assertEqual( c.max_clusters, 8 )
        self.assertEqual( c.min_diagnosis_confidence, 0.65 )
        self.assertEqual( c.cost_cap_usd, 15.00 )
        self.assertEqual( c.budget_usd, 15.00 )            # __post_init__ mirror

    def test_custom_values_mirror_budget( self ):
        c = _Config( cost_cap_usd=20.0, max_clusters=5 )
        self.assertEqual( c.budget_usd, 20.0 )             # mirrors cost_cap_usd
        self.assertEqual( c.max_clusters, 5 )

    def setUp( self ):
        _echo_get.seen = {}
        self.cfg_mgr = MagicMock()
        self.cfg_mgr.get.side_effect = _echo_get

    def _clean_env( self ):
        # Ensure the override env var is absent for the default from_config path.
        return patch.dict( os.environ, {}, clear=False ) if \
            "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE" not in os.environ else \
            patch.dict( os.environ, { k: v for k, v in os.environ.items()
                                      if k != "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE" }, clear=True )

    def test_from_config_dispatches_all_return_types( self ):
        with patch.dict( os.environ, {}, clear=False ):
            os.environ.pop( "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE", None )
            c = _Config.from_config( self.cfg_mgr, debug=False )
        self.assertEqual( c.budget_usd, 15.0 )             # mirror still runs
        seen = _echo_get.seen
        self.assertEqual( seen[ "test fix expediter lead model" ],      "string" )
        self.assertEqual( seen[ "test fix expediter auto fix enabled" ], "boolean" )
        self.assertEqual( seen[ "test fix expediter max clusters" ],    "int" )
        self.assertEqual( seen[ "test fix expediter min diagnosis confidence" ], "float" )

    def test_from_config_debug_prints( self ):
        with patch.dict( os.environ, {}, clear=False ):
            os.environ.pop( "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE", None )
            buf = io.StringIO()
            with redirect_stdout( buf ):
                _Config.from_config( self.cfg_mgr, debug=True )
        self.assertIn( "[TestFixExpediterConfig] lead_model", buf.getvalue() )

    def test_env_override_valid_debug_on( self ):
        with patch.dict( os.environ, { "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE": "42" } ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                c = _Config.from_config( self.cfg_mgr, debug=True )
        self.assertEqual( c.feedback_timeout_seconds, 42 )
        self.assertIn( "OVERRIDDEN to 42s", buf.getvalue() )

    def test_env_override_valid_debug_off( self ):
        with patch.dict( os.environ, { "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE": "7" } ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                c = _Config.from_config( self.cfg_mgr, debug=False )
        self.assertEqual( c.feedback_timeout_seconds, 7 )
        self.assertEqual( buf.getvalue(), "" )             # silent

    def test_env_override_malformed_debug_on( self ):
        with patch.dict( os.environ, { "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE": "not-an-int" } ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                c = _Config.from_config( self.cfg_mgr, debug=True )
        # Malformed → falls back to the INI/default value (300).
        self.assertEqual( c.feedback_timeout_seconds, 300 )
        self.assertIn( "is not an int", buf.getvalue() )

    def test_env_override_malformed_debug_off( self ):
        with patch.dict( os.environ, { "TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE": "bad" } ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                c = _Config.from_config( self.cfg_mgr, debug=False )
        self.assertEqual( c.feedback_timeout_seconds, 300 )
        self.assertEqual( buf.getvalue(), "" )


if __name__ == "__main__":
    unittest.main()
