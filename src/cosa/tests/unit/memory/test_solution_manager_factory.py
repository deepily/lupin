"""
Unit tests for cosa.memory.solution_manager_factory.

Covers the ManagerType enum and the SolutionSnapshotManagerFactory:

- ManagerType.from_string (exact / case-insensitive / unknown→ValueError)
- create_manager: str→enum coercion, debug/verbose logging, file_based / postgres
  dispatch, and the defensive unsupported-type ValueError
- _create_file_based_manager / _create_postgres_manager: lazy-import success,
  ImportError-wrap, and missing-config-key KeyError arms
- get_available_types
- create_from_config_manager: missing-type ValueError, file_based (success +
  missing-path KeyError), postgres (explicit table, defaulted table, no storage
  keys read), debug/verbose logging

The heavy concrete managers (FileBasedSolutionManager / PostgresSolutionManager)
are NEVER imported for real — their modules are injected into sys.modules as
lightweight fakes (or set to None to force ImportError). No filesystem, DB, or
GPU dependency.

quick_smoke_test() is excluded from coverage via pyproject exclude_also.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, memory group).
Reduced to two backends 2026-08-17 (row 8098838f) when the LanceDB manager and
ManagerType.LANCEDB were deleted — those cases tested code that no longer exists.
"""

import sys
import types
import unittest
from unittest.mock import Mock, patch

from cosa.memory.solution_manager_factory import (
    ManagerType,
    SolutionSnapshotManagerFactory,
)


def _fake_module( name, attr_name ):
    """Build a throwaway module exposing `attr_name` as a Mock manager class."""
    mod = types.ModuleType( name )
    created = Mock( name=f"{attr_name}_instance" )
    cls = Mock( name=attr_name, return_value=created )
    setattr( mod, attr_name, cls )
    return mod, cls, created


_FILE_MOD  = "cosa.memory.file_based_solution_manager"
_PG_MOD    = "cosa.memory.postgres_solution_manager"


class TestManagerType( unittest.TestCase ):
    """ManagerType.from_string + enum values."""

    def test_from_string_exact( self ):
        self.assertEqual( ManagerType.from_string( "file_based" ), ManagerType.FILE_BASED )
        self.assertEqual( ManagerType.from_string( "postgres" ), ManagerType.POSTGRES )

    def test_from_string_case_insensitive_and_trimmed( self ):
        self.assertEqual( ManagerType.from_string( "  POSTGRES  " ), ManagerType.POSTGRES )
        self.assertEqual( ManagerType.from_string( "File_Based" ), ManagerType.FILE_BASED )

    def test_from_string_unknown_raises( self ):
        with self.assertRaises( ValueError ):
            ManagerType.from_string( "redis" )

    def test_lancedb_is_no_longer_a_manager_type( self ):
        """The deleted backend must not resolve — this is the removal's contract."""
        with self.assertRaises( ValueError ):
            ManagerType.from_string( "lancedb" )


class TestCreateManager( unittest.TestCase ):
    """create_manager dispatch + logging + defensive arm."""

    def test_file_based_dispatch_with_logging( self ):
        """String coercion + debug/verbose logging + file_based dispatch."""
        mod, cls, created = _fake_module( _FILE_MOD, "FileBasedSolutionManager" )
        with patch.dict( sys.modules, { _FILE_MOD: mod } ), patch( "builtins.print" ):
            result = SolutionSnapshotManagerFactory.create_manager(
                "file_based", { "path": "/x" }, debug=True, verbose=True
            )
        self.assertIs( result, created )
        cls.assert_called_once_with( { "path": "/x" }, True, True )

    def test_postgres_dispatch( self ):
        """postgres dispatch via enum input."""
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            result = SolutionSnapshotManagerFactory.create_manager(
                ManagerType.POSTGRES, { "table_name": "t" }
            )
        self.assertIs( result, created )

    def test_unsupported_type_raises( self ):
        """A non-str, non-known manager_type hits the defensive ValueError arm."""
        bogus = Mock()   # not str → skips coercion; != either enum value
        with self.assertRaises( ValueError ):
            SolutionSnapshotManagerFactory.create_manager( bogus, {} )

    def test_debug_without_verbose_skips_config_log( self ):
        """debug=True, verbose=False → logs the header line but NOT the config dump."""
        mod, cls, created = _fake_module( _FILE_MOD, "FileBasedSolutionManager" )
        with patch.dict( sys.modules, { _FILE_MOD: mod } ), patch( "builtins.print" ):
            result = SolutionSnapshotManagerFactory.create_manager(
                "file_based", { "path": "/x" }, debug=True, verbose=False
            )
        self.assertIs( result, created )


class TestCreateFileBasedManager( unittest.TestCase ):
    """_create_file_based_manager import + validation arms."""

    def test_success( self ):
        mod, cls, created = _fake_module( _FILE_MOD, "FileBasedSolutionManager" )
        with patch.dict( sys.modules, { _FILE_MOD: mod } ):
            result = SolutionSnapshotManagerFactory._create_file_based_manager(
                { "path": "/x" }, False, False
            )
        self.assertIs( result, created )

    def test_import_error_wrapped( self ):
        """A missing FileBasedSolutionManager module → wrapped ImportError."""
        with patch.dict( sys.modules, { _FILE_MOD: None } ):
            with self.assertRaises( ImportError ):
                SolutionSnapshotManagerFactory._create_file_based_manager( { "path": "/x" }, False, False )

    def test_missing_path_key_raises( self ):
        mod, cls, created = _fake_module( _FILE_MOD, "FileBasedSolutionManager" )
        with patch.dict( sys.modules, { _FILE_MOD: mod } ):
            with self.assertRaises( KeyError ):
                SolutionSnapshotManagerFactory._create_file_based_manager( {}, False, False )


