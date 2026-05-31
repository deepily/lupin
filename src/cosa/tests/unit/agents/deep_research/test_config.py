"""
Unit tests for cosa.agents.deep_research.config.ResearchConfig.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
dataclass + INI-loading logic — no network/LLM/SDK. The ConfigurationManager is
mocked at the boundary so from_config() is exercised without reading real INI.
"""

import unittest
from unittest.mock import Mock

from cosa.agents.deep_research.config import ResearchConfig


class TestGetMaxSubagents( unittest.TestCase ):
    """get_max_subagents — complexity → limit mapping + unknown fallback."""

    def setUp( self ):
        self.config = ResearchConfig()

    def test_simple( self ):
        self.assertEqual( self.config.get_max_subagents( "simple" ), 1 )

    def test_moderate( self ):
        self.assertEqual( self.config.get_max_subagents( "moderate" ), 4 )

    def test_complex( self ):
        self.assertEqual( self.config.get_max_subagents( "complex" ), 10 )

    def test_unknown_falls_back_to_moderate( self ):
        self.assertEqual( self.config.get_max_subagents( "nonsense" ), 4 )

    def test_custom_limits_respected( self ):
        cfg = ResearchConfig( max_subagents_simple=2, max_subagents_complex=20 )
        self.assertEqual( cfg.get_max_subagents( "simple" ), 2 )
        self.assertEqual( cfg.get_max_subagents( "complex" ), 20 )


class TestDefaults( unittest.TestCase ):
    """Dataclass defaults + Optional handling."""

    def test_default_models_and_audience( self ):
        cfg = ResearchConfig()
        self.assertEqual( cfg.lead_model, "claude-opus-4-6" )
        self.assertEqual( cfg.subagent_model, "claude-sonnet-4-6" )
        self.assertEqual( cfg.audience, "academic" )
        self.assertIsNone( cfg.audience_context )

    def test_custom_audience_context( self ):
        cfg = ResearchConfig( audience="beginner", audience_context="ML architect" )
        self.assertEqual( cfg.audience, "beginner" )
        self.assertEqual( cfg.audience_context, "ML architect" )


class TestFromConfig( unittest.TestCase ):
    """from_config — INI → dataclass with per-type return_type coercion."""

    def _config_mgr( self, overrides=None ):
        """
        Mock ConfigurationManager whose get() returns a type-appropriate value driven
        by the requested return_type (so the int / boolean / string coercion arms in
        from_config are all exercised). `overrides` maps ini_key → forced return value.
        """
        overrides = overrides or {}
        def fake_get( ini_key, default=None, silent=False, return_type="string" ):
            if ini_key in overrides:
                return overrides[ ini_key ]
            if return_type == "int":     return 7
            if return_type == "boolean": return False
            if return_type == "float":   return 1.5      # no float field today; defensive
            return default                                # string → echo the dataclass default
        mgr = Mock()
        mgr.get.side_effect = fake_get
        return mgr

    def test_loads_all_fields_with_type_coercion( self ):
        cfg = ResearchConfig.from_config( self._config_mgr() )
        self.assertIsInstance( cfg, ResearchConfig )
        # string field echoed from its default
        self.assertEqual( cfg.lead_model, "claude-opus-4-6" )
        # int fields coerced via return_type="int"
        self.assertEqual( cfg.max_subagents_simple, 7 )
        self.assertEqual( cfg.feedback_timeout_seconds, 7 )
        self.assertIsInstance( cfg.max_concurrent_subagents, int )
        # bool fields coerced via return_type="boolean"
        self.assertIs( cfg.stream_thoughts_to_voice, False )
        self.assertIs( cfg.prefer_primary_sources, False )

    def test_audience_context_empty_string_becomes_none( self ):
        mgr = self._config_mgr( overrides={ "deep research audience context": "" } )
        cfg = ResearchConfig.from_config( mgr )
        self.assertIsNone( cfg.audience_context )

    def test_audience_context_none_becomes_none( self ):
        mgr = self._config_mgr( overrides={ "deep research audience context": None } )
        cfg = ResearchConfig.from_config( mgr )
        self.assertIsNone( cfg.audience_context )

    def test_audience_context_populated_preserved( self ):
        mgr = self._config_mgr( overrides={ "deep research audience context": "AI architect" } )
        cfg = ResearchConfig.from_config( mgr )
        self.assertEqual( cfg.audience_context, "AI architect" )

    def test_debug_flag_prints_without_error( self ):
        cfg = ResearchConfig.from_config( self._config_mgr(), debug=True )
        self.assertIsInstance( cfg, ResearchConfig )


if __name__ == "__main__":
    unittest.main()
