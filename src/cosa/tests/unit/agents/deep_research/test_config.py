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
        self.assertEqual( cfg.lead_model, "claude-opus-5" )      # read from the INI, not from code
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
        mgr.get_required.side_effect = lambda ini_key, **kwargs: f"model-for[{ini_key}]"
        return mgr

    def test_loads_all_fields_with_type_coercion( self ):
        cfg = ResearchConfig.from_config( self._config_mgr() )
        self.assertIsInstance( cfg, ResearchConfig )
        # model fields are read with get_required, which has no default
        self.assertEqual( cfg.lead_model, "model-for[deep research lead model]" )
        self.assertEqual( cfg.subagent_model, "model-for[deep research subagent model]" )
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


class TestFromConfigReadsThroughTheSharedLoader( unittest.TestCase ):
    """from_config reads through the shared loader: silently, with one debug line."""

    def _recording_mgr( self ):
        mgr = Mock()
        mgr.get.side_effect = lambda ini_key, default=None, silent=False, return_type="string": default
        mgr.get_required.side_effect = lambda ini_key, **kwargs: f"model-for[{ini_key}]"
        return mgr

    def test_every_key_is_read_once_with_silent_true( self ):
        mgr = self._recording_mgr()
        ResearchConfig.from_config( mgr )
        calls = mgr.get.call_args_list + mgr.get_required.call_args_list     # 24 through get, the two model ids through get_required
        self.assertEqual( ( mgr.get.call_count, mgr.get_required.call_count ), ( 24, 2 ) )
        self.assertEqual( { call.kwargs[ "silent" ] for call in calls }, { True } )
        self.assertEqual( len( { call.args[ 0 ] for call in calls } ), 26 )

    def test_each_key_carries_the_field_default_and_a_type_coerced_return_type( self ):
        mgr = self._recording_mgr()
        ResearchConfig.from_config( mgr )
        asked = { call.args[ 0 ]: ( call.kwargs[ "default" ], call.kwargs[ "return_type" ] ) for call in mgr.get.call_args_list }
        self.assertNotIn( "deep research lead model", asked )        # the model ids have no default: they go through get_required
        self.assertEqual( [ call.args[ 0 ] for call in mgr.get_required.call_args_list ], [ "deep research lead model", "deep research subagent model" ] )
        self.assertEqual( asked[ "deep research max subagents complex" ], ( 10, "int" ) )
        self.assertEqual( asked[ "deep research prefer primary sources" ][ 1 ], "boolean" )
        self.assertEqual( asked[ "deep research audience context" ], ( None, "string" ) )

    def test_debug_prints_one_summary_line_and_no_per_field_lines( self ):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout( out ):
            ResearchConfig.from_config( self._recording_mgr(), debug=True )
        self.assertEqual( out.getvalue().splitlines(), [ "[ResearchConfig.from_config] Loaded 26 fields from INI" ] )

    def test_a_missing_audience_context_key_stays_none( self ):
        self.assertIsNone( ResearchConfig.from_config( self._recording_mgr() ).audience_context )


class TestFromConfigThroughTheRealManager( unittest.TestCase ):
    """The real manager over the real INI returns each field as its annotated type."""

    ARGS = ( "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini "
             "config_block_id=Lupin:+Development" )

    def test_every_field_has_its_annotated_type_and_an_empty_audience_context_is_none( self ):
        import os
        from dataclasses import fields
        from cosa.config.configuration_manager import ConfigurationManager
        os.environ[ "LUPIN_CONFIG_MGR_CLI_ARGS" ] = self.ARGS
        mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
        try:
            cfg = ResearchConfig.from_config( mgr )
        finally:
            ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
        typed = [ f for f in fields( ResearchConfig ) if f.type in ( int, bool ) ]
        self.assertGreater( len( typed ), 5 )
        for f in typed:
            self.assertIs( type( getattr( cfg, f.name ) ), f.type, f.name )
        self.assertIsInstance( cfg.lead_model, str )
        self.assertNotEqual( cfg.audience_context, "" )


if __name__ == "__main__":
    unittest.main()
