"""
Unit tests for cosa.rest.dependencies.config.

The three getters are lazy singletons backed by module globals. Each underlying
class ( ConfigurationManager / SolutionSnapshotManager / TwoWordIdGenerator ) is
patched so NO real config file / snapshot disk load / word-list load occurs.

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


class TestGetSnapshotManager( unittest.TestCase ):
    """
    Tests for get_snapshot_manager.

    Ensures:
        - Lazy single construction + reuse semantics
    """

    def setUp( self ):
        cfg._snapshot_mgr = None

    def tearDown( self ):
        cfg._snapshot_mgr = None

    def test_first_call_constructs( self ):
        """
        Ensures:
            - First call constructs SolutionSnapshotManager and returns it
        """
        sentinel = MagicMock( name="snapshot_mgr" )
        with patch.object( cfg, "SolutionSnapshotManager", return_value=sentinel ) as klass:
            result = cfg.get_snapshot_manager()
        self.assertIs( result, sentinel )
        klass.assert_called_once_with()

    def test_second_call_reuses_singleton( self ):
        """
        Ensures:
            - Second call returns the cached instance, no reconstruction
        """
        sentinel = MagicMock( name="snapshot_mgr" )
        with patch.object( cfg, "SolutionSnapshotManager", return_value=sentinel ) as klass:
            first  = cfg.get_snapshot_manager()
            second = cfg.get_snapshot_manager()
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
