"""
Unit tests for cosa.memory.solution_manager_factory.

Covers the ManagerType enum and the SolutionSnapshotManagerFactory:

- ManagerType.from_string (exact / case-insensitive / unknown→ValueError)
- create_manager: str→enum coercion, debug/verbose logging, file_based / lancedb
  dispatch, and the defensive unsupported-type ValueError
- _create_file_based_manager / _create_lancedb_manager: lazy-import success,
  ImportError-wrap, and missing-config-key KeyError arms
- get_available_types
- create_from_config_manager: missing-type ValueError, file_based (success +
  missing-path KeyError), lancedb local (success + missing-db_path KeyError),
  lancedb gcs (success + missing-uri KeyError), missing-table KeyError,
  debug/verbose logging

The heavy concrete managers (FileBasedSolutionManager / LanceDBSolutionManager)
are NEVER imported for real — their modules are injected into sys.modules as
lightweight fakes (or set to None to force ImportError). No filesystem, DB, or
GPU dependency.

quick_smoke_test() is excluded from coverage via pyproject exclude_also.

Created 2026-05-31 by Sam 🎙️ (CoSA coverage campaign, memory group).
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
_LANCE_MOD = "cosa.memory.lancedb_solution_manager"


class TestManagerType( unittest.TestCase ):
    """ManagerType.from_string + enum values."""

    def test_from_string_exact( self ):
        self.assertEqual( ManagerType.from_string( "file_based" ), ManagerType.FILE_BASED )
        self.assertEqual( ManagerType.from_string( "lancedb" ), ManagerType.LANCEDB )

    def test_from_string_case_insensitive_and_trimmed( self ):
        self.assertEqual( ManagerType.from_string( "  LANCEDB  " ), ManagerType.LANCEDB )
        self.assertEqual( ManagerType.from_string( "File_Based" ), ManagerType.FILE_BASED )

    def test_from_string_unknown_raises( self ):
        with self.assertRaises( ValueError ):
            ManagerType.from_string( "redis" )


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

    def test_lancedb_dispatch( self ):
        """lancedb dispatch via enum input."""
        mod, cls, created = _fake_module( _LANCE_MOD, "LanceDBSolutionManager" )
        with patch.dict( sys.modules, { _LANCE_MOD: mod } ):
            result = SolutionSnapshotManagerFactory.create_manager(
                ManagerType.LANCEDB, { "db_path": "/db", "table_name": "t" }
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


class TestCreateLancedbManager( unittest.TestCase ):
    """_create_lancedb_manager import + validation arms."""

    def test_success( self ):
        mod, cls, created = _fake_module( _LANCE_MOD, "LanceDBSolutionManager" )
        with patch.dict( sys.modules, { _LANCE_MOD: mod } ):
            result = SolutionSnapshotManagerFactory._create_lancedb_manager(
                { "db_path": "/db", "table_name": "t" }, False, False
            )
        self.assertIs( result, created )

    def test_import_error_wrapped( self ):
        with patch.dict( sys.modules, { _LANCE_MOD: None } ):
            with self.assertRaises( ImportError ):
                SolutionSnapshotManagerFactory._create_lancedb_manager(
                    { "db_path": "/db", "table_name": "t" }, False, False
                )

    def test_missing_keys_raises( self ):
        mod, cls, created = _fake_module( _LANCE_MOD, "LanceDBSolutionManager" )
        with patch.dict( sys.modules, { _LANCE_MOD: mod } ):
            with self.assertRaises( KeyError ):
                SolutionSnapshotManagerFactory._create_lancedb_manager( { "db_path": "/db" }, False, False )


class TestGetAvailableTypes( unittest.TestCase ):
    def test_returns_all_values( self ):
        self.assertEqual( set( SolutionSnapshotManagerFactory.get_available_types() ),
                          { "file_based", "lancedb" } )


class TestCreateFromConfigManager( unittest.TestCase ):
    """create_from_config_manager — both backends + every validation/log arm."""

    def _cfg( self, mapping ):
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, **kw: mapping.get( key, default )
        return cfg

    def test_missing_manager_type_raises( self ):
        cfg = self._cfg( { "solution snapshots manager type": "" } )
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

    def test_lancedb_local_success( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"   : "lancedb",
            "storage backend"                   : "local",
            "solution snapshots lancedb table"  : "snaps",
            "solution snapshots lancedb path"   : "/db.lance",
        } )
        mod, cls, created = _fake_module( _LANCE_MOD, "LanceDBSolutionManager" )
        with patch.dict( sys.modules, { _LANCE_MOD: mod } ):
            result = SolutionSnapshotManagerFactory.create_from_config_manager( cfg )
        self.assertIs( result, created )
        passed_config = cls.call_args[ 0 ][ 0 ]
        self.assertEqual( passed_config[ "db_path" ], "/db.lance" )

    def test_lancedb_local_missing_db_path_raises( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"  : "lancedb",
            "storage backend"                  : "local",
            "solution snapshots lancedb table" : "snaps",
            "solution snapshots lancedb path"  : "",
        } )
        with self.assertRaises( KeyError ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )

    def test_lancedb_gcs_currently_raises_keyerror( self ):
        """
        Pin the CURRENT (buggy) gcs path: it RAISES KeyError.

        create_from_config_manager's gcs branch builds a config carrying
        'gcs_uri' + 'table_name' but NO 'db_path'. It then delegates to
        create_manager → _create_lancedb_manager, whose required_keys are
        ['db_path', 'table_name'] (solution_manager_factory.py:162). 'db_path'
        is absent for gcs → KeyError. So a fully-valid gcs config can never
        build a manager via this path. Reported to Tiberius (he owns the fix:
        _create_lancedb_manager must accept gcs configs — require gcs_uri OR
        db_path, not db_path unconditionally). See TRIPWIRE below for the
        correct contract.
        """
        cfg = self._cfg( {
            "solution snapshots manager type"      : "lancedb",
            "storage backend"                      : "gcs",
            "solution snapshots lancedb table"     : "snaps",
            "solution snapshots lancedb gcs uri"   : "gs://bucket/db",
        } )
        mod, cls, created = _fake_module( _LANCE_MOD, "LanceDBSolutionManager" )
        with patch.dict( sys.modules, { _LANCE_MOD: mod } ):
            with self.assertRaises( KeyError ):
                SolutionSnapshotManagerFactory.create_from_config_manager( cfg )

    @unittest.expectedFailure
    def test_lancedb_gcs_should_build_manager_TRIPWIRE( self ):
        """
        TRIPWIRE (expectedFailure): the CORRECT gcs contract.

        Once _create_lancedb_manager accepts gcs configs (db_path OR gcs_uri),
        a valid gcs config builds the manager and this xpasses.
        """
        cfg = self._cfg( {
            "solution snapshots manager type"      : "lancedb",
            "storage backend"                      : "gcs",
            "solution snapshots lancedb table"     : "snaps",
            "solution snapshots lancedb gcs uri"   : "gs://bucket/db",
        } )
        mod, cls, created = _fake_module( _LANCE_MOD, "LanceDBSolutionManager" )
        with patch.dict( sys.modules, { _LANCE_MOD: mod } ):
            result = SolutionSnapshotManagerFactory.create_from_config_manager( cfg )
        self.assertIs( result, created )

    def test_lancedb_gcs_missing_uri_raises( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"    : "lancedb",
            "storage backend"                    : "gcs",
            "solution snapshots lancedb table"   : "snaps",
            "solution snapshots lancedb gcs uri" : "",
        } )
        with self.assertRaises( KeyError ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )

    def test_lancedb_missing_table_raises( self ):
        cfg = self._cfg( {
            "solution snapshots manager type"  : "lancedb",
            "storage backend"                  : "local",
            "solution snapshots lancedb table" : "",
            "solution snapshots lancedb path"  : "/db.lance",
        } )
        with self.assertRaises( KeyError ):
            SolutionSnapshotManagerFactory.create_from_config_manager( cfg )


if __name__ == "__main__":
    unittest.main()
