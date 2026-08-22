"""
Factory pattern for creating swappable solution snapshot managers.

This module provides a unified interface for creating different solution snapshot
manager implementations based on configuration, enabling runtime switching between
the file-based and Postgres backends.
"""

from enum import Enum
from typing import Union, Dict, Any, List
import cosa.utils.util as du

from cosa.memory.snapshot_manager_interface import SolutionSnapshotManagerInterface


class ManagerType( Enum ):
    """The solution snapshot backends this app can build.

    ⚰️ FILE_BASED was REMOVED on 2026-08-21 (Rick's ruling 6791ce47, "delete after v2 lands"),
    together with `FileBasedSolutionManager` and the deprecated `SolutionSnapshotManager`.
    It had been unreachable in production for some time — `main.py` refuses to start on any
    value but "postgres" — but unreachable is not the reason it went. It was a TRAP: a grep
    for `def save_snapshot` found the deprecated file-based class FIRST, in the most
    obviously-named file, with a docstring saying it saved to files. A reviewer read that,
    believed it, and raised a false alarm that the queue was writing to files while the
    brain read Postgres. Two of the three classes carrying that method could not be built at
    all; only one could, and it was the third one found.

    One backend, so one answer to "where does a snapshot go".
    """
    POSTGRES = "postgres"

    @classmethod
    def from_string( cls, value: str ) -> 'ManagerType':
        """
        Convert string to ManagerType enum safely.

        Requires:
            - value is a string

        Ensures:
            - Returns appropriate ManagerType enum
            - Handles case insensitive matching

        Raises:
            - ValueError if value not recognized
        """
        value_lower = value.lower().strip()
        for manager_type in cls:
            if manager_type.value == value_lower:
                return manager_type

        raise ValueError( f"Unknown manager type: '{value}'. Valid options: {[mt.value for mt in cls]}" )


class SolutionSnapshotManagerFactory:
    """
    Factory for creating swappable solution snapshot managers.

    Provides centralized creation logic that allows runtime switching between
    different storage backends based on configuration.
    """

    @staticmethod
    def create_manager( manager_type: Union[ManagerType, str],
                       config: Dict[str, Any],
                       debug: bool = False,
                       verbose: bool = False ) -> SolutionSnapshotManagerInterface:
        """
        Create manager instance based on type and configuration.

        Requires:
            - manager_type is valid ManagerType or string
            - config contains required keys for the specified manager type
            - debug and verbose are booleans

        Ensures:
            - Returns appropriate manager implementation
            - Manager is configured but not initialized
            - Identical interface regardless of backend type

        Args:
            manager_type: Type of manager to create — "postgres" is the only one left
            config: Configuration dictionary with manager-specific settings
            debug: Enable debug output
            verbose: Enable verbose output

        Examples:
            # Postgres manager (no storage location — the ORM model fixes the table)
            config = {"table_name": "solution_snapshots"}
            manager = SolutionSnapshotManagerFactory.create_manager("postgres", config)

        Raises:
            - ValueError if manager_type unknown
            - ImportError if required dependencies missing
            - KeyError if required config keys missing
        """
        # Convert string to enum if needed
        if isinstance( manager_type, str ):
            manager_type = ManagerType.from_string( manager_type )

        if debug:
            print( f"Creating {manager_type.value} solution snapshot manager..." )
            if verbose:
                print( f"Configuration: {config}" )

        # Create appropriate manager implementation
        if manager_type == ManagerType.POSTGRES:
            return SolutionSnapshotManagerFactory._create_postgres_manager( config, debug, verbose )
        else:
            raise ValueError( f"Unsupported manager type: {manager_type}" )

    @staticmethod
    def _create_postgres_manager( config: Dict[str, Any], debug: bool, verbose: bool ) -> SolutionSnapshotManagerInterface:
        """
        Create the Postgres+pgvector solution snapshot manager.

        Requires:
            - config may be empty; there is NO storage location to validate and
              config["table_name"] is optional (reporting-only — the table is fixed
              by the ORM model)

        Ensures:
            - Returns PostgresSolutionManager instance
            - Validates nothing about a storage path: demanding one here would
              reject the only correct config for this backend

        Raises:
            - ImportError if PostgresSolutionManager not available
        """
        try:
            from cosa.memory.postgres_solution_manager import PostgresSolutionManager
        except ImportError as e:
            raise ImportError( f"PostgresSolutionManager not available: {e}" )

        return PostgresSolutionManager( config, debug, verbose )

    @staticmethod
    def get_available_types() -> List[str]:
        """
        Get list of available manager types.

        Requires:
            - Nothing

        Ensures:
            - Returns list of all available manager type strings
            - Useful for configuration validation and UI

        Raises:
            - None
        """
        return [manager_type.value for manager_type in ManagerType]

    @staticmethod
    def create_from_config_manager( config_mgr, debug: bool = False, verbose: bool = False ) -> SolutionSnapshotManagerInterface:
        """
        Create manager from Lupin ConfigurationManager instance.

        Convenience method that reads standard Lupin configuration keys
        and creates appropriate manager automatically.

        Requires:
            - config_mgr is valid ConfigurationManager instance
            - Required config keys present in configuration

        Ensures:
            - Returns configured manager based on config settings
            - Uses standard Lupin configuration key names
            - Builds the Postgres configuration, the only backend left

        Args:
            config_mgr: ConfigurationManager instance
            debug: Enable debug output
            verbose: Enable verbose output

        Expected Config Keys:
            - "solution snapshots manager type": "postgres" — the only accepted value
            - "solution snapshots postgres table": Reporting-only table name

        Raises:
            - ValueError if manager type not configured or invalid
            - KeyError if required config keys missing for selected type
        """
        # Get manager type from configuration
        manager_type_str = config_mgr.get( "solution snapshots manager type" )
        if not manager_type_str:
            raise ValueError( "Configuration key 'solution snapshots manager type' not found" )

        manager_type = ManagerType.from_string( manager_type_str )

        # ManagerType.POSTGRES is the only member, and `from_string` refuses anything
        # else, so there is nothing left to branch on. No storage location to read
        # either: the table is fixed by the ORM model and the connection comes from
        # the DB layer, so the only knobs here are reporting-only.
        config = {
            "table_name" : config_mgr.get( "solution snapshots postgres table", default="solution_snapshots" ),
            "enable_performance_monitoring" : config_mgr.get(
                "solution snapshots enable performance monitoring", default=True, return_type="boolean"
            )
        }

        if debug:
            print( f"Creating {manager_type.value} manager from ConfigurationManager" )
            if verbose:
                # Don't print full config as it may contain sensitive info
                print( f"Manager type: {manager_type.value}" )
                print( f"Performance monitoring: {config.get('enable_performance_monitoring', True)}" )

        return SolutionSnapshotManagerFactory.create_manager( manager_type, config, debug, verbose )