class TestGetAvailableTypes( unittest.TestCase ):
    def test_returns_all_values( self ):
        self.assertEqual( set( SolutionSnapshotManagerFactory.get_available_types() ),
                          { "file_based", "postgres" } )


class TestCreateFromConfigManager( unittest.TestCase ):
    """create_from_config_manager — the file_based branch + every validation/log arm."""

    def _cfg( self, mapping ):
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, **kw: mapping.get( key, default )
        return cfg

    def test_missing_manager_type_raises( self ):
        cfg = self._cfg( { "solution snapshots manager type": "" } )
        with self.assertRaises( ValueError ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )

    def test_lancedb_manager_type_now_raises( self ):
        """A config still saying `lancedb` fails loudly rather than silently degrading."""
        cfg = self._cfg( { "solution snapshots manager type": "lancedb" } )
        with self.assertRaises( ValueError ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )

    def test_file_based_success_with_logging( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"     : "file_based",
            "solution snapshots file based path"  : "/solutions/",
            "solution snapshots enable performance monitoring" : True,
        } )
        mod, cls, created = _fake_module( _FILE_MOD, "FileBasedSolutionManager" )
        with patch.dict( sys.modules, { _FILE_MOD: mod } ), patch( "builtins.print" ):
            result = SolutionSnapshotManagerFactory.create_from_config_manager( cfg, debug=True, verbose=True )
        self.assertIs( result, created )
        passed_config = cls.call_args[ 0 ][ 0 ]
        self.assertEqual( passed_config[ "path" ], "/solutions/" )

    def test_file_based_debug_without_verbose( self ):
        """create_from_config_manager debug=True, verbose=False → header log, no detail log."""
        cfg = self._cfg( {
            "solution snapshots manager type"     : "file_based",
            "solution snapshots file based path"  : "/solutions/",
        } )
        mod, cls, created = _fake_module( _FILE_MOD, "FileBasedSolutionManager" )
        with patch.dict( sys.modules, { _FILE_MOD: mod } ), patch( "builtins.print" ):
            result = SolutionSnapshotManagerFactory.create_from_config_manager( cfg, debug=True, verbose=False )
        self.assertIs( result, created )

    def test_file_based_missing_path_raises( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"    : "file_based",
            "solution snapshots file based path" : "",
        } )
        with self.assertRaises( KeyError ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )


class TestCreatePostgresManager( unittest.TestCase ):
    """_create_postgres_manager — dispatch, lazy import, and the no-validation contract.

    Added 2026-08-17 (row 5ff7b8f5) with ManagerType.POSTGRES: the Postgres backend
    has NO storage location to validate, so an empty config must be accepted —
    demanding a db_path would reject this backend's only correct config.
    """

    def test_create_manager_dispatches_to_postgres( self ):
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            result = SolutionSnapshotManagerFactory.create_manager( "postgres", {} )
        self.assertIs( result, created )
        cls.assert_called_once_with( {}, False, False )

    def test_empty_config_is_accepted( self ):
        """No required keys: nothing about a storage path may be demanded here."""
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            result = SolutionSnapshotManagerFactory._create_postgres_manager( {}, False, False )
        self.assertIs( result, created )

    def test_table_name_and_flags_pass_through( self ):
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        config = { "table_name": "snaps" }
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            SolutionSnapshotManagerFactory._create_postgres_manager( config, True, True )
        cls.assert_called_once_with( config, True, True )

    def test_import_failure_is_wrapped( self ):
        with patch.dict( sys.modules, { _PG_MOD: None } ):
            with self.assertRaises( ImportError ) as caught:
                SolutionSnapshotManagerFactory._create_postgres_manager( {}, False, False )
        self.assertIn( "PostgresSolutionManager not available", str( caught.exception ) )


class TestCreateFromConfigManagerPostgres( unittest.TestCase ):
    """create_from_config_manager — the postgres branch reads reporting-only keys."""

    def _cfg( self, mapping ):
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, **kw: mapping.get( key, default )
        return cfg

    def test_postgres_success_with_explicit_table( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"   : "postgres",
            "solution snapshots postgres table" : "snaps",
        } )
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            result = SolutionSnapshotManagerFactory.create_from_config_manager( cfg )
        self.assertIs( result, created )
        built_config = cls.call_args[ 0 ][ 0 ]
        self.assertEqual( built_config[ "table_name" ], "snaps" )
        self.assertTrue( built_config[ "enable_performance_monitoring" ] )

    def test_postgres_table_defaults_when_key_absent( self ):
        """An absent table key defaults rather than raising — it is reporting-only."""
        cfg = self._cfg( { "solution snapshots manager type": "postgres" } )
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )
        self.assertEqual( cls.call_args[ 0 ][ 0 ][ "table_name" ], "solution_snapshots" )

    def test_postgres_needs_no_storage_location( self ):
        """No db_path / gcs_uri / storage-backend key is read for this backend."""
        cfg = self._cfg( { "solution snapshots manager type": "postgres" } )
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )
        read_keys = [ call.args[ 0 ] for call in cfg.get.call_args_list ]
        for storage_key in ( "solution snapshots lancedb path",
                             "solution snapshots lancedb gcs uri",
                             "solution snapshots lancedb table" ):
            self.assertNotIn( storage_key, read_keys )

    def test_postgres_debug_verbose_logging( self ):
        cfg = self._cfg( { "solution snapshots manager type": "postgres" } )
        mod, cls, created = _fake_module( _PG_MOD, "PostgresSolutionManager" )
        with patch.dict( sys.modules, { _PG_MOD: mod } ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg, debug=True, verbose=True )
        self.assertIs( cls.call_args[ 0 ][ 0 ][ "enable_performance_monitoring" ], True )


if __name__ == "__main__":
    unittest.main()
