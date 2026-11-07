#!/usr/bin/env python3
"""
The merge-pyramid reuse gate: do the outcome lines a branch adds hold up?

It reads the lines a branch adds to Markdown files and judges each `REUSE-OUTCOME` line.
The checks are the reviewer's: shape, call log, token and kind pairing. Every line is recorded in refusals.jsonl.
Every new definition the branch adds must also have an outcome line. The list comes from git (the daily check's window and
changed files), or from a symbol index diff when one is given with --diff.
A branch that adds no definitions and no outcome lines passes. It sends nothing and runs no model.

The base is the merge base with the nearest of the branches in the key `reuse merge gate base`, else main and origin/main.
The key `reuse merge gate since`, a commit, moves the base up to it, so earlier lines and definitions are exempt.
A rename is followed: a function in a renamed file is new only when it is absent under the old path.

The flag `reuse review gating` is read fresh on every run:

    - false: refusals are reported under "Report-only" and the run exits 0.
    - true: any refusal or missing definition exits 1.

Exit 3 means the gate could not check. Either the flag is absent, doubled or garbled, or git named no base.
It also means the flag is true and `since` is empty, because the gate would then check every definition back to the base.
It also means `since` is not a known commit, the list of new definitions could not be built,
or a given diff reports `algorithm_changed`.
That is not a pass, in either phase.
The summary block (Total Tests, Passed, Failed, Errors) is the one the test-suite job reads.
Its unit is checks: one for the scan itself, one per outcome line, one per new definition in the diff.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

from cosa.repo.duplicate_check import errors as dc_errors
from cosa.repo.duplicate_check import extract
from cosa.repo.symindex import build, py_index, spec as sp
from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import fleet_cap_ini_io
from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_outcome as ro
from lupin_mcp import reuse_refusals as rr
from lupin_mcp import reuse_review_gate as gate
from lupin_mcp.reuse_needset import errors as needset_errors
from lupin_mcp.reuse_needset import source_at

WORKTREE_PREFIX  = "reuse-gate-"                                    # the detached worktrees of this gate, beside the daily check's
UNREADABLE       = ( OSError, ValueError, RuntimeError, SyntaxError, needset_errors.NeedsetError, dc_errors.DuplicateCheckError )     # what makes a run "could not check"
BASE_CANDIDATES  = ( "main", "origin/main" )                    # the branches a branch is merged into, when --base and the key `reuse merge gate base` are both absent
SINCE_KEY        = "reuse merge gate since"                  # a commit; only definitions and lines added after it are checked
BASE_KEY         = "reuse merge gate base"                   # the branches to measure from, separated by spaces; the nearest merge base wins
SHA_RE           = re.compile( r"[0-9a-f]{7,40}" )
HUNK_RE          = re.compile( r"^@@ -\S+ \+(\d+)(?:,\d+)? @@" )          # the first line a hunk adds, in the new file
EXIT_REFUSED     = 1
EXIT_NOT_CHECKED = rr.NOT_CHECKED                               # 3, the same code the reviewer's gate and the refusal record use


def _git( root, args ):
    """
    Run one git command in root.

    Requires:
        - root is a directory; args is a list of strings
    Ensures:
        - returns ( return code, stdout text ); a git binary that cannot start returns ( 127, "" )
    """
    try: done = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, encoding="utf-8" )
    except OSError: return 127, ""
    return done.returncode, done.stdout


def read_names( ini ):
    """
    Read the branches to measure from.

    Requires:
        - ini is a configuration file path, or None for the default file
    Ensures:
        - returns the names the key `reuse merge gate base` holds, split on spaces
        - returns BASE_CANDIDATES when the key is absent, doubled, unreadable or empty
    """
    raw = fleet_cap_ini_io.read_value_from_disk( ini if ini is not None else gate.ini_path(), BASE_KEY )
    return raw.split() if raw and raw.strip() else list( BASE_CANDIDATES )


def read_since( ini ):
    """
    Read the commit after which definitions and lines are checked.

    Requires:
        - ini is a configuration file path, or None for the default file
    Ensures:
        - returns the commit text the key `reuse merge gate since` holds, or None when the key is absent, doubled, unreadable or empty
    Raises:
        - ValueError when the key holds something that is not a hexadecimal commit
    """
    raw = fleet_cap_ini_io.read_value_from_disk( ini if ini is not None else gate.ini_path(), SINCE_KEY )
    if raw is None or not raw.strip(): return None
    if not SHA_RE.fullmatch( raw.strip() ): raise ValueError( f"`{SINCE_KEY}` holds {raw!r}, which is not a commit" )
    return raw.strip()


def resolve_base( root, names=None ):
    """
    Name the commit the branch is measured from.

    Requires:
        - root is a git working tree; names is a branch name, a list of them, or None for BASE_CANDIDATES
    Ensures:
        - returns the merge base of HEAD and the named branch that lies nearest HEAD, by the commits between them
        - a name git does not know, or one with no merge base, is passed over
        - returns None when no name has a merge base with HEAD
    """
    names = list( BASE_CANDIDATES ) if not names else ( [ names ] if isinstance( names, str ) else list( names ) )
    best  = None
    for name in names:
        code, out = _git( root, [ "merge-base", name, "HEAD" ] )
        if code != 0 or not out.strip(): continue
        sha = out.strip()
        code, count = _git( root, [ "rev-list", "--count", f"{sha}..HEAD" ] )
        if best is None or int( count ) < best[ 0 ]: best = ( int( count ), sha )
    return best[ 1 ] if best else None


def effective_base( root, sha, since ):
    """
    Move the base up to the `since` commit when that commit lies between the base and HEAD.

    Requires:
        - sha is a commit; since is a commit text or None
    Ensures:
        - returns the full sha of `since` when it is a descendant of sha and an ancestor of HEAD, so earlier definitions and lines are exempt
        - returns sha when since is None, or lies outside that stretch (a branch cut before `since` is checked from its merge base)
    Raises:
        - ValueError when git does not know the `since` commit
    """
    if since is None: return sha
    code, full = _git( root, [ "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}" ] )
    if code != 0 or not full.strip(): raise ValueError( f"`{SINCE_KEY}` names {since}, which git does not know" )
    full = full.strip()
    inside = _git( root, [ "merge-base", "--is-ancestor", sha, full ] )[ 0 ] == 0 and _git( root, [ "merge-base", "--is-ancestor", full, "HEAD" ] )[ 0 ] == 0
    return full if inside else sha


def added_text_by_file( root, base_sha ):
    """
    Collect the lines HEAD adds to Markdown files since base_sha.

    Requires:
        - base_sha is a commit of root's repository
    Ensures:
        - returns { path: text } for each added or modified `.md` file with at least one added line
        - the text holds each added line at its own line number of the new file and an empty line everywhere else, so a line number in a refusal is the file's
        - an added line that itself begins with `++ b/` is told from a file header by the hunk marker before it
        - paths are listed in the order git reports them
        - returns None when git could not produce the diff
    """
    code, out = _git( root, [ "diff", "--unified=0", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "--diff-filter=AM", base_sha, "HEAD", "--", "*.md" ] )
    if code != 0: return None
    files, current, in_hunk, number = {}, None, False, 0
    for line in out.splitlines():
        if line.startswith( "diff --git " ): in_hunk = False
        elif line.startswith( "@@" ): in_hunk, number = True, int( HUNK_RE.match( line ).group( 1 ) ) - 1
        elif not in_hunk and line.startswith( "+++ b/" ): current = line[ 6: ]
        elif in_hunk and line.startswith( "+" ): number += 1; files.setdefault( current, {} )[ number ] = line[ 1: ]
    return { path: "\n".join( rows.get( n, "" ) for n in range( 1, max( rows ) + 1 ) ) for path, rows in files.items() }


def added_definition_ids( root, base_sha ):
    """
    List the symbol ids of the definitions HEAD adds since base_sha.

    Requires:
        - root is a git working tree that holds base_sha and HEAD
    Ensures:
        - the window and the changed files are the daily check's own (`window_of`, `changed_files`)
        - a file the symbol index does not hold (a test file, a skipped folder) lists nothing, by the indexer's own rule (`is_indexed`)
        - a definition is new when its file and name are absent at base_sha; a definition whose text changed is not new
        - a renamed file is read against the path it had at base_sha, so a function counts as new only when it is absent under the old path
        - ids follow the symbol index's rule (module and name, the repository prefix, `#2` for a repeat), so they match a ruling's symbol
        - the two detached worktrees are removed whether the call ends or fails
        - returns the ids sorted

    Raises:
        - RuntimeError when git fails, NeedsetError when a worktree cannot be made
        - ValueError when a changed Python file does not parse, DuplicateCheckError when a script file's extraction does not close
    """
    window = daily.window_of( root, { "commit": base_sha }, None, "HEAD" )
    files  = [ f for f in daily.changed_files( root, window ) if ro.is_indexed( f, root ) ]
    if not files: return []
    stem   = pathlib.Path( root ) / source_at.WORKTREES / f"{WORKTREE_PREFIX}{window[ 'end' ][ :9 ]}"
    tree   = source_at.ensure_worktree( root, window[ "end" ], stem )
    try:
        held = daily.definitions_held_at_start( root, window, files, base_sha, stem.with_name( f"{stem.name}-base" ), lambda f, d: ( f, d[ "name" ] ) )
        report = extract.extract_tree( tree, [ pathlib.Path( tree ) / f for f in files ], "new" )
        if report[ "skipped_python" ]: raise ValueError( f"{', '.join( report[ 'skipped_python' ] )} did not parse, so its definitions cannot be listed" )
        extract.completeness( report )
        found = report[ "definitions" ]
    finally: daily.release( root, tree )
    spec    = sp.spec_for( root )
    records = [ { "lang": d[ "lang" ], "file": d[ "file" ], "name": d[ "name" ], "line": d[ "line" ],
                  "module": py_index.module_name( spec, spec.root / d[ "file" ] ) if d[ "lang" ] == "py" else "" }
                for d in found if ( d[ "file" ], d[ "name" ] ) not in held ]
    records.sort( key=lambda r: ( r[ "file" ], r[ "line" ] ) )
    build._assign_ids( spec, records )
    return sorted( r[ "id" ] for r in records )


def run( root, base, diff_path, data_dir, log_dir, gating, since=None ):
    """
    Judge the outcome lines the branch adds, and the new definitions of a given diff.

    Requires:
        - gating is True or False; since is a commit text or None
        - base is a branch name, a list of names, or None
        - diff_path is a symbol index diff file, or None for the definitions added_definition_ids finds
    Ensures:
        - returns { "refusals": [ { path, n, line, reasons } ], "missing": [ { symbol, reason } ], "lines": int, "definitions": int, "appended": int }
        - returns { "error": text } when the gate could not check: an unreadable or ill-shaped diff file, an unreadable call log, a diff with `algorithm_changed`, no base, or a record that could not be written
        - refusals.jsonl in data_dir gains one record per judged line, once per document text
        - the call log, searches and exclusions are read once for all documents
        - with `since` inside the branch, lines and definitions added before it are not read
    """
    sha = resolve_base( root, base )
    if sha is None: return { "error": "git names no merge base for HEAD; pass --base" }
    try:
        sha = effective_base( root, sha, since )
        diff = json.loads( pathlib.Path( diff_path ).read_text( encoding="utf-8" ) ) if diff_path else { "added": added_definition_ids( root, sha ) }
        if not isinstance( diff, dict ) or not isinstance( diff.get( "added", [] ), list ): raise ValueError( f"{diff_path} is not a symbol index diff" )
        if "algorithm_changed" in diff: raise ValueError( f"{diff_path}: the pin algorithm changed, so the diff lists no definitions to check" )
        records, _bad = eg.merge_call_logs( log_dir )
    except UNREADABLE as e: return { "error": f"{type( e ).__name__}: {e}" }
    files = added_text_by_file( root, sha )
    if files is None: return { "error": f"git could not diff {sha} against HEAD" }
    receipts, searches, exclusions = eg.receipts_by_id( records ), eg.searches_by_receipt( records, data_dir ), eg.exclusions_by_symbol( records )
    refusals, outcomes, rulings, lines, appended = [], [], {}, 0, 0
    for path, text in files.items():
        file_rulings = eg.parse_rulings( text )
        verdicts     = rr.judge( text, receipts, searches, exclusions, file_rulings, root )
        lines       += len( verdicts )
        try:
            if verdicts: appended += rr.record( data_dir, text, verdicts )
        except OSError as e: return { "error": f"{type( e ).__name__}: {e}" }
        outcomes    += ro.parse_outcomes( text )
        for sym, rows in file_rulings.items(): rulings.setdefault( sym, [] ).extend( rows )
        refusals    += [ { "path": path, "n": v[ "n" ], "line": v[ "line" ], "reasons": v[ "reasons" ] } for v in verdicts if v[ "status" ] == "refused" ]
    missing = ro.missing_outcome_refusals( diff.get( "added", [] ), outcomes, rulings )
    return { "refusals": refusals, "missing": missing, "lines": lines, "definitions": len( diff.get( "added", [] ) ), "appended": appended }


def summary( result, gating ):
    """
    Print-ready lines for the test-suite job.

    Requires:
        - result is a successful run() result; gating is True or False
    Ensures:
        - returns the list of lines, ending with one verdict line
        - with gating false the refusals are counted under "Report-only" and Failed stays 0
    """
    bad    = len( result[ "refusals" ] ) + len( result[ "missing" ] )
    total  = 1 + result[ "lines" ] + result[ "definitions" ]
    failed = bad if gating else 0
    out    = [ f"Reuse gate: {result[ 'lines' ]} outcome lines and {result[ 'definitions' ]} new definitions checked; gating is {'on' if gating else 'off (report only)'}." ]
    for r in result[ "refusals" ]: out.append( f"REFUSED {r[ 'path' ]} line {r[ 'n' ]}: {'; '.join( r[ 'reasons' ] )}: {r[ 'line' ]}" )
    for m in result[ "missing" ]: out.append( f"MISSING {m[ 'reason' ]}" )
    if not gating: out.append( f"Report-only: {bad}" )
    out += [ f"Total Tests: {total}", f"Passed: {total - failed}", f"Failed: {failed}", f"Errors: {failed}" ]
    if failed: out.append( f"REUSE GATE FAILED: {bad} refusals or missing outcome lines." )
    else:      out.append( "REUSE GATE PASSED: " + ( f"report only, {bad} would be refused." if bad else "every outcome line the branch adds holds up." ) )
    return out


def main( argv=None, out=None ):
    """
    Command line: judge the outcome lines this branch adds.

    Requires:
        - run from, or given with --root, a git working tree
    Ensures:
        - prints the summary block on `out` and returns 0, 1 or 3
        - returns 3 with the reason on `out`, and no summary block, when the gate could not check, so the job reads the run as not executed
        - returns 1 only when gating is true and a line is refused or a definition has no outcome line
    """
    ap = argparse.ArgumentParser( description="Judge the REUSE-OUTCOME lines a branch adds, for the merge pyramid." )
    ap.add_argument( "--root", default="." )
    ap.add_argument( "--base", default=None, help="the branch or commit to measure from; default is the branches of `reuse merge gate base`, else main and origin/main" )
    ap.add_argument( "--diff", default=None, help="a symbol index diff to use in place of the definitions found from git" )
    ap.add_argument( "--data-dir", default=None )
    ap.add_argument( "--log-dir", default=None )
    ap.add_argument( "--ini", default=None, help="the configuration file holding `reuse review gating`" )
    a    = ap.parse_args( argv )
    out  = out if out is not None else sys.stdout
    root = pathlib.Path( a.root ).resolve()
    flag = gate.read_gating( a.ini )
    if flag is None:
        print( f"REFUSING: `{gate.GATING_KEY}` could not be read. Nothing was checked.", file=out )
        return EXIT_NOT_CHECKED
    try: since = read_since( a.ini )
    except ValueError as e:
        print( f"REFUSING: {e}. Nothing was checked.", file=out )
        return EXIT_NOT_CHECKED
    if flag and since is None:
        print( f"REFUSING: `{gate.GATING_KEY}` is true and `{SINCE_KEY}` is empty, so the gate would check every definition back to the merge base."
               f" Set both in one commit. Nothing was checked.", file=out )
        return EXIT_NOT_CHECKED
    data = pathlib.Path( a.data_dir or rr.default_data_dir( root ) )
    try: data.mkdir( parents=True, exist_ok=True )
    except OSError as e:
        print( f"REFUSING: {type( e ).__name__}: {e}. Nothing was checked.", file=out )
        return EXIT_NOT_CHECKED
    result = run( root, a.base or read_names( a.ini ), a.diff, data, a.log_dir or data / "call-log", flag, since )
    if "error" in result:
        print( f"REFUSING: {result[ 'error' ]}. Nothing was checked.", file=out )
        return EXIT_NOT_CHECKED
    print( "\n".join( summary( result, flag ) ), file=out )
    return EXIT_REFUSED if flag and ( result[ "refusals" ] or result[ "missing" ] ) else 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
