"""
Per-repo code-health settings, read from Lupin's INI through ConfigurationManager.

Each setting is a key named on the pattern `external repo <name> <kind>`, plus one global key for the data subdirectory.
A blank detection key means detect. The ceiling and the Jev token limit have no code default and are refused when blank.
Every bad value raises CodeHealthSettingError, and the message names the key.

Usage:
    from cosa.repo import code_health_settings as chs
    settings = chs.repo_settings( config_mgr, "lupin" )
"""
import contextlib
import pathlib
import re
import sys

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
from cosa.utils.csv_text import split_csv

LANGUAGES_KIND   = "index languages"
SOURCE_DIRS_KIND = "index source dirs"
TEST_DIRS_KIND   = "index test dirs"
EXCLUDE_KIND     = "index exclude"
WIKI_DIR_KIND    = "wiki dir"
TITLE_KIND       = "filed title prefix"
CEILING_KIND     = "duplicate check ceiling"
JEV_LIMIT_KIND   = "jev token limit"
PER_REPO_KINDS   = ( LANGUAGES_KIND, SOURCE_DIRS_KIND, TEST_DIRS_KIND, EXCLUDE_KIND, WIKI_DIR_KIND, TITLE_KIND, CEILING_KIND, JEV_LIMIT_KIND )
CHECKOUT_PATH_WORD = "path"
DATA_SUBDIR_KEY  = "code health data subdir"
DATA_SUBDIR      = "code-health"
LANGUAGES        = ( "py", "ts", "dart" )
DEFAULT_REPO     = "lupin"
WHOLE_NUMBER     = re.compile( r"[0-9]+" )
ONE_TOKEN        = re.compile( r"\S+" )
JUDGE_MODEL_KEY   = "duplicate check judge model"
REWRITE_MODEL_KEY = "duplicate check proof rewrite model"
DRAFTER_MODEL_KEY = "reuse need drafter model"
ALIKE_MODEL_KEY   = "duplicate check proof alike model"
NEED_WRITER_MODEL_KEY = "symindex need writer model"
SECOND_MODEL_KEY  = "reuse need second model"


class CodeHealthSettingError( ValueError ):
    """Raised when a code-health key holds a value the reader refuses; the message names the key."""


def repo_key( name, kind ):
    """
    Build the INI key of one per-repo setting.

    Requires:
        - name is a repo name from `external repos`
        - kind is one of the eight per-repo kinds

    Ensures:
        - returns `external repo <name> <kind>`
    """
    return f"external repo {name} {kind}"


def read_text( config, key ):
    """
    Read one key as stripped text.

    Requires:
        - config has a ConfigurationManager `get` method

    Ensures:
        - returns the stripped value, or an empty string when the key is absent or blank
        - an absent key prints no splainer text
    """
    return str( config.get( key, default="", silent=True ) ).strip()


def read_entries( config, key ):
    """
    Read one key as a comma-separated list.

    Ensures:
        - returns the stripped, non-empty entries in file order
        - a blank or absent key returns an empty list
    """
    return split_csv( read_text( config, key ) )


def read_positive_int( config, key ):
    """
    Read one key as a positive whole number.

    Ensures:
        - returns the number as an int, at least 1

    Raises:
        - CodeHealthSettingError naming the key when the value is blank, absent, zero, negative or not a whole number
    """
    text = read_text( config, key )
    if WHOLE_NUMBER.fullmatch( text ) is None or int( text ) < 1:
        raise CodeHealthSettingError( f"{key}: {text!r} is not a positive whole number; this key has no default" )
    return int( text )


def check_relative( key, entry ):
    """
    Refuse a path that is absolute or climbs out of the repo root.

    Ensures:
        - returns the entry when it is a relative path with no `..` part

    Raises:
        - CodeHealthSettingError naming the key for an absolute path or a `..` part
    """
    path = pathlib.PurePosixPath( entry )
    if path.is_absolute() or ".." in path.parts:
        raise CodeHealthSettingError( f"{key}: {entry!r} must be a path relative to the repo root, with no `..`" )
    return entry


