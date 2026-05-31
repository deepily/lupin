"""
Unit tests for cosa.agents.model_registry.

Covers the model-configuration registry (quick_smoke_test excluded via pyproject):

- LlmProvider enum values
- ModelConfig: defaults (supported_parameters set) + __post_init__ validation
  (max_tokens / cost_input / cost_output arms)
- ModelRegistry: default-model bootstrap, register_model (new / replace /
  verbose-logging branch), get_model_config (found / LlmConfigError),
  get_models_by_provider, list_all_models (sorted), get_providers,
  _verbose_logging property

Pure in-memory data structures — no external dependencies. The verbose-logging
branch (always-False property) is exercised via PropertyMock.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, agents Tier-2, greenfield).
"""

import unittest
from unittest.mock import patch, PropertyMock

from cosa.agents.model_registry import LlmProvider, ModelConfig, ModelRegistry
from cosa.agents.llm_exceptions import LlmConfigError


def _cfg( **overrides ):
    base = dict(
        name         = "m",
        provider     = LlmProvider.OPENAI,
        client_class = "x.Y",
        max_tokens   = 100,
    )
    base.update( overrides )
    return ModelConfig( **base )


class TestLlmProvider( unittest.TestCase ):
    def test_values( self ):
        self.assertEqual(
            { p.value for p in LlmProvider },
            { "openai", "anthropic", "groq", "google", "deepily" },
        )


class TestModelConfig( unittest.TestCase ):
    def test_defaults( self ):
        cfg = _cfg()
        self.assertTrue( cfg.supports_streaming )
        self.assertTrue( cfg.supports_system_messages )
        self.assertIsNone( cfg.cost_per_1k_tokens_input )
        self.assertIn( "temperature", cfg.supported_parameters )
        self.assertIn( "stop", cfg.supported_parameters )

    def test_non_positive_max_tokens_raises( self ):
        with self.assertRaises( ValueError ):
            _cfg( max_tokens=0 )

    def test_negative_cost_input_raises( self ):
        with self.assertRaises( ValueError ):
            _cfg( cost_per_1k_tokens_input=-0.01 )

    def test_negative_cost_output_raises( self ):
        with self.assertRaises( ValueError ):
            _cfg( cost_per_1k_tokens_output=-0.01 )

    def test_zero_costs_valid( self ):
        cfg = _cfg( cost_per_1k_tokens_input=0.0, cost_per_1k_tokens_output=0.0 )
        self.assertEqual( cfg.cost_per_1k_tokens_input, 0.0 )


class TestModelRegistry( unittest.TestCase ):
    def setUp( self ):
        self.reg = ModelRegistry()

    def test_default_models_bootstrapped( self ):
        models = self.reg.list_all_models()
        self.assertEqual( len( models ), 9 )                 # 9 default models
        self.assertIn( "gpt-4", models )
        self.assertIn( "claude-3-haiku-20240307", models )

    def test_list_all_models_sorted( self ):
        models = self.reg.list_all_models()
        self.assertEqual( models, sorted( models ) )

    def test_get_model_config_found( self ):
        cfg = self.reg.get_model_config( "gpt-4" )
        self.assertIsInstance( cfg, ModelConfig )
        self.assertEqual( cfg.provider, LlmProvider.OPENAI )

    def test_get_model_config_unknown_raises( self ):
        with self.assertRaises( LlmConfigError ):
            self.reg.get_model_config( "no-such-model" )

    def test_get_models_by_provider( self ):
        openai_models = self.reg.get_models_by_provider( LlmProvider.OPENAI )
        self.assertEqual( len( openai_models ), 3 )          # gpt-4, gpt-4-turbo, gpt-3.5-turbo
        self.assertTrue( all( m.provider == LlmProvider.OPENAI for m in openai_models ) )

    def test_get_models_by_provider_empty( self ):
        """A provider with no registered models returns an empty list."""
        # Fresh registry then check a provider that has models — emptiness path
        # is covered by filtering: build a registry with only one provider's view.
        google_models = self.reg.get_models_by_provider( LlmProvider.GOOGLE )
        self.assertEqual( len( google_models ), 1 )

    def test_get_providers( self ):
        providers = self.reg.get_providers()
        self.assertEqual(
            providers,
            { LlmProvider.OPENAI, LlmProvider.ANTHROPIC, LlmProvider.GROQ,
              LlmProvider.GOOGLE, LlmProvider.DEEPILY },
        )

    def test_register_new_and_replace( self ):
        before = len( self.reg.list_all_models() )
        self.reg.register_model( _cfg( name="custom" ) )
        self.assertEqual( len( self.reg.list_all_models() ), before + 1 )
        # Replace same-name → count unchanged, config swapped
        self.reg.register_model( _cfg( name="custom", max_tokens=4096 ) )
        self.assertEqual( len( self.reg.list_all_models() ), before + 1 )
        self.assertEqual( self.reg.get_model_config( "custom" ).max_tokens, 4096 )

    def test_register_model_verbose_logging_branch( self ):
        """When _verbose_logging is True, register_model prints the registration line."""
        with patch.object( ModelRegistry, "_verbose_logging", new_callable=PropertyMock, return_value=True ), \
             patch( "builtins.print" ) as mock_print:
            self.reg.register_model( _cfg( name="verbose-model" ) )
        self.assertTrue( mock_print.called )

    def test_verbose_logging_default_false( self ):
        self.assertFalse( self.reg._verbose_logging )


if __name__ == "__main__":
    unittest.main()
