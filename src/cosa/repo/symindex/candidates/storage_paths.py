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
    "interpreter"  : ( "reuse candidate search interpreter",    "LUPIN_REUSE_CANDIDATE_INTERPRETER" ),
    "handoff"      : ( "reuse candidate purpose handoff subdir",   "LUPIN_REUSE_CANDIDATE_HANDOFF_DIR" ),
    "container_root" : ( "reuse candidate container root",         "LUPIN_REUSE_CANDIDATE_CONTAINER_ROOT" )
}
HANDOFF_NOT_IN_CONTAINER = "HANDOFF_NOT_IN_CONTAINER"
ARM_KEY                  = ( "reuse candidate shortlist arm", "LUPIN_REUSE_CANDIDATE_ARM" )      # not in the key table: a blank value means the shipped default, never an error


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


def main_checkout( root ):
    """
    Return the main checkout of the repository that root belongs to.

    Requires:
        - root is a repository root or a worktree of one

    Ensures:
        - a worktree resolves to its parent checkout, the tree the containers mount
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _main_repo_path
    return pathlib.Path( _main_repo_path( pathlib.Path( root ) ) )


def handoff_dir( root, config=None, environ=None ):
    """
    Return the folder where the purpose-line job's request and response files are exchanged.

    Requires:
        - root is a repository root or a worktree of one

    Ensures:
        - an override variable is an absolute path and is returned as it is
        - an INI value is relative to the main checkout, so the containers can see it

    Raises:
        - CandidateError STORAGE_KEY_MISSING when the key is absent, or an override is not absolute
    """
    value, from_env = _read( "handoff", config, os.environ if environ is None else environ )
    if not from_env: return main_checkout( root ) / value
    if not pathlib.PurePath( value ).is_absolute():
        raise CandidateError( STORAGE_KEY_MISSING, f"{KEYS[ 'handoff' ][ 1 ]} must be an absolute path, got {value!r}" )
    return pathlib.Path( value )


def container_path( host_path, root, config=None, environ=None ):
    """
    Translate a host path under the main checkout to the path the container sees.

    Requires:
        - host_path is a path under the main checkout of root

    Ensures:
        - returns the container root joined to the path relative to the main checkout, as a string

    Raises:
        - CandidateError HANDOFF_NOT_IN_CONTAINER when host_path is outside the main checkout
        - CandidateError STORAGE_KEY_MISSING when the container root key is absent
    """
    container_root = _read( "container_root", config, os.environ if environ is None else environ )[ 0 ]
    main           = main_checkout( root )
    try:
        rel = pathlib.Path( host_path ).relative_to( main )
    except ValueError:
        raise CandidateError( HANDOFF_NOT_IN_CONTAINER, f"{host_path} is outside {main}, which is what the container mounts" )
    return str( pathlib.PurePosixPath( container_root ) / rel.as_posix() )


def shortlist_arm( default, config=None, environ=None ):
    """
    Return the shortlist search arm the shipped stage runs.

    Requires:
        - default is the arm name to use when neither source names one

    Ensures:
        - returns the override variable's value when set and not blank, else the INI value when not blank, else default
        - the name is stripped and not checked here: the stage refuses an unknown arm

    Raises:
        - CandidateError DEPENDENCY_MISSING when the INI has to be read and no manager can be built
    """
    environ   = os.environ if environ is None else environ
    env_value = environ.get( ARM_KEY[ 1 ], "" ).strip()
    if env_value: return env_value
    manager = config if config is not None else build_config()
    value   = manager.get( ARM_KEY[ 0 ], silent=True )
    value   = "" if value is None else str( value ).strip()
    return value if value else default
