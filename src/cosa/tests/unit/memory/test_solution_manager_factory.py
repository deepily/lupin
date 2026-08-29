"""
Unit tests for cosa.memory.solution_manager_factory.

Covers the ManagerType enum and the SolutionSnapshotManagerFactory:

- ManagerType.from_string (exact / case-insensitive / unknown→ValueError), and that
  the two RETIRED backends — `lancedb` and, since 2026-08-21, `file_based` — are
  refused by name rather than merely absent
- create_manager: str→enum coercion and the defensive unsupported-type ValueError
- _create_postgres_manager: lazy-import success and the ImportError wrap
- get_available_types
- create_from_config_manager: missing-type ValueError, postgres (explicit table,
  defaulted table, no storage keys read), debug/verbose logging

⚰️ The file_based cases were deleted on 2026-08-21 with the backend itself (Rick's
ruling 6791ce47, "delete after v2 lands"). There is one backend now, so there is no
dispatch branch left to cover — a test that kept exercising a removed arm would be
covering a fake module and nothing else.

The heavy concrete manager (PostgresSolutionManager) is NEVER imported for real — its
module is injected into sys.modules as a lightweight fake (or set to None to force
ImportError). No filesystem, DB, or GPU dependency.

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


_PG_MOD    = "cosa.memory.postgres_solution_manager"


class TestManagerType( unittest.TestCase ):
    """ManagerType.from_string + enum values."""

    def test_from_string_exact( self ):
        self.assertEqual( ManagerType.from_string( "postgres" ), ManagerType.POSTGRES )

    def test_from_string_case_insensitive_and_trimmed( self ):
        self.assertEqual( ManagerType.from_string( "  POSTGRES  " ), ManagerType.POSTGRES )

    def test_from_string_unknown_raises( self ):
        with self.assertRaises( ValueError ):
            ManagerType.from_string( "redis" )

    def test_lancedb_is_no_longer_a_manager_type( self ):
        """The deleted backend must not resolve — this is the removal's contract."""
        with self.assertRaises( ValueError ):
            ManagerType.from_string( "lancedb" )

    def test_file_based_is_no_longer_a_manager_type( self ):
        """Same contract, for the backend deleted on 2026-08-21 (ruling 6791ce47).

        `file_based` is still the DEFAULT `main.py` reads when the key is unset, so a box
        with no configured backend reaches this and is refused rather than quietly building
        a manager whose class no longer exists.
        """
        with self.assertRaises( ValueError ):
            ManagerType.from_string( "file_based" )


class TestCreateManager( unittest.TestCase ):
    """create_manager dispatch + logging + defensive arm."""

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

class TestGetAvailableTypes( unittest.TestCase ):
    def test_returns_all_values( self ):
        self.assertEqual( set( SolutionSnapshotManagerFactory.get_available_types() ),
                          { "postgres" } )


class TestCreateFromConfigManager( unittest.TestCase ):
    """create_from_config_manager — every validation and logging arm.

    The file_based cases went with the backend on 2026-08-21 (ruling 6791ce47): there is
    one backend now, so there is no branch to cover.
    """

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
