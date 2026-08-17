"""
Factory pattern for creating swappable solution snapshot managers.

This module provides a unified interface for creating different solution snapshot
manager implementations based on configuration, enabling runtime switching between
file-based and LanceDB backends.
"""

from enum import Enum
from typing import Union, Dict, Any, List
import cosa.utils.util as du

from cosa.memory.snapshot_manager_interface import SolutionSnapshotManagerInterface
from cosa.rest.db.repositories.vector_store_backend import is_postgres_backend


class ManagerType( Enum ):
    """Enumeration of available solution snapshot manager implementations."""
    FILE_BASED = "file_based"
    LANCEDB = "lancedb"
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
            manager_type: Type of manager to create ("file_based" or "lancedb")
            config: Configuration dictionary with manager-specific settings
            debug: Enable debug output
            verbose: Enable verbose output
            
        Examples:
            # File-based manager
            config = {"path": "/src/conf/long-term-memory/solutions/"}
            manager = SolutionSnapshotManagerFactory.create_manager("file_based", config)
            
            # LanceDB manager  
            config = {
                "db_path": "/src/conf/long-term-memory/lupin.lancedb",
                "table_name": "solution_snapshots"
            }
            manager = SolutionSnapshotManagerFactory.create_manager("lancedb", config)
            
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
        if manager_type == ManagerType.FILE_BASED:
            return SolutionSnapshotManagerFactory._create_file_based_manager( config, debug, verbose )
        elif manager_type == ManagerType.LANCEDB:
            return SolutionSnapshotManagerFactory._create_lancedb_manager( config, debug, verbose )
        elif manager_type == ManagerType.POSTGRES:
            return SolutionSnapshotManagerFactory._create_postgres_manager( config, debug, verbose )
        else:
            raise ValueError( f"Unsupported manager type: {manager_type}" )
    
    @staticmethod
    def _create_file_based_manager( config: Dict[str, Any], debug: bool, verbose: bool ) -> SolutionSnapshotManagerInterface:
        """
        Create file-based solution snapshot manager.
        
        Requires:
            - config["path"] contains valid directory path
            
        Ensures:
            - Returns FileBasedSolutionManager instance
            - Manager configured with provided path
            
        Raises:
            - ImportError if FileBasedSolutionManager not available
            - KeyError if required config keys missing
        """
        try:
            from cosa.memory.file_based_solution_manager import FileBasedSolutionManager
        except ImportError as e:
            raise ImportError( f"FileBasedSolutionManager not available: {e}" )
        
        # Validate required configuration
        required_keys = ["path"]
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            raise KeyError( f"Missing required config keys for file_based manager: {missing_keys}" )
        
        return FileBasedSolutionManager( config, debug, verbose )
    
    @staticmethod
    def _create_lancedb_manager( config: Dict[str, Any], debug: bool, verbose: bool ) -> SolutionSnapshotManagerInterface:
        """
        Create LanceDB solution snapshot manager.
        
        Requires:
            - config["table_name"] contains table name
            - config carries a storage location: config["db_path"] (local backend)
              OR config["gcs_uri"] (gcs backend)

        Ensures:
            - Returns SolutionSnapshotManager instance
            - Manager configured with provided database settings
            
        Raises:
            - ImportError if SolutionSnapshotManager not available
            - KeyError if required config keys missing
        """
        try:
            from cosa.memory.lancedb_solution_manager import SolutionSnapshotManager
        except ImportError as e:
            raise ImportError( f"SolutionSnapshotManager not available: {e}" )
        
        # Validate required configuration. table_name is always required; the
        # storage location may be a local db_path OR a gcs_uri. gcs configs carry
        # gcs_uri (not db_path) — see create_from_config_manager's gcs branch — so
        # requiring db_path unconditionally would make every valid gcs config
        # unbuildable.
        #
        # A FOURTH authority on the same fact (decision 2b20a6d6): under the postgres
        # backend the manager routes to SolutionSnapshotRepository and touches NO
        # LanceDB location at all, so demanding one here rejects the only correct
        # config. Ask the storage authority before requiring a storage location.
        missing_keys = [ key for key in [ "table_name" ] if key not in config ]
        if not is_postgres_backend() and "db_path" not in config and "gcs_uri" not in config:
            missing_keys.append( "db_path|gcs_uri" )
        if missing_keys:
            raise KeyError( f"Missing required config keys for lancedb manager: {missing_keys}" )

        return SolutionSnapshotManager( config, debug, verbose )

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
            - Validates nothing about LanceDB paths: demanding a db_path/gcs_uri here
              would reject the only correct config for this backend

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
            - Handles both file_based and lancedb configurations
            
        Args:
            config_mgr: ConfigurationManager instance
            debug: Enable debug output
            verbose: Enable verbose output
            
        Expected Config Keys:
            - "solution snapshots manager type": "file_based", "lancedb" or "postgres"
            - "solution snapshots postgres table": Reporting-only table name (postgres only)
            - "solution snapshots file based path": Path for file-based storage (file_based only)
            - "storage backend": "local" or "gcs" (lancedb only, defaults to "local")
            - "solution snapshots lancedb path": Local DB path (lancedb with backend=local)
            - "solution snapshots lancedb gcs uri": GCS URI (lancedb with backend=gcs)
            - "solution snapshots lancedb table": Table name (lancedb only)
            
        Raises:
            - ValueError if manager type not configured or invalid
            - KeyError if required config keys missing for selected type
        """
        # Get manager type from configuration
        manager_type_str = config_mgr.get( "solution snapshots manager type" )
        if not manager_type_str:
            raise ValueError( "Configuration key 'solution snapshots manager type' not found" )
        
        manager_type = ManagerType.from_string( manager_type_str )
        
        # Build configuration based on manager type
        if manager_type == ManagerType.FILE_BASED:
            config = {
                "path": config_mgr.get( "solution snapshots file based path" ),
                "enable_performance_monitoring": config_mgr.get( 
                    "solution snapshots enable performance monitoring", default=True, return_type="boolean"
                )
            }
            
            if not config["path"]:
                raise KeyError( "Configuration key 'solution snapshots file based path' not found" )
                
        elif manager_type == ManagerType.POSTGRES:
            # No storage location to read: the table is fixed by the ORM model and the
            # connection comes from the DB layer, so the only knobs are reporting-only.
            config = {
                "table_name": config_mgr.get( "solution snapshots postgres table", default="solution_snapshots" ),
                "enable_performance_monitoring": config_mgr.get(
                    "solution snapshots enable performance monitoring", default=True, return_type="boolean"
                )
            }

        elif manager_type == ManagerType.LANCEDB:  # pragma: no branch - ManagerType members are validated upstream by from_string; FILE_BASED and POSTGRES are handled above, so not-those implies LANCEDB and the elif-False arc is unreachable
            # Read storage backend configuration
            storage_backend = config_mgr.get( "storage backend", default="development" )

            config = {
                "storage backend": storage_backend,
                "table_name": config_mgr.get( "solution snapshots lancedb table" ),
                "nprobes": config_mgr.get( "solution snapshots lancedb nprobes", default=20, return_type="int" ),
                "enable_performance_monitoring": config_mgr.get(
                    "solution snapshots enable performance monitoring", default=True, return_type="boolean"
                )
            }

            # Add backend-specific configuration keys
            if storage_backend == "gcs":
                config["gcs_uri"] = config_mgr.get( "solution snapshots lancedb gcs uri" )

                if not config["gcs_uri"]:
                    raise KeyError( "Configuration key 'solution snapshots lancedb gcs uri' required for GCS backend" )
            else:  # local
                config["db_path"] = config_mgr.get( "solution snapshots lancedb path" )

                if not config["db_path"]:
                    raise KeyError( "Configuration key 'solution snapshots lancedb path' required for local backend" )

            # Validate table name
            if not config["table_name"]:
                raise KeyError( "Configuration key 'solution snapshots lancedb table' is required" )
        
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
        file_type = ManagerType.from_string( "file_based" )
        lance_type = ManagerType.from_string( "LANCEDB" )  # Test case insensitive
        
        if file_type == ManagerType.FILE_BASED and lance_type == ManagerType.LANCEDB:
            print( "✓ ManagerType enum conversion working correctly" )
        else:
            print( "✗ ManagerType enum conversion failed" )
        
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
        expected_types = {"file_based", "lancedb", "postgres"}
        
        if set( available ) == expected_types:
            print( f"✓ Available types correct: {available}" )
        else:
            print( f"✗ Available types incorrect. Got: {available}, Expected: {list(expected_types)}" )
        
        # Test factory creation (will fail since implementations don't exist yet, but should test validation)
        print( "\nTesting factory validation..." )
        
        # Test file-based config validation
        try:
            SolutionSnapshotManagerFactory.create_manager( 
                "file_based", 
                {},  # Missing path
                debug=False 
            )
            print( "✗ File-based manager accepted invalid config" )
        except KeyError:
            print( "✓ File-based manager properly validates config" )
        except ImportError:
            print( "✓ File-based manager config validation working (implementation not available)" )
        
        # Test lancedb config validation  
        try:
            SolutionSnapshotManagerFactory.create_manager(
                "lancedb",
                {"db_path": "/test/path"},  # Missing table_name
                debug=False
            )
            print( "✗ LanceDB manager accepted invalid config" )
        except KeyError:
            print( "✓ LanceDB manager properly validates config" )
        except ImportError:
            print( "✓ LanceDB manager config validation working (implementation not available)" )
        
        print( "\n✓ SolutionSnapshotManagerFactory smoke test completed successfully" )
        
    except Exception as e:
        print( f"✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Factory smoke test failed", caller="quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()