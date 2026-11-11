"""
One-off repair of the shadow audit's queue, after the daily check began queuing index ids.

Items queued before commit cd70b6dab carry the daily check's own "d-" id as exclude_id.
The sweep's index does not know that id, so each drain refuses the item as UNKNOWN_ENTRY and drops it on the third try.
This script is told what to do with every such item.
The flag --code takes d-id=file:name and rewrites that item to the index id of the definition.
The flag --drop takes a d- id and removes that item, and the --reason given is logged.
It lists the plan and changes nothing unless --apply is given.
An item whose d- id is in neither list stops the whole run.

Exit 0 means the plan was listed or applied. Exit 3 means it was refused and nothing was changed.
"""
import argparse
import datetime
import json
import os
import pathlib
import sys

from cosa.repo.symindex.candidates import shadow_audit as sa
from lupin_mcp import duplicate_check_audit as audit

EXIT_REFUSED = 3
LOG_NAME     = "shadow-pending-reid.log"


class ReidRefused( ValueError ):
    """A plan that was not made or not applied, with the reason in the message."""


def read_items( folder ):
    """
    Read every queue item in the folder.

    Requires:
        - folder is the shadow-pending folder
    Ensures:
        - returns [ ( path, item ) ] sorted by file name, for each *.json file
    Raises:
        - ReidRefused when a file is not a queue item, so a corrupt file is never skipped over
    """
    items = []
    for path in sorted( pathlib.Path( folder ).glob( "*.json" ) ):
        try: item = json.loads( path.read_text( encoding="utf-8" ) )
        except ValueError: item = None
        if not sa._item_ok( item ): raise ReidRefused( f"{path.name} is not a queue item" )
        items.append( ( path, item ) )
    return items


def make_plan( items, code, drop, entries ):
    """
    Decide what happens to each item.

    Requires:
        - code maps a d- id to ( file, name ); drop is a set of d- ids
        - entries are the index records, each with id, file, name and line
    Ensures:
        - returns one { path, id, old, action, new } for each item: action is "rewrite" with new the index id, or "remove" with new None
        - the definition named must be held by the index exactly once by file and name, so no line is guessed
    Raises:
        - ReidRefused for an item whose exclude_id is in neither list, one in both, one that is not a d- id, or a definition the index does not hold once
    """
    plan = []
    for path, item in items:
        old = item[ "exclude_id" ]
        if old is None or not old.startswith( "d-" ): raise ReidRefused( f"{path.name} has exclude_id {old!r}, which is not a d- id; nothing to repair" )
        if old in code and old in drop: raise ReidRefused( f"{old} is listed both as code and as dropped" )
        if old in drop: plan.append( { "path": path, "id": item[ "id" ], "old": old, "action": "remove", "new": None } ); continue
        if old not in code: raise ReidRefused( f"{path.name} (exclude_id {old}) is in neither --code nor --drop" )
        file, name = code[ old ]
        held       = [ e for e in entries if e[ "file" ] == file and e[ "name" ] == name ]
        if len( held ) != 1: raise ReidRefused( f"{file} {name} is held {len( held )} times by the index, not once" )
        plan.append( { "path": path, "id": item[ "id" ], "old": old, "action": "rewrite", "new": audit.index_id_finder( entries )( { "file": file, "name": name, "line": held[ 0 ][ "line" ] } ) } )
    return plan


def apply_plan( plan, items, reason, log_path, today ):
    """
    Carry out a plan and log each step.

    Ensures:
        - a rewritten item is a new file named by the queue's own id rule, with the new exclude_id and attempts 0, written whole; the old file is removed after it
        - a removed item's file is removed
        - one JSON line a step is appended to the log: the day, the action, the old and new ids, the item's file name and, for a removal, the reason
    """
    by_path = { path: item for path, item in items }
    with pathlib.Path( log_path ).open( "a", encoding="utf-8" ) as log:
        for step in plan:
            item = by_path[ step[ "path" ] ]
            line = { "day": today, "action": step[ "action" ], "old": step[ "old" ], "new": step[ "new" ], "file": step[ "path" ].name }
            if step[ "action" ] == "rewrite":
                key = sa._receipt_id( sa.need_hash( item[ "need" ] ), item[ "generation" ], item[ "index_sha" ], step[ "new" ] )
                new = { **item, "id": key, "exclude_id": step[ "new" ], "attempts": 0 }
                made = sa._write_once( step[ "path" ].with_name( f"{key}.json" ), json.dumps( new, sort_keys=True ) + "\n" )
                if not made: raise ReidRefused( f"{key}.json already exists; nothing more was changed" )   # pragma: no branch - the raise is exercised by the collision test; coverage does not record an exception leaving a with block
                line[ "new_file" ] = f"{key}.json"
            else: line[ "reason" ] = reason
            os.remove( step[ "path" ] )
            log.write( json.dumps( line, sort_keys=True ) + "\n" )


def parse_code( pairs ):
    """
    Read the --code pairs.

    Ensures:
        - returns { d- id: ( file, name ) } for each "d-id=file:name"
    Raises:
        - ReidRefused for a pair without that shape
    """
    out = {}
    for pair in pairs:
        left, _, right = pair.partition( "=" )
        file, _, name  = right.rpartition( ":" )
        if not left or not file or not name: raise ReidRefused( f"--code {pair!r} is not d-id=file:name" )
        out[ left ] = ( file, name )
    return out


def main( argv=None, out=None, entries_fn=None ):
    """
    List, or with --apply carry out, the repair of one shadow-pending folder.

    Requires:
        - entries_fn() returns the index records; None reads them from the lookup tool's own context (reuse_tools.prepare)
    Ensures:
        - without --apply nothing on disk changes and the plan is printed, one line an item
        - with --apply every step is logged beside the folder, and --reason is required when any item is removed
        - returns 0 for a listed or applied plan; 3 with the reason printed and nothing changed
    """
    ap = argparse.ArgumentParser( description="Re-id or remove the shadow audit's d- queue items." )
    ap.add_argument( "folder" )
    ap.add_argument( "--code", action="append", default=[], help="d-id=file:name, rewritten to the index id" )
    ap.add_argument( "--drop", action="append", default=[], help="d-id of an item to remove" )
    ap.add_argument( "--reason", default=None )
    ap.add_argument( "--apply", action="store_true" )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    try:
        items = read_items( a.folder )
        if a.drop and a.apply and not a.reason: raise ReidRefused( "--reason is required to remove items" )
        if entries_fn is None:
            from lupin_mcp import reuse_tools as rt
            entries_fn = lambda: rt.prepare( rt.context_from_environment() )[ 1 ]
        plan = make_plan( items, parse_code( a.code ), set( a.drop ), entries_fn() )
        for s in plan: print( f"{'APPLY' if a.apply else 'DRY-RUN'} {s[ 'path' ].name}: {s[ 'action' ]} {s[ 'old' ]} -> {s[ 'new' ]}", file=out )
        if a.apply:
            log_path = pathlib.Path( a.folder ).parent / "shadow-audit" / LOG_NAME
            log_path.parent.mkdir( parents=True, exist_ok=True )
            apply_plan( plan, items, a.reason, log_path, datetime.date.today().isoformat() )
    except ReidRefused as e:
        print( f"REFUSING: {e}. Nothing was changed.", file=out )
        return EXIT_REFUSED
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
