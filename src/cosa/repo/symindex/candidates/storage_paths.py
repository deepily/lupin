"""
Where the candidate stage keeps its files.

Every location comes from an INI key, and an environment variable overrides the key.
No path is written in code, and a missing key is a named error, never a default.
"""
import os
import pathlib

from cosa.repo.symindex.candidates.errors import CandidateError, STORAGE_KEY_MISSING, DEPENDENCY_MISSING

CONFIG_ENV_VAR = "LUPIN_CONFIG_MGR_CLI_ARGS"

# name : ( INI key, environment override )
KEYS = {
    "data_subdir"  : ( "reuse review data subdir",              "LUPIN_REUSE_REVIEW_DATA_SUBDIR" ),
    "vectors"      : ( "reuse candidate vectors subdir",        "LUPIN_REUSE_CANDIDATE_VECTORS_DIR" ),
    "query_cache"  : ( "reuse candidate query cache subdir",    "LUPIN_REUSE_CANDIDATE_QUERY_CACHE_DIR" ),
    "purpose"      : ( "reuse candidate purpose lines subdir",  "LUPIN_REUSE_CANDIDATE_PURPOSE_DIR" ),
    "interpreter"  : ( "reuse candidate search interpreter",    "LUPIN_REUSE_CANDIDATE_INTERPRETER" )
}


def build_config():
    """
    Build the ConfigurationManager of this process.

    Ensures:
        - returns the manager built from the environment variable of the registered command

    Raises:
        - CandidateError DEPENDENCY_MISSING when the manager cannot be built
    """
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        return ConfigurationManager( env_var_name=CONFIG_ENV_VAR )
    except Exception as e:
        raise CandidateError( DEPENDENCY_MISSING, f"no ConfigurationManager in this process: {e}" )


def _read( name, config, environ ):
    """
    Read one key.

    Ensures:
        - returns ( value, from_env ) with the environment value when it is set and not blank
        - otherwise returns the INI value, with from_env False

    Raises:
        - CandidateError DEPENDENCY_MISSING for the interpreter key, STORAGE_KEY_MISSING for the others,
          when both sources are absent or blank
    """
    ini_key, env_var = KEYS[ name ]
    env_value        = environ.get( env_var, "" ).strip()
    if env_value: return env_value, True
    manager = config if config is not None else build_config()
    value   = manager.get( ini_key, silent=True )
    value   = "" if value is None else str( value ).strip()
    if value: return value, False
    code = DEPENDENCY_MISSING if name == "interpreter" else STORAGE_KEY_MISSING
    raise CandidateError( code, f"the INI key '{ini_key}' is missing or empty and {env_var} is not set" )


def data_subdir( config=None, environ=None ):
    """
    Return the reuse-review data directory name, relative to the fleet data root.

    Requires:
        - config is a ConfigurationManager, or None to build one
        - environ is a mapping, or None for os.environ

    Ensures:
        - returns the override variable's value when set, else the INI value

    Raises:
        - CandidateError STORAGE_KEY_MISSING when neither is set
    """
    return _read( "data_subdir", config, os.environ if environ is None else environ )[ 0 ]


def candidate_dir( name, data_directory, config=None, environ=None ):
    """
    Return one candidate directory: vectors, query_cache or purpose.

    Requires:
        - name is one of "vectors", "query_cache" and "purpose"
        - data_directory is the data directory that paths.data_dir returned

    Ensures:
        - an override variable is an absolute path and is returned as it is
        - an INI value is relative to data_directory

    Raises:
        - CandidateError STORAGE_KEY_MISSING when the key is absent, or an override is not absolute
    """
    value, from_env = _read( name, config, os.environ if environ is None else environ )
    if not from_env: return pathlib.Path( data_directory ) / value
    if not pathlib.PurePath( value ).is_absolute():
        raise CandidateError( STORAGE_KEY_MISSING, f"{KEYS[ name ][ 1 ]} must be an absolute path, got {value!r}" )
    return pathlib.Path( value )


def search_interpreter( config=None, environ=None ):
    """
    Return the interpreter that runs the search process.

    Ensures:
        - returns the path as a string, from the override variable or the INI key
        - the file is checked to exist

    Raises:
        - CandidateError DEPENDENCY_MISSING when the key is absent or the file is not there
    """
    value = _read( "interpreter", config, os.environ if environ is None else environ )[ 0 ]
    if not pathlib.Path( value ).is_file():
        raise CandidateError( DEPENDENCY_MISSING, f"the search interpreter {value!r} is not a file" )
    return value
