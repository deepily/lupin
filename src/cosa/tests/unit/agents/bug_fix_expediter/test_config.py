"""
Unit tests for cosa.agents.bug_fix_expediter.config.

BugFixExpediterConfig is an INI-driven dataclass. Tests cover:
  - default instantiation (all field defaults)
  - custom-value instantiation
  - from_config(): the type-coercion dispatch (bool/int/float/str → return_type)
    exercised across ALL 14 mapped keys in one call, with a mocked
    ConfigurationManager.get that echoes each field default back, plus the
    debug-print branch (debug=True) and the silent branch (debug=False).

config_mgr is mocked at the boundary — no real ConfigurationManager / INI read.
quick_smoke_test + __main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig


class TestDefaults( unittest.TestCase ):
    """Dataclass field defaults."""

    def test_default_instantiation( self ):
        c = BugFixExpediterConfig()
        self.assertEqual( c.lead_model,               "claude-opus-4-6" )
        self.assertEqual( c.worker_model,             "claude-sonnet-4-6" )
        self.assertIsNone( c.thinking_effort )
        self.assertEqual( c.max_diagnosis_iterations, 3 )
        self.assertEqual( c.min_diagnosis_confidence, 0.7 )
        self.assertEqual( c.max_fix_attempts,         2 )
        self.assertEqual( c.max_file_changes_per_fix, 20 )
        self.assertEqual( c.wall_clock_timeout_secs,  600 )
        self.assertEqual( c.budget_usd,               2.00 )
        self.assertEqual( c.feedback_timeout_seconds, 300 )
        self.assertTrue( c.narrate_progress )
        self.assertFalse( c.auto_retry_on_fix )
        self.assertTrue( c.require_user_confirm )
        self.assertEqual( c.trust_mode,               "shadow" )
        self.assertFalse( c.enabled )

    def test_custom_values( self ):
        c = BugFixExpediterConfig( lead_model="custom", budget_usd=10.0, enabled=True )
        self.assertEqual( c.lead_model, "custom" )
        self.assertEqual( c.budget_usd, 10.0 )
        self.assertTrue( c.enabled )


def _echo_default_get( ini_key, default=None, return_type=None ):
    """Mocked ConfigurationManager.get — echoes the dataclass default back.

    Also records the return_type the production code computed per key so the
    test can assert the bool/int/float/str dispatch fired correctly."""
    _echo_default_get.seen[ ini_key ] = return_type
    return default


class TestFromConfig( unittest.TestCase ):
    """from_config() type-coercion dispatch across all field types."""

    def setUp( self ):
        _echo_default_get.seen = {}
        self.cfg_mgr = Mock()
        self.cfg_mgr.get.side_effect = _echo_default_get

    def test_from_config_dispatches_every_return_type( self ):
        c = BugFixExpediterConfig.from_config( self.cfg_mgr, debug=False )

        # Result mirrors defaults (mock echoed default for every key).
        self.assertEqual( c.lead_model,  "claude-opus-4-6" )   # str  → "string"
        self.assertEqual( c.max_fix_attempts, 2 )              # int  → "int"
        self.assertEqual( c.min_diagnosis_confidence, 0.7 )    # float → "float"
        self.assertFalse( c.enabled )                          # bool → "boolean"

        # All 14 mapped keys consulted exactly once.
        self.assertEqual( self.cfg_mgr.get.call_count, 14 )

        # The computed return_type per field type — proves each branch of the
        # bool/int/float/str ladder was taken (discriminating, not just "ran").
        seen = _echo_default_get.seen
        self.assertEqual( seen[ "bug fix expediter lead model" ],           "string" )
        self.assertEqual( seen[ "bug fix expediter enabled" ],              "boolean" )
        self.assertEqual( seen[ "bug fix expediter narrate progress" ],     "boolean" )
        self.assertEqual( seen[ "bug fix expediter max fix attempts" ],     "int" )
        self.assertEqual( seen[ "bug fix expediter max diagnosis iterations" ], "int" )
        self.assertEqual( seen[ "bug fix expediter min diagnosis confidence" ], "float" )
        self.assertEqual( seen[ "bug fix expediter budget usd" ],           "float" )
        self.assertEqual( seen[ "bug fix expediter trust mode" ],           "string" )

    def test_from_config_debug_prints_each_field( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            BugFixExpediterConfig.from_config( self.cfg_mgr, debug=True )
        out = buf.getvalue()
        # The debug line for at least one representative key of each type.
        self.assertIn( "[BugFixExpediterConfig] lead_model", out )
        self.assertIn( "(from INI: bug fix expediter lead model)", out )
        self.assertIn( "[BugFixExpediterConfig] enabled", out )

    def test_from_config_silent_when_debug_false( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            BugFixExpediterConfig.from_config( self.cfg_mgr, debug=False )
        self.assertEqual( buf.getvalue(), "" )


if __name__ == "__main__":
    unittest.main()
