"""
Configuration and shared service dependencies for FastAPI application.

Provides singleton pattern for shared services including configuration management
and ID generation. These dependencies are injected into FastAPI endpoints to
ensure consistent service access across the application.

Snapshot management is deliberately absent. A get_snapshot_manager() lived here
until step 0 of the brain-integration plan; it constructed the deprecated
file-based manager with no `path`, which that class's __init__ required, so any
call raised TypeError. Nothing reached it: routers/admin.py:34 defines its own
same-named dependency returning main's Postgres singleton, and that is the one
the app uses. (The class itself was deleted on 2026-08-21, ruling 6791ce47.)
Ask main for the snapshot manager, not this module.
"""

from cosa.config.configuration_manager import ConfigurationManager
from cosa.agents.two_word_id_generator import TwoWordIdGenerator

# Global instances (initialized once)
_config_mgr = None
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