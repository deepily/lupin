"""
The launch preflight of a live need-set run, as a script step.

Two guards refused the first run launches before any model call, and the checklist around them was prose.
The index manifest hashes file times, so a tree touched after the last identity check fails with VECTORS_NOT_FROM_INDEX.
The spend ledger keeps a run name for good once an attempt began under it.
This step makes both mechanical.

The worktree janitor sweeps the run's source tree (needset-run-<sha>) when it has been idle for hours.
The launch then makes it again with git worktree add, which gives every tracked file a new time.
So the preflight makes and locks that same tree first and builds the index from it as the run will.
Only then does it read the identity, as its last step.
A tree it had to recreate is named in the refusal.

A run-command.sh calls it last, just before the python launch.
Give it the launch's own arguments.

    python -m lupin_mcp.reuse_needset.launch_preflight --live --root "$ROOT" --source-commit "$COMMIT" "$@"
It reads the run name and the vector folder from the variables run-env.sh sets.
"""
import argparse
import json
import os
import pathlib
import sys

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import freeze, source_at

RULE         = "A spend-ledger run name is consumed by the first attempt made under it, even one refused before any model call. The next attempt takes the next letter."
EXIT_REFUSED = 2
LETTERS      = "abcdefghijklmnopqrstuvwxyz"
REFUSALS     = ( er.RUN_NAME_CONSUMED, er.FREEZE_INCOMPLETE, er.VECTORS_NOT_FROM_INDEX )


def begun_run_names( ledger_file ):
    """
    Read every run name the spend ledger has a begin row for.

    Requires:
        - ledger_file is the ledger's path; the file is only read, never locked or written

    Ensures:
        - returns the set of run names with a begin row, closed or not
        - a missing file returns the empty set
        - a line that is not a JSON object is skipped; the ledger itself refuses such lines when a run begins
    """
    path = pathlib.Path( ledger_file )
    if not path.is_file(): return set()
    names = set()
    for line in path.read_text( encoding="utf-8" ).splitlines():
        try:
            row = json.loads( line )
        except ValueError:
            continue
        if isinstance( row, dict ) and row.get( "kind" ) == "begin" and isinstance( row.get( "run" ), str ): names.add( row[ "run" ] )
    return names


def next_run_name( name, begun ):
    """
    Letter a run name forward to the first name the ledger has not begun.

    Requires:
        - name is a non-empty string; begun is a collection of begun names

    Ensures:
        - a name ending in -<letter> steps to the next letter, past any that were begun
        - a name with no letter suffix is treated as -a and steps to -b
        - returns name itself when it is not begun
    Raises:
        - NeedsetError RUN_NAME_CONSUMED when the letters run out at z
    """
    if name not in begun: return name
    stem, _, tail = name.rpartition( "-" )
    if len( tail ) == 1 and tail in LETTERS: start = LETTERS.index( tail ) + 1
    else: stem, start = name, 1
    for letter in LETTERS[ start: ]:
        if f"{stem}-{letter}" not in begun: return f"{stem}-{letter}"
    raise er.NeedsetError( er.RUN_NAME_CONSUMED, f"no unused letter is left after {name!r}" )


def check_run_name( name, begun ):
    """
    Refuse a run name the ledger has already begun.

    Requires:
        - name is the run name the launch will use

    Ensures:
        - returns None when the name is unused
    Raises:
        - NeedsetError RUN_NAME_CONSUMED naming the next free name and carrying the rule
    """
    if not name: raise er.NeedsetError( er.RUN_NAME_CONSUMED, "no run name is set: LUPIN_REUSE_JEV_RUN_NAME is empty" )
    if name in begun:
        raise er.NeedsetError( er.RUN_NAME_CONSUMED, f"{name!r} already began in the spend ledger; the next free name is {next_run_name( name, begun )!r}. {RULE}" )


