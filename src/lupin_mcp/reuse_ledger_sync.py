"""
Write a repo's Jev ledger limit from its INI key, and fail loud when the two differ.

The key `external repo <name> jev token limit` is the single source of a repo's Jev limit.
The sync writes the ledger's latest limit row from it, never by hand.
The drift check compares the two at the start of a Jev run.
Nothing here sends anything.

Usage:
    python -m lupin_mcp.reuse_ledger_sync sync  --repo lupin --by <who> --why <reason>
    python -m lupin_mcp.reuse_ledger_sync check --repo lupin
"""
import argparse
import sys

from cosa.repo import code_health_settings as chs
from lupin_mcp import reuse_ledger as rl

CREATED   = "created"
SET       = "set"
UNCHANGED = "unchanged"
EXIT_OK   = 0
EXIT_DRIFT = 1
EXIT_REFUSED = 2
PATH_KIND = "path"


class LedgerDrift( Exception ):
    """The ledger's latest limit row differs from the INI key; no Jev run may start."""


def check_drift( ledger, key_tokens, key ):
    """
    Compare the ledger's latest limit row with the INI key's value.

    Requires:
        - ledger is an AccountLedger; key_tokens is the int the key holds; key names the key for the message
    Ensures:
        - returns None when the two are equal
    Raises:
        - LedgerDrift naming the key, both numbers and the sync command when they differ
        - LedgerUnreadable from the ledger when it is missing, damaged or has no limit row
    """
    limit = ledger.limit_tokens()
    if limit != key_tokens:
        raise LedgerDrift( f"{key} says {key_tokens} but the ledger {ledger.path} holds {limit}; run python -m lupin_mcp.reuse_ledger_sync sync" )


def sync( path, key_tokens, by, why ):
    """
    Make the ledger's latest limit row equal the key.

    Requires:
        - key_tokens is a positive int; by and why say who ran it and for what reason
    Ensures:
        - a missing ledger is created with the limit, and the created outcome is returned
        - a ledger whose limit differs gets a new limit row, and the set outcome is returned
        - a ledger whose limit already equals the key is left untouched, and the unchanged outcome is returned
    Raises:
        - LedgerUnreadable when the existing file is damaged or has no limit row
    """
    ledger = rl.AccountLedger( path )
    if not ledger.path.exists():
        rl.AccountLedger.create( path, key_tokens, by, why )
        return CREATED
    if ledger.limit_tokens() == key_tokens: return UNCHANGED
    ledger.set_limit( key_tokens, by, why )
    return SET


def repo_root( config, name ):
    """
    Find the checkout root of a registered repo.

    Ensures:
        - lupin resolves to the project root; any other repo to its `external repo <name> path` key
    Raises:
        - CodeHealthSettingError naming the key when another repo's path key is blank or absent
    """
    if name == chs.DEFAULT_REPO:
        import cosa.utils.util as cu
        return cu.get_project_root()
    key  = chs.repo_key( name, PATH_KIND )
    path = chs.read_text( config, key )
    if not path: raise chs.CodeHealthSettingError( f"{key} is blank, so the ledger of {name} cannot be located" )
    return path


def check_repo( config, name, path=None ):
    """
    Run the drift check for one repo at the start of a Jev run.

    Requires:
        - config is a ConfigurationManager; path is a ledger file, or None for the repo's own
    Ensures:
        - returns None when the key and the ledger agree
    Raises:
        - CodeHealthSettingError naming the key when the key is blank or bad
        - LedgerDrift or LedgerUnreadable as check_drift does
    """
    key    = chs.repo_key( name, chs.JEV_LIMIT_KIND )
    tokens = chs.jev_token_limit( config, name )
    check_drift( rl.AccountLedger( path or rl.ledger_path( repo_root( config, name ) ) ), tokens, key )


def main( argv=None, config=None ):
    """
    Run sync or check from the command line.

    Ensures:
        - returns EXIT_OK when done, EXIT_DRIFT when check finds a difference, EXIT_REFUSED when the key, path or ledger is unusable
        - prints one line saying what happened
    """
    from cosa.config.configuration_manager import ConfigurationManager
    parser = argparse.ArgumentParser( description="Sync or check a repo's Jev ledger limit against its INI key" )
    parser.add_argument( "command", choices=( "sync", "check" ) )
    parser.add_argument( "--repo", default=chs.DEFAULT_REPO )
    parser.add_argument( "--ledger", default=None, help="ledger file; default is the repo's own" )
    parser.add_argument( "--by", default="reuse_ledger_sync" )
    parser.add_argument( "--why", default="synced from the INI key" )
    args   = parser.parse_args( argv )
    config = config or ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    try:
        if args.command == "check":
            check_repo( config, args.repo, args.ledger )
            print( f"ok: the ledger limit of {args.repo} equals its INI key" )
            return EXIT_OK
        tokens = chs.jev_token_limit( config, args.repo )
        path   = args.ledger or rl.ledger_path( repo_root( config, args.repo ) )
        print( f"{sync( path, tokens, args.by, args.why )}: {path} limit {tokens}" )
        return EXIT_OK
    except LedgerDrift as e:
        print( f"DRIFT: {e}", file=sys.stderr )
        return EXIT_DRIFT
    except ( chs.CodeHealthSettingError, rl.LedgerUnreadable, ValueError ) as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit( main() )
