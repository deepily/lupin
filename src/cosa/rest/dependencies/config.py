"""
Configuration and shared service dependencies for FastAPI application.

Provides singleton pattern for shared services including configuration management,
solution snapshot management, and ID generation. These dependencies are injected
into FastAPI endpoints to ensure consistent service access across the application.
"""

from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.solution_snapshot_mgr import SolutionSnapshotManager
from cosa.agents.two_word_id_generator import TwoWordIdGenerator

# Global instances (initialized once)
_config_mgr = None
_snapshot_mgr = None
_id_generator = None

def get_config_manager():
    """
    Dependency to get configuration manager singleton.
    
    Requires:
        - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set
        - ConfigurationManager class is available
        
    Ensures:
        - Returns singleton ConfigurationManager instance
        - Creates instance on first call with environment variable
        - Returns same instance on subsequent calls
        - Instance is properly initialized with CLI arguments
        
    Raises:
        - EnvironmentError if LUPIN_CONFIG_MGR_CLI_ARGS not set
        - ImportError if ConfigurationManager not available
    """
    global _config_mgr
    if _config_mgr is None:
        _config_mgr = ConfigurationManager(env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS")
    return _config_mgr

def get_snapshot_manager():
    """
    Dependency to get snapshot manager singleton.
    
    Requires:
        - SolutionSnapshotManager class is available
        - Solution snapshot directory exists and is accessible
        
    Ensures:
        - Returns singleton SolutionSnapshotManager instance
        - Creates instance on first call with default configuration
        - Returns same instance on subsequent calls
        - Instance is loaded with existing snapshots from disk
        
    Raises:
        - ImportError if SolutionSnapshotManager not available
        - FileNotFoundError if snapshot directory not accessible
    """
    global _snapshot_mgr
    if _snapshot_mgr is None:
        _snapshot_mgr = SolutionSnapshotManager()
    return _snapshot_mgr

def get_id_generator():
    """
    Dependency to get ID generator singleton.
    
    Requires:
        - TwoWordIdGenerator class is available
        - Word list files are accessible in the generator
        
    Ensures:
        - Returns singleton TwoWordIdGenerator instance
        - Creates instance on first call with default word lists
        - Returns same instance on subsequent calls
        - Instance is ready to generate unique two-word IDs
        
    Raises:
        - ImportError if TwoWordIdGenerator not available
        - FileNotFoundError if word list files not found
    """
    global _id_generator
    if _id_generator is None:
        _id_generator = TwoWordIdGenerator()
    return _id_generator