def preflight( run_name, ledger_file, vectors_dir, live=True, advance=False, tree_fn=None, index_fn=None, identity_fn=freeze.identity, unlock_fn=None ):
    """
    Run the guards of a live launch, the identity check last.

    Requires:
        - tree_fn() returns ( the run's source tree, True when this call had to make it ); the tree is left locked
        - index_fn( tree ) returns the index generation folder the run will read from that tree
        - identity_fn( index_gen, vectors_dir ) is freeze.identity or a stand-in; unlock_fn( tree ) unlocks a tree

    Ensures:
        - without live nothing is checked and no tree is touched: a plan-only run contacts no model and begins no ledger run
        - the run name is judged first; then the tree is made and locked, the index built from it, and the identity read as the final step
        - a consumed name with advance letters forward and the result carries run_name as the new name
        - any failure after the tree step, a crash included, unlocks the tree when this call made it, and re-raises
        - a tree that was already there is never unlocked, because a live run on the same commit may hold it
        - returns { live, run_name, identity, advanced_from, tree, tree_recreated }
    Raises:
        - NeedsetError RUN_NAME_CONSUMED for a consumed name without advance
        - NeedsetError FREEZE_INCOMPLETE and VECTORS_NOT_FROM_INDEX from the identity check; the second says when this call recreated the tree
    """
    if not live: return { "live": False, "run_name": run_name, "identity": None, "advanced_from": None, "tree": None, "tree_recreated": None }
    begun = begun_run_names( ledger_file )
    was   = None
    if advance and run_name in begun: run_name, was = next_run_name( run_name, begun ), run_name
    check_run_name( run_name, begun )
    tree, recreated = tree_fn()
    try:
        identity = identity_fn( index_fn( tree ), vectors_dir )
    except BaseException as e:
        if recreated and unlock_fn is not None: unlock_fn( tree )
        if isinstance( e, er.NeedsetError ) and e.code == er.VECTORS_NOT_FROM_INDEX and recreated:
            raise er.NeedsetError( e.code, f"{e.detail}. This launch had to make {tree} again, which moves every file time the index hashes: rebuild the vectors against it with rebuild_vectors, then relaunch" )
        raise
    return { "live": True, "run_name": run_name, "identity": identity, "advanced_from": was, "tree": str( tree ), "tree_recreated": recreated }


def source_tree_of( root, commit ):
    """
    Make and lock the run's source tree, saying whether it had to be made.

    Requires:
        - root is the lupin repository and commit a commit it holds

    Ensures:
        - returns ( the tree at the commit, locked, True when it did not exist before this call )
    """
    existed = source_at.worktree_path( root, commit ).exists()
    return source_at.ensure_worktree( root, commit ), not existed


def index_of( tree ):  # pragma: no cover -- builds the real index of a real tree; main's test replaces it
    """Ensures: returns the index generation of the tree, built when missing."""
    from cosa.repo.symindex import build as sx_build
    return sx_build.ensure( tree )


def parse_args( argv, environ ):
    """Ensures: returns the parsed command line, with run-env.sh values as defaults."""
    ap = argparse.ArgumentParser( description=__doc__, allow_abbrev=False )
    ap.add_argument( "--live", action="store_true", help="check for a live launch; without it nothing is checked" )
    ap.add_argument( "--advance", action="store_true", help="letter a consumed run name forward instead of refusing; prints RUN_NAME=<name>" )
    ap.add_argument( "--root", required=True )
    ap.add_argument( "--source-commit", default="", help="the commit of the run's source tree; required with --live" )
    ap.add_argument( "--run-name", default=environ.get( "LUPIN_REUSE_JEV_RUN_NAME", "" ) )
    ap.add_argument( "--vectors-dir", default=environ.get( "LUPIN_REUSE_CANDIDATE_VECTORS_DIR", "" ) )
    ap.add_argument( "--ledger" )
    args, _ = ap.parse_known_args( argv )
    return args


def main( argv=None, environ=None, out=sys.stdout, err=sys.stderr, identity_fn=freeze.identity, tree_fn=None, index_fn=index_of, unlock_fn=None ):
    """
    Run the preflight from a launch script.

    Requires:
        - argv is a list or None for sys.argv; arguments it does not know (the launch's own, such as --limit) are ignored

    Ensures:
        - tree_fn, index_fn and unlock_fn default to the real source tree of --source-commit under --root, the real index and git worktree unlock
        - returns 0 when every guard passed, and prints one JSON line; with --advance a changed name is also printed as RUN_NAME=<name>
        - returns EXIT_REFUSED after printing the code, the detail and, for a consumed name, the rule to err
    """
    environ = os.environ if environ is None else environ
    args    = parse_args( sys.argv[ 1: ] if argv is None else argv, environ )
    if args.ledger: ledger = args.ledger
    else:
        from lupin_mcp import reuse_ledger
        ledger = reuse_ledger.ledger_path( args.root )
    if args.live and not args.source_commit:
        print( "launch preflight REFUSED: a live launch needs --source-commit, the commit of the run's source tree", file=err )
        return EXIT_REFUSED
    tree_fn   = tree_fn or ( lambda: source_tree_of( args.root, args.source_commit ) )
    unlock_fn = unlock_fn or ( lambda tree: source_at.unlock( args.root, tree ) )
    try:
        got = preflight( args.run_name, ledger, args.vectors_dir, live=args.live, advance=args.advance, tree_fn=tree_fn, index_fn=index_fn, identity_fn=identity_fn, unlock_fn=unlock_fn )
    except er.NeedsetError as e:
        print( f"launch preflight REFUSED: {e}", file=err )
        return EXIT_REFUSED
    print( json.dumps( got, sort_keys=True ), file=out )
    if got[ "advanced_from" ] is not None:
        print( f"RUN_NAME={got[ 'run_name' ]}", file=out )
        print( RULE, file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover -- process entry point
    sys.exit( main() )
