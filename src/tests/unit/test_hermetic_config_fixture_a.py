"""
Isolation-verify pair, RED half (A): deliberately pollutes config + env state.

This module is the pollution SOURCE of the hermetic-config fixture's
verify pair. Its partner, test_hermetic_config_fixture_b.py, collects
immediately after it (alphabetical file collection within src/tests/unit/)
and asserts that NONE of the pollution injected here survived the module
boundary.

Contract being verified (src/tests/conftest.py::hermetic_config_module_boundary):
    - ConfigurationManager singleton registry is reset at module boundaries
    - Tracked env vars (LUPIN_CONFIG_MGR_CLI_ARGS, LUPIN_ROOT,
      LUPIN_TEST_HERMETIC_SENTINEL) are snapshot/restored at module boundaries
    - Pollution DOES persist WITHIN a module (module scope, not function scope)

If the fixture is removed from conftest.py, the partner module fails RED.
That fails-before behavior was captured as a landing receipt on the
pre-fixture tree (FM-21, 2026-06-11).

KEEP IN SYNC: the SENTINEL_* constants below are duplicated verbatim in
test_hermetic_config_fixture_b.py (deliberate — no cross-test-module imports).
"""
import os

from cosa.config.configuration_manager import ConfigurationManager

SENTINEL_CONFIG_KEY      = "hermetic fixture sentinel key"
SENTINEL_CONFIG_VALUE    = "polluted by test_hermetic_config_fixture_a"
SENTINEL_ENV_VAR         = "LUPIN_TEST_HERMETIC_SENTINEL"
SENTINEL_ENV_VALUE       = "polluted-env-value"
POLLUTED_CLI_ARGS_VALUE  = "config_path=/polluted splainer_path=/polluted config_block_id=POLLUTED"


class TestHermeticPollutionSource:
    """Injects every pollution vector the hermetic fixture must contain."""

    def test_pollute_config_singleton_and_env( self ):
        """
        Pollute the ConfigurationManager singleton and the tracked env vars.

        Requires:
            - LUPIN_CONFIG_MGR_CLI_ARGS holds the canonical value at module
              start (fixture setup snapshots it before this test runs)

        Ensures:
            - The CM singleton carries SENTINEL_CONFIG_KEY
            - LUPIN_TEST_HERMETIC_SENTINEL is set (was absent — exercises the
              fixture's delete-on-restore arm)
            - LUPIN_CONFIG_MGR_CLI_ARGS holds a polluted value (was present —
              exercises the fixture's restore-value arm)

        Raises:
            - None
        """
        # Instantiate BEFORE polluting env — a fresh CM reads the canonical env
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config_mgr.set_config( SENTINEL_CONFIG_KEY, SENTINEL_CONFIG_VALUE )

        os.environ[ SENTINEL_ENV_VAR ]              = SENTINEL_ENV_VALUE
        os.environ[ "LUPIN_CONFIG_MGR_CLI_ARGS" ]   = POLLUTED_CLI_ARGS_VALUE

        # Sanity: pollution took hold
        assert config_mgr.get( SENTINEL_CONFIG_KEY ) == SENTINEL_CONFIG_VALUE
        assert os.environ[ SENTINEL_ENV_VAR ] == SENTINEL_ENV_VALUE

    def test_pollution_persists_within_module( self ):
        """
        Prove the fixture is MODULE-scoped, not function-scoped.

        Requires:
            - test_pollute_config_singleton_and_env ran first in this module

        Ensures:
            - The singleton (and its sentinel key) is STILL visible here —
              a function-scoped reset would have wiped it and this test
              would fail, pinning the module-scope contract

        Raises:
            - None
        """
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        assert config_mgr.exists( SENTINEL_CONFIG_KEY )
        assert config_mgr.get( SENTINEL_CONFIG_KEY ) == SENTINEL_CONFIG_VALUE
        assert os.environ[ SENTINEL_ENV_VAR ] == SENTINEL_ENV_VALUE
        assert os.environ[ "LUPIN_CONFIG_MGR_CLI_ARGS" ] == POLLUTED_CLI_ARGS_VALUE
