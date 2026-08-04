#!/usr/bin/env python3
"""
Merge the portable Claude Code permission stanza into a machine's ~/.claude/settings.json.

WHY THIS EXISTS
    Rick's dev box grants a short list of bare tool names ( "Bash", "Read", "Write" — no
    parentheses, therefore no path ), three deny guards, and defaultMode "auto". The VM did
    not, so every session there stopped to ask. Copying the whole settings file is NOT the
    fix: it carries machine-specific "hooks", "env", "model" and "heartbeat" keys that a copy
    would clobber. So we ship the PERMISSIONS STANZA ONLY and MERGE it.

WHY THE SOURCE FILE LIVES OUTSIDE THE REPO
    Rick's ruling 2026-08-04: the permission list does not go in git. It lives at
    $DEEPILY_DATA_DIR/claude-permissions.json, and reaches the VM through
    src/conf/vm-unversioned-manifest.tsv — the registry of payloads git cannot deliver.

THE PORTABILITY GUARD
    A permission rule naming an absolute machine path is dead on any other machine: nothing
    expands $LUPIN_ROOT inside a permission pattern, and a "*" cannot rescue an absolute
    prefix. An earlier attempt shipped 96 such rules and they silently did nothing. So this
    script REFUSES a source file containing one, and names every offender. You find out at
    authoring time instead of months later.

USAGE
    python3 apply_claude_permissions.py                 # merge into $HOME/.claude/settings.json
    python3 apply_claude_permissions.py --dry-run       # report the delta, write nothing
    python3 apply_claude_permissions.py --verify        # exit 1 if the target is missing a rule
    python3 apply_claude_permissions.py --source X --target Y
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

# Absolute-path prefixes that cannot survive a hop to another machine. A rule containing one
# is rejected outright — see "THE PORTABILITY GUARD" above.
NON_PORTABLE_PREFIXES = ( "/mnt/", "/home/", "/Users/", "/var/", "/opt/", "/srv/" )

DEFAULT_SOURCE_BASENAME = "claude-permissions.json"
STANZA_KEYS             = ( "allow", "deny", "ask", "defaultMode" )


def default_source_path():
    """
    Resolve the source file from DEEPILY_DATA_DIR.

    Requires:
        - DEEPILY_DATA_DIR is set in the environment

    Ensures:
        - returns an absolute path to the permission file inside that directory

    Raises:
        - RuntimeError if DEEPILY_DATA_DIR is unset
    """
    data_dir = os.environ.get( "DEEPILY_DATA_DIR" )
    if not data_dir:
        raise RuntimeError(
            "DEEPILY_DATA_DIR is not set. Export it ( dev: ~/.bashrc; VM: shipped by "
            "`lupin-vm.sh push-env` ) or pass --source explicitly."
        )
    return os.path.join( data_dir, DEFAULT_SOURCE_BASENAME )


def default_target_path():
    """
    Ensures:
        - returns the current user's Claude Code user-level settings path
    """
    return os.path.join( os.path.expanduser( "~" ), ".claude", "settings.json" )


def find_non_portable( rules ):
    """
    Identify rules carrying a machine-specific absolute path.

    Requires:
        - rules is an iterable of strings

    Ensures:
        - returns the subset whose text contains any NON_PORTABLE_PREFIXES entry,
          preserving input order
    """
    return [ r for r in rules if any( p in r for p in NON_PORTABLE_PREFIXES ) ]


def load_stanza( source_path ):
    """
    Read and validate the portable permission stanza.

    Requires:
        - source_path names a readable JSON file with a "permissions" object

    Ensures:
        - returns a dict holding only STANZA_KEYS present in the source
        - every allow/deny/ask rule is portable

    Raises:
        - FileNotFoundError if source_path does not exist
        - ValueError if "permissions" is missing, or any rule is non-portable
    """
    with open( source_path ) as fh:
        doc = json.load( fh )

    if "permissions" not in doc:
        raise ValueError( f"{source_path}: no 'permissions' object — nothing to merge" )

    perms  = doc[ "permissions" ]
    stanza = { k: perms[ k ] for k in STANZA_KEYS if k in perms }

    offenders = []
    for key in ( "allow", "deny", "ask" ):
        offenders.extend( find_non_portable( stanza.get( key, [] ) ) )

    if offenders:
        listed = "\n".join( f"    {r}" for r in offenders )
        raise ValueError(
            f"{source_path}: {len( offenders )} rule(s) name a machine-specific absolute "
            f"path and cannot travel to another host:\n{listed}\n"
            "  Nothing expands $LUPIN_ROOT inside a permission pattern, and '*' cannot "
            "rescue an absolute prefix. Use a bare tool name ( e.g. \"Read\" ) or a "
            "relative pattern instead."
        )

    return stanza


def compute_merge( target_doc, stanza ):
    """
    Compute the merged permissions block without touching disk.

    Requires:
        - target_doc is a dict ( the parsed target settings file )
        - stanza is the validated portable stanza

    Ensures:
        - returns ( merged_permissions, delta ) where delta names what would change
        - existing target rules are preserved; stanza rules are appended if absent
        - defaultMode is overwritten only when the stanza specifies it
        - every key of target_doc outside "permissions" is left for the caller, untouched
    """
    current = dict( target_doc.get( "permissions", {} ) )
    delta   = { "added": {}, "mode": None }

    for key in ( "allow", "deny", "ask" ):
        if key not in stanza:
            continue
        existing = list( current.get( key, [] ) )
        added    = [ r for r in stanza[ key ] if r not in existing ]
        current[ key ] = existing + added
        if added: delta[ "added" ][ key ] = added

    if "defaultMode" in stanza and current.get( "defaultMode" ) != stanza[ "defaultMode" ]:
        delta[ "mode" ] = ( current.get( "defaultMode" ), stanza[ "defaultMode" ] )
        current[ "defaultMode" ] = stanza[ "defaultMode" ]

    return current, delta


def missing_rules( target_doc, stanza ):
    """
    Report which stanza rules the target does NOT carry — the --verify oracle.

    Requires:
        - target_doc is a dict, stanza is the validated portable stanza

    Ensures:
        - returns a list of human-readable strings, empty when the target is in sync
    """
    current = target_doc.get( "permissions", {} )
    gaps    = []

    for key in ( "allow", "deny", "ask" ):
        for rule in stanza.get( key, [] ):
            if rule not in current.get( key, [] ):
                gaps.append( f"{key}: {rule}" )

    if "defaultMode" in stanza and current.get( "defaultMode" ) != stanza[ "defaultMode" ]:
        gaps.append( f"defaultMode: expected {stanza['defaultMode']!r}, "
                     f"found {current.get( 'defaultMode' )!r}" )

    return gaps


def apply( source_path, target_path, dry_run=False, verify=False, now=None ):
    """
    Merge the stanza at source_path into the settings file at target_path.

    Requires:
        - source_path is a readable portable-stanza file
        - target_path is a readable JSON settings file

    Ensures:
        - verify mode writes nothing and returns 0 in sync, 1 when rules are missing
        - dry-run writes nothing and returns 0
        - otherwise the target is backed up, merged, and re-parsed to prove valid JSON
        - keys of the target outside "permissions" are byte-identical afterwards
        - returns a process exit code

    Raises:
        - FileNotFoundError, ValueError from load_stanza on a bad source
    """
    stanza = load_stanza( source_path )

    with open( target_path ) as fh:                 # parse BEFORE backing up — never back up
        target_doc = json.load( fh )                # a file we could not read in the first place

    if verify:
        gaps = missing_rules( target_doc, stanza )
        if gaps:
            print( f"OUT OF SYNC: {target_path} is missing {len( gaps )} rule(s):" )
            for g in gaps: print( f"    {g}" )
            return 1
        print( f"IN SYNC: {target_path} carries every rule from {source_path}" )
        return 0

    merged, delta = compute_merge( target_doc, stanza )
    untouched     = [ k for k in target_doc if k != "permissions" ]

    if not delta[ "added" ] and delta[ "mode" ] is None:
        print( f"NO CHANGE: {target_path} already carries every rule from {source_path}" )
        return 0

    for key, added in delta[ "added" ].items():
        print( f"{key.upper():<12} +{len( added )}: {added}" )
    if delta[ "mode" ]:
        print( f"{'DEFAULTMODE':<12} {delta['mode'][0]!r} -> {delta['mode'][1]!r}" )

    if dry_run:
        print( "DRY RUN: nothing written" )
        return 0

    stamp  = ( now or datetime.now() ).strftime( "%Y%m%d-%H%M%S" )
    backup = f"{target_path}.bak-{stamp}"
    shutil.copy2( target_path, backup )

    target_doc[ "permissions" ] = merged
    with open( target_path, "w" ) as fh:
        json.dump( target_doc, fh, indent=2 )

    with open( target_path ) as fh:                 # re-parse: prove we wrote valid JSON
        json.load( fh )

    print( f"BACKUP       {backup}" )
    print( f"UNTOUCHED    {untouched}" )
    print( "NOTE         Claude Code loads settings at STARTUP — restart any running "
           "session to pick this up." )
    return 0


def main( argv=None ):
    """
    Ensures:
        - parses argv, runs apply(), and returns a process exit code
        - a bad source or unreadable target reports the reason and returns 2
    """
    ap = argparse.ArgumentParser( description=__doc__.split( "\n" )[ 1 ] )
    ap.add_argument( "--source", default=None,
                     help="portable stanza file ( default: $DEEPILY_DATA_DIR/claude-permissions.json )" )
    ap.add_argument( "--target", default=None,
                     help="settings file to merge into ( default: ~/.claude/settings.json )" )
    ap.add_argument( "--dry-run", action="store_true", help="report the delta, write nothing" )
    ap.add_argument( "--verify",  action="store_true", help="exit 1 if the target is missing a rule" )
    args = ap.parse_args( argv )

    try:
        source = args.source or default_source_path()
        target = args.target or default_target_path()
        return apply( source, target, dry_run=args.dry_run, verify=args.verify )
    except ( RuntimeError, ValueError, FileNotFoundError, json.JSONDecodeError ) as e:
        print( f"ERROR: {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":
    sys.exit( main() )
