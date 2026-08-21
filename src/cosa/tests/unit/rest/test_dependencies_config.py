"""
Unit tests for cosa.rest.dependencies.config.

The two getters are lazy singletons backed by module globals. Each underlying
class ( ConfigurationManager / TwoWordIdGenerator ) is patched so NO real config
file / word-list load occurs.

A third getter, get_snapshot_manager, was covered here until step 0 of the
brain-integration plan deleted it. Its two tests went with it: they asserted the
lazy-singleton behaviour of a function that could not be called without raising
TypeError, so they proved the mock worked, not that the code did.

Covers both branches of every getter: first call (global is None → construct)
and subsequent call (global set → reuse, no re-construction).
"""

import unittest
from unittest.mock import patch, MagicMock

import cosa.rest.dependencies.config as cfg


class TestGetConfigManager( unittest.TestCase ):
    """
    Tests for get_config_manager.

    Ensures:
        - First call constructs with the LUPIN_CONFIG_MGR_CLI_ARGS env var name
        - Subsequent calls return the same instance without reconstructing
    """

    def setUp( self ):
        """
        Ensures:
            - Module singleton reset to None before each test
        """
        cfg._config_mgr = None

    def tearDown( self ):
        cfg._config_mgr = None

    def test_first_call_constructs_with_env_var_name( self ):
        """
        Ensures:
            - Constructs ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            - Returns the constructed instance
        """
        sentinel = MagicMock( name="config_mgr" )
        with patch.object( cfg, "ConfigurationManager", return_value=sentinel ) as klass:
            result = cfg.get_config_manager()
        self.assertIs( result, sentinel )
        klass.assert_called_once_with( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    def test_second_call_reuses_singleton( self ):
        """
        Ensures:
            - Second call returns the same instance, no second construction
        """
        sentinel = MagicMock( name="config_mgr" )
        with patch.object( cfg, "ConfigurationManager", return_value=sentinel ) as klass:
            first  = cfg.get_config_manager()
            second = cfg.get_config_manager()
        self.assertIs( first, second )
        klass.assert_called_once()


class TestGetIdGenerator( unittest.TestCase ):
    """
    Tests for get_id_generator.

    Ensures:
        - Lazy single construction + reuse semantics
    """

    def setUp( self ):
        cfg._id_generator = None

    def tearDown( self ):
        cfg._id_generator = None

    def test_first_call_constructs( self ):
        """
        Ensures:
            - First call constructs TwoWordIdGenerator and returns it
        """
        sentinel = MagicMock( name="id_generator" )
        with patch.object( cfg, "TwoWordIdGenerator", return_value=sentinel ) as klass:
            result = cfg.get_id_generator()
        self.assertIs( result, sentinel )
        klass.assert_called_once_with()

    def test_second_call_reuses_singleton( self ):
        """
        Ensures:
            - Second call returns the cached instance, no reconstruction
        """
        sentinel = MagicMock( name="id_generator" )
        with patch.object( cfg, "TwoWordIdGenerator", return_value=sentinel ) as klass:
            first  = cfg.get_id_generator()
            second = cfg.get_id_generator()
        self.assertIs( first, second )
        klass.assert_called_once()


if __name__ == "__main__":
    unittest.main()
