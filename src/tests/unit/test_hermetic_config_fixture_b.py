"""
Isolation-verify pair, GREEN half (B): asserts the pollution did not survive.

Partner of test_hermetic_config_fixture_a.py (which collects immediately
before this module and deliberately pollutes the ConfigurationManager
singleton + tracked env vars). Every assertion here is about state at a
fresh MODULE boundary.

WITHOUT the hermetic_config_module_boundary fixture in src/tests/conftest.py
this module fails RED — that fails-before output is part of the FM-21
landing receipt (2026-06-11).

KEEP IN SYNC: the SENTINEL_* constants below are duplicated verbatim from
test_hermetic_config_fixture_a.py (deliberate — no cross-test-module imports).
"""
import os

from cosa.config.configuration_manager import ConfigurationManager

SENTINEL_CONFIG_KEY      = "hermetic fixture sentinel key"
SENTINEL_CONFIG_VALUE    = "polluted by test_hermetic_config_fixture_a"
SENTINEL_ENV_VAR         = "LUPIN_TEST_HERMETIC_SENTINEL"
SENTINEL_ENV_VALUE       = "polluted-env-value"
POLLUTED_CLI_ARGS_VALUE  = "config_path=/polluted splainer_path=/polluted config_block_id=POLLUTED"


class TestHermeticModuleBoundary:
    """Asserts a virgin config world at the module boundary after pollution."""

    def test_config_singleton_is_virgin_at_module_boundary( self ):
        """
        A fresh CM instantiated here must NOT carry the partner's sentinel key.

        Requires:
            - test_hermetic_config_fixture_a.py ran (and polluted) before
              this module in collection order

        Ensures:
            - The CM obtained here is a re-derived instance from the canonical
              env — the set_config() sentinel from the partner module is gone

        Raises:
            - None
        """
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        assert not config_mgr.exists( SENTINEL_CONFIG_KEY ), (
            f"ConfigurationManager singleton leaked across the module boundary: "
            f"sentinel key '{SENTINEL_CONFIG_KEY}' from test_hermetic_config_fixture_a "
            f"is still present"
        )

    def test_tracked_env_vars_restored_at_module_boundary( self ):
        """
        Tracked env vars must be back to their pre-pollution state.

        Requires:
            - test_hermetic_config_fixture_a.py ran (and polluted) before
              this module in collection order

        Ensures:
            - LUPIN_TEST_HERMETIC_SENTINEL is absent again (delete-on-restore arm)
            - LUPIN_CONFIG_MGR_CLI_ARGS is back to the canonical value
              (restore-value arm), not the polluted one
            - LUPIN_ROOT is still set (suite precondition, restored not lost)

        Raises:
            - None
        """
        assert SENTINEL_ENV_VAR not in os.environ, (
            f"env var '{SENTINEL_ENV_VAR}' leaked across the module boundary"
        )
        assert os.environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS" ) != POLLUTED_CLI_ARGS_VALUE, (
            "LUPIN_CONFIG_MGR_CLI_ARGS still holds the polluted value across the module boundary"
        )
        assert "config_path=" in os.environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS", "" )
        assert os.environ.get( "LUPIN_ROOT" )