def index_languages( config, name ):
    """
    Read the languages the index covers.

    Ensures:
        - returns a list of entries from py, ts and dart, or an empty list, which means detection

    Raises:
        - CodeHealthSettingError naming the key for an entry outside py, ts and dart
    """
    key     = repo_key( name, LANGUAGES_KIND )
    entries = read_entries( config, key )
    for entry in entries:
        if entry not in LANGUAGES: raise CodeHealthSettingError( f"{key}: {entry!r} is not one of {', '.join( LANGUAGES )}" )
    return entries


def relative_paths( config, name, kind ):
    """
    Read a list of repo-relative directories, for the source or test dirs.

    Ensures:
        - returns the entries, or an empty list, which means detection

    Raises:
        - CodeHealthSettingError naming the key for an absolute entry or one with `..`
    """
    key = repo_key( name, kind )
    return [ check_relative( key, entry ) for entry in read_entries( config, key ) ]


def index_exclude( config, name ):
    """
    Read the directory names the index skips.

    Ensures:
        - returns the entries, or an empty list, which means the built-in skip names
        - an entry is a bare directory name

    Raises:
        - CodeHealthSettingError naming the key for an entry that holds a path separator
    """
    key     = repo_key( name, EXCLUDE_KIND )
    entries = read_entries( config, key )
    for entry in entries:
        if "/" in entry or "\\" in entry: raise CodeHealthSettingError( f"{key}: {entry!r} is a path; give directory names only" )
    return entries


def wiki_dir( config, name ):
    """
    Read the wiki directory, relative to the repo root.

    Ensures:
        - returns the relative path, or None, which means the librarian derives `<root>/src/docs/wiki`

    Raises:
        - CodeHealthSettingError naming the key for an absolute path or one with `..`
    """
    key  = repo_key( name, WIKI_DIR_KIND )
    text = read_text( config, key )
    return check_relative( key, text ) if text else None


def filed_title_prefix( config, name ):
    """
    Read the prefix of a filed row's title.

    Ensures:
        - returns the configured text, or `[<NAME>]` with the name upper-cased when the key is blank or absent
    """
    return read_text( config, repo_key( name, TITLE_KIND ) ) or f"[{name.upper()}]"


def duplicate_check_ceiling( config, name ):
    """
    Read the most judge calls one duplicate-check run may make.

    Ensures:
        - returns a positive int

    Raises:
        - CodeHealthSettingError naming the key when the value is blank, absent or not a positive whole number
    """
    return read_positive_int( config, repo_key( name, CEILING_KIND ) )


def jev_token_limit( config, name ):
    """
    Read the repo's Jev token limit.

    Ensures:
        - returns a positive int

    Raises:
        - CodeHealthSettingError naming the key when the value is blank, absent or not a positive whole number
    """
    return read_positive_int( config, repo_key( name, JEV_LIMIT_KIND ) )


def model_id( key, config=None ):
    """
    Read the model id one code-health caller sends its prompts to.

    Requires:
        - key is the INI key of a model id: one of this module's *_MODEL_KEY names, or another service's key, such as the notification proxy's fallback model
        - config has a ConfigurationManager `get` method, or is None to build the process's own

    Ensures:
        - returns the stripped value of the key, read when called through ConfigurationManager.get_required, so an INI edit needs no code change
        - there is no default in code: the INI file is the only place a model id is set
        - building the process's own manager writes its start-up banner to stderr, never stdout, because the callers'
          command-line tools print their result as JSON on stdout

    Raises:
        - CodeHealthSettingError naming the key when the value is blank, absent or holds white space
    """
    from cosa.config.configuration_manager import ConfigurationManager, MissingConfigKeyError
    if config is None:
        with contextlib.redirect_stdout( sys.stderr ): config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    try:
        text = str( config.get_required( key, silent=True ) ).strip()
    except MissingConfigKeyError as error:
        raise CodeHealthSettingError( f"{key}: {error}; this key has no default and lives only in lupin-app.ini" ) from error
    if ONE_TOKEN.fullmatch( text ) is None:
        raise CodeHealthSettingError( f"{key}: {text!r} is not one model id; this key has no default and lives only in lupin-app.ini" )
    return text