def quick_smoke_test():
    """Test the factory pattern and manager creation."""
    du.print_banner( "SolutionSnapshotManagerFactory Smoke Test", prepend_nl=True )

    try:
        # Test enum conversion
        print( "Testing ManagerType enum..." )
        pg_type = ManagerType.from_string( "POSTGRES" )  # Test case insensitive

        if pg_type == ManagerType.POSTGRES:
            print( "✓ ManagerType enum conversion working correctly" )
        else:
            print( "✗ ManagerType enum conversion failed" )

        # The retired backend is refused by name, not merely absent from the enum.
        print( "\nTesting that the retired file_based backend is refused..." )
        try:
            ManagerType.from_string( "file_based" )
            print( "✗ file_based was accepted — the deleted backend is still selectable" )
        except ValueError:
            print( "✓ file_based properly rejected (removed 2026-08-21, ruling 6791ce47)" )

        # Test invalid type handling
        print( "\nTesting invalid manager type handling..." )
        try:
            invalid_type = ManagerType.from_string( "invalid_type" )
            print( "✗ Invalid type was accepted (should have failed)" )
        except ValueError:
            print( "✓ Invalid manager type properly rejected" )

        # Test available types
        print( "\nTesting available types retrieval..." )
        available = SolutionSnapshotManagerFactory.get_available_types()
        expected_types = {"postgres"}

        if set( available ) == expected_types:
            print( f"✓ Available types correct: {available}" )
        else:
            print( f"✗ Available types incorrect. Got: {available}, Expected: {list(expected_types)}" )

        # Test factory creation (will fail since implementations don't exist yet, but should test validation)
        print( "\nTesting factory validation..." )

        # Test that the retired backend cannot be built at all
        try:
            SolutionSnapshotManagerFactory.create_manager( "file_based", {}, debug=False )
            print( "✗ the deleted file-based manager was BUILT" )
        except ValueError:
            print( "✓ the deleted file-based manager cannot be built" )

        # Test postgres config validation — an EMPTY config is valid here, because
        # this backend has no storage location to demand.
        try:
            SolutionSnapshotManagerFactory.create_manager( "postgres", {}, debug=False )
            print( "✓ Postgres manager accepts a location-free config" )
        except ImportError:
            print( "✓ Postgres manager config validation working (implementation not available)" )

        print( "\n✓ SolutionSnapshotManagerFactory smoke test completed successfully" )

    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Factory smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()
