"""
Merge the rotated judge ledgers into the daily ledger, so their rulings count again.

A rotation renamed the daily ledger aside when the Claude Code version changed. This reads those files and copies their rulings into the live ledger.
"""
import pathlib
import re

from cosa.repo.doc_lint import harness_runner
from cosa.repo.duplicate_check.proof import proof_cli

ROTATED_GLOB = "judge-ledger.*.jsonl"
VERSION      = re.compile( r"version=(\d+(?:\.\d+)*)" )


def version_of( binding ):
    """
    Read the Claude Code version out of a ledger binding.

    Requires:
        - binding is a ledger binding string, or None
    Ensures:
        - returns the version as a tuple of integers, or an empty tuple when there is none, so a file with no binding sorts first
    """
    found = VERSION.search( binding or "" )
    return tuple( int( n ) for n in found.group( 1 ).split( "." ) ) if found else ()


def strip_version( binding ):
    """
    Remove the Claude Code version from a ledger binding.

    Requires:
        - binding is a ledger binding string, or None
    Ensures:
        - returns the binding as the daily ledger binds it, with the binary path, backend and server and no version; None gives None
    """
    return None if binding is None else proof_cli._VERSION.sub( "", binding )


def rotated_files( folder ):
    """
    List the rotated ledgers beside the live one, oldest version first.

    Requires:
        - folder is the daily check's data folder
    Ensures:
        - returns the paths of judge-ledger.<version>.jsonl files in order of the version in their binding, then by name; the live ledger is never listed
    """
    found = [ p for p in pathlib.Path( folder ).glob( ROTATED_GLOB ) if p.name != proof_cli.LEDGER_NAME ]
    return sorted( found, key=lambda p: ( version_of( harness_runner.Ledger( p ).recorded ), p.name ) )


def merge_rotated( folder, apply=False ):
    """
    Copy each ruling the rotated ledgers hold and the live ledger lacks into the live ledger.

    Requires:
        - folder holds the live judge-ledger.jsonl, bound as the daily run binds it
        - apply is False for a count that writes nothing, or True to append

    Ensures:
        - never reads a rotated file for writing, and never renames, rewrites or removes one
        - a key the live ledger already holds is left as it is; a key several rotated files hold takes the value of the newest version
        - a rotated file bound to another binary, backend or server than the live ledger, or bound to nothing, is refused before anything is written
        - a copied ruling keeps its key, so its model id is kept, and is stamped "cli" with the version of the file it came from
        - returns { files, entries, distinct, added, already_held, conflicts, models }: conflicts is the keys whose value differs between files, models counts the added keys per model id
        - with apply False the live file is not touched; a second apply adds nothing

    Raises:
        - LedgerBindingError when the live ledger has no binding, or a rotated file's binding differs from it in more than the version
    """
    folder = pathlib.Path( folder )
    live   = proof_cli.StampedLedger( folder / proof_cli.LEDGER_NAME, "" )
    base   = strip_version( live.recorded )
    for path in rotated_files( folder ):
        held = harness_runner.Ledger( path ).recorded
        if base is None or strip_version( held ) != base:
            raise harness_runner.LedgerBindingError( f"ledger {path} is bound to {held!r}, not the live ledger's {live.recorded!r} (version aside): it is not merged" )
    merged = {}
    seen   = 0
    clash  = set()
    for path in rotated_files( folder ):
        source = harness_runner.Ledger( path )
        stamp  = ".".join( str( n ) for n in version_of( source.recorded ) )
        seen  += len( source.entries )
        for key, value in source.entries.items():
            if key in merged and merged[ key ][ "value" ] != value: clash.add( key )
            merged[ key ] = { "value": value, "stamp": stamp, "timing": source.timing( key ) }
    held   = [ k for k in merged if k in live.entries ]
    added  = [ k for k in merged if k not in live.entries ]
    models = {}
    for key in added: models[ key.split( "|" )[ 4 ] ] = models.get( key.split( "|" )[ 4 ], 0 ) + 1
    if apply:
        for key in added:
            live.stamp = merged[ key ][ "stamp" ]
            live.put( key, merged[ key ][ "value" ], timing=merged[ key ][ "timing" ] )
    return { "files": len( rotated_files( folder ) ), "entries": seen, "distinct": len( merged ), "added": len( added ), "already_held": len( held ),
             "conflicts": len( clash ), "models": models }