def data_subdir( config ):
    """
    Read the leaf folder under the fleet data root that holds code-health data.

    Ensures:
        - returns the configured name, or `code-health` when the key is blank or absent
        - the name is one path component, never a path

    Raises:
        - CodeHealthSettingError naming the key for a name with a separator, `.` or `..`
    """
    text = read_text( config, DATA_SUBDIR_KEY ) or DATA_SUBDIR
    if "/" in text or "\\" in text or text in ( ".", ".." ):
        raise CodeHealthSettingError( f"{DATA_SUBDIR_KEY}: {text!r} must be one folder name, not a path" )
    return text


def data_dir( root=None, config=None ):
    """
    Resolve the folder that holds one repo's code-health data.

    Requires:
        - root is the repo checkout, or None for the project root
        - config has a ConfigurationManager `get` method, or None to build the process's own

    Ensures:
        - returns `<fleet_data_root( root )>/<code health data subdir>` as a Path, outside the repo tree
        - never returns a path under the checkout's `io/` folder

    Raises:
        - CodeHealthSettingError naming the key when the subdir is a path
    """
    if config is None:
        from cosa.config.configuration_manager import ConfigurationManager
        config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    return fleet_data_root( root ) / data_subdir( config )


def repo_settings( config, name ):
    """
    Read every per-repo setting for one repo.

    Ensures:
        - returns a dict with one entry per detection or text kind, under the kind's name with spaces as underscores
        - the ceiling and the Jev limit are not read here, because a repo may run without either

    Raises:
        - CodeHealthSettingError naming the key for the first bad value
    """
    return { "index_languages": index_languages( config, name ), "index_source_dirs": relative_paths( config, name, SOURCE_DIRS_KIND ),
             "index_test_dirs": relative_paths( config, name, TEST_DIRS_KIND ), "index_exclude": index_exclude( config, name ),
             "wiki_dir": wiki_dir( config, name ), "filed_title_prefix": filed_title_prefix( config, name ) }


def repo_of( job ):
    """
    Name the repo a registry job belongs to.

    Ensures:
        - returns the job's repo key, or lupin when it has none, so every row written before the key existed stays Lupin's
    """
    return job[ "repo" ] if "repo" in job else DEFAULT_REPO


def registry_repo_names( registry ):
    """
    List the repos that carry a row in the job registry.

    Requires:
        - registry is the dict cosa.rest.job_registry.load_registry returns, with a `jobs` list

    Ensures:
        - returns a sorted list of names: each job's `repo` value, or lupin for a job with no `repo` key
    """
    return sorted( { repo_of( job ) for job in registry[ "jobs" ] } )


def name_mismatches( checkouts ):
    """
    List repos whose registered name differs from their checkout's directory name.

    Requires:
        - checkouts maps a repo name to the path of its checkout

    Ensures:
        - returns a sorted list of names whose fleet data folder name is not the name
        - a worktree path counts as its main checkout, the rule fleet_data_root already uses
    """
    return sorted( name for name, path in checkouts.items() if fleet_data_root( path ).name != name )


def check_registry_names( registry, config ):
    """
    Refuse a registry whose repo names do not each equal their checkout's directory name.

    The data folder and the manager roster variable derive from the directory name. A row whose
    `repo` differs would read and write the wrong place. Only repos that carry a registry row are
    checked. The whole `external repos` list is not, because par-pacific and claude-plans differ from their directories.

    Requires:
        - registry is the dict cosa.rest.job_registry.load_registry returns
        - config has a ConfigurationManager `get` method, and each row's repo has `external repo <name> path`

    Ensures:
        - returns the sorted repo names that carry a row, at least one, when every name matches
        - a repo with no path key counts as failing, because its checkout cannot be compared

    Raises:
        - CodeHealthSettingError when the registry names no repo, so the check never passes on nothing
        - CodeHealthSettingError naming every repo whose name differs from its checkout's directory name or has no path
    """
    names = registry_repo_names( registry )
    if not names: raise CodeHealthSettingError( "the registry names no repo, so the directory-name check would pass on nothing" )
    paths   = { name: read_text( config, repo_key( name, CHECKOUT_PATH_WORD ) ) for name in names }
    missing = [ name for name, path in paths.items() if path == "" ]
    failing = sorted( missing + name_mismatches( { name: path for name, path in paths.items() if path != "" } ) )
    if failing: raise CodeHealthSettingError( f"repo name must equal its checkout's directory name; failing: {', '.join( failing )}" )
    return names
