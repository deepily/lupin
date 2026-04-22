"""
Unit tests for TestFixExpediterConfig.

Session 1cfcdf73 (2026-04-10): Phase 2 scaffolding tests.
"""

import pytest

from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig


class TestDefaults:

    def test_default_instantiation( self ):
        config = TestFixExpediterConfig()
        assert config.lead_model == "claude-opus-4-6"
        assert config.worker_model == "claude-sonnet-4-6"
        # Session 1cfcdf73 (2026-04-10): default flipped from False to True.
        assert config.auto_fix_enabled is True
        assert config.max_clusters == 8
        assert config.max_cluster_seed_failures == 50
        assert config.max_diagnosis_iterations == 4
        assert config.min_diagnosis_confidence == 0.65
        assert config.max_fix_attempts == 2
        assert config.cost_cap_usd == 15.00
        assert config.wall_clock_timeout_secs == 2400
        assert config.trust_mode == "inherit"
        assert config.rerun_scope == "affected"
        assert config.continue_on_cluster_failure is True
        assert config.voice_gate_mode == "aggregate"
        assert config.feedback_timeout_seconds == 300
        assert config.narrate_progress is True

    def test_budget_usd_mirrors_cost_cap_usd( self ):
        """budget_usd should mirror cost_cap_usd for shared FixExecutor compatibility."""
        config = TestFixExpediterConfig()
        assert config.budget_usd == config.cost_cap_usd == 15.00

    def test_budget_usd_mirrors_custom_cost_cap( self ):
        config = TestFixExpediterConfig( cost_cap_usd=25.0 )
        assert config.budget_usd == 25.0

    def test_custom_values( self ):
        config = TestFixExpediterConfig(
            auto_fix_enabled=True,
            max_clusters=5,
            voice_gate_mode="per_cluster",
        )
        assert config.auto_fix_enabled is True
        assert config.max_clusters == 5
        assert config.voice_gate_mode == "per_cluster"


class TestFromConfig:

    def test_from_config_loads_all_twelve_keys( self ):
        """All 12+ INI keys load without splainer warnings (step 17 of plan)."""
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config = TestFixExpediterConfig.from_config( config_mgr, debug=False )

        # Session 1cfcdf73 (2026-04-10): INI default flipped from false to true.
        assert config.auto_fix_enabled is True
        assert config.max_clusters == 8
        assert config.max_cluster_seed_failures == 50
        assert config.max_diagnosis_iterations == 4
        assert config.min_diagnosis_confidence == 0.65
        assert config.cost_cap_usd == 15.00
        assert config.wall_clock_timeout_secs == 2400
        assert config.trust_mode == "inherit"
        assert config.rerun_scope == "affected"
        assert config.continue_on_cluster_failure is True
        assert config.voice_gate_mode == "aggregate"

    def test_from_config_mirrors_budget_usd( self ):
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config = TestFixExpediterConfig.from_config( config_mgr )
        assert config.budget_usd == config.cost_cap_usd
