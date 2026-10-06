"""
Runs the four script checks on one rewritten package and writes the claim check's input.

A writer has rewritten the docstrings of one package. This runs docstring_lint, docs_only_diff,
contract_diff and a compile check on the package's own files against a base revision. It writes
result.json and pairs.json to an output directory. The checks are the existing modules; none is
re-implemented here. The claim check and the reader test are run separately.
"""

import argparse
import json
import os
import sys

from . import contract_diff
from .cli import in_scope, tracked_files
from .docs_only_diff import DOC_SUFFIX, _git, _show, changed_files, path_difference
from .docstring_lint import extract_docstrings, lint_source
from .marker_counts import count_markers
from .word_list import configure_root


def _is_own( path, package ):
    """
    Say whether a path is a file that sits directly in the package directory.

    Requires:
        - path and package are posix repo-relative paths

    Ensures:
        - True for a file whose directory is the package, False for a subdirectory's file

    Raises:
        - nothing
    """
    return path.rpartition( "/" )[ 0 ] == package


def keyed_docstrings( source ):
    """
    Key every docstring of a Python source by kind, name and occurrence.

    Requires:
        - source is valid Python text, or None for a file that does not exist

    Ensures:
        - returns { ( kind, name, occurrence ): text } in extract_docstrings order
        - occurrence counts the docstrings of the same name before this one in the file, so the key is unique
        - None gives an empty dict

    Raises:
        - SyntaxError when source does not parse
    """
    keyed = {}
    seen  = {}
    for kind, name, _, text in ( extract_docstrings( source ) if source is not None else [] ):
        keyed[ ( kind, name, seen.get( name, 0 ) ) ] = text
        seen[ name ] = seen.get( name, 0 ) + 1
    return keyed


def _label( key ):
    """
    Write a docstring key as text.

    Requires:
        - key is ( kind, name, occurrence )

    Ensures:
        - returns kind:name#occurrence

    Raises:
        - nothing
    """
    return f"{key[ 0 ]}:{key[ 1 ]}#{key[ 2 ]}"


def match_docstrings( path, old_source, new_source ):
    """
    Pair the docstrings of one file before and after a rewrite.

    Requires:
        - path is the repo-relative path; the sources are Python text, or None when the file is absent on that side

    Ensures:
        - returns ( pairs, refusal ); refusal is None when the key sets are equal
        - pairs hold { id, old, new } for each docstring whose text changed, id being path::name#occurrence
        - a differing key set gives no pairs and a refusal naming the file and the keys that were added or removed
        - a side that does not parse gives no pairs and a refusal naming the side

    Raises:
        - nothing
    """
    try:
        old = keyed_docstrings( old_source )
    except SyntaxError as err:
        return [], { "file": path, "reason": f"old text does not parse: {err.msg}" }
    try:
        new = keyed_docstrings( new_source )
    except SyntaxError as err:
        return [], { "file": path, "reason": f"new text does not parse: {err.msg}" }
    if old.keys() != new.keys():
        added   = [ _label( k ) for k in new if k not in old ]
        removed = [ _label( k ) for k in old if k not in new ]
        return [], { "file": path, "reason": "docstring keys differ", "added": added, "removed": removed }
    return [ { "id": f"{path}::{k[ 1 ]}#{k[ 2 ]}", "old": old[ k ], "new": new[ k ] } for k in new if old[ k ] != new[ k ] ], None


def _run( name, action ):
    """
    Run one check and record its result.

    Requires:
        - action is a callable that returns ( passed, output )

    Ensures:
        - returns { name, pass, ran, output }
        - any exception from action is a check that did not run: pass False, ran False, and the error named
        - a check that did not run is never reported as passed

    Raises:
        - nothing
    """
    try:
        passed, output = action()
    except Exception as err:
        return { "name": name, "pass": False, "ran": False, "output": f"did not run: {type( err ).__name__}: {err}" }
    return { "name": name, "pass": bool( passed ), "ran": True, "output": output }


def _lint_check( root, files ):
    """
    Run docstring_lint over the package files.

    Requires:
        - files are repo-relative paths of files that exist in the working tree

    Ensures:
        - returns ( passed, findings ), passed when there are no findings
        - each finding is path:line: rule: message

    Raises:
        - OSError when a file cannot be read
    """
    found = []
    for path in files:
        with open( f"{root}/{path}", encoding="utf-8" ) as handle: source = handle.read()
        found += [ f"{f.path}:{f.line}: {f.rule}: {f.message}" for f in lint_source( path, source, root ) ]
    return not found, found


def _docs_only_check( root, base, changed ):
    """
    Run docs_only_diff over the changed package files.

    Requires:
        - changed maps each changed package path to its ( old_mode, new_mode )

    Ensures:
        - returns ( passed, rows ) with one { path, failure } per changed file, failure None for a pass
        - passed when every failure is None

    Raises:
        - RuntimeError from git when a read fails
    """
    rows = [ { "path": p, "failure": path_difference( p, modes, _show( root, base, p ), _show( root, None, p ) ) } for p, modes in sorted( changed.items() ) ]
    return all( row[ "failure" ] is None for row in rows ), rows


def _contract_check( root, base, changed ):
    """
    Run contract_diff over the changed .py package files.

    Requires:
        - changed maps each changed package path to its modes

    Ensures:
        - returns ( passed, { findings, table } ), passed when contract_diff reports no finding
        - the table is what contract_diff prints for the same rows

    Raises:
        - SyntaxError when a changed file does not parse
    """
    results = {}
    for path in sorted( p for p in changed if p.endswith( ".py" ) ):
        rows = contract_diff.diff_contracts( _show( root, base, path ), _show( root, None, path ) )
        if rows: results[ path ] = rows
    found = contract_diff.findings( results )
    return not found, { "findings": found, "table": contract_diff.render_table( results ) }


def _compile_check( root, changed ):
    """
    Check that every changed .py file that still exists compiles.

    Requires:
        - changed maps each changed package path to its modes

    Ensures:
        - returns ( passed, rows ) with one { path, error } per file, error None for a pass
        - compile() is used and no .pyc is written, so the check leaves nothing behind
        - a deleted file is not compiled

    Raises:
        - nothing
    """
    rows = []
    for path in sorted( p for p in changed if p.endswith( ".py" ) ):
        source = _show( root, None, path )
        if source is None: continue
        try:
            compile( source, path, "exec" )
            rows.append( { "path": path, "error": None } )
        except ( SyntaxError, ValueError ) as err:
            rows.append( { "path": path, "error": f"{type( err ).__name__}: {err}" } )
    return all( row[ "error" ] is None for row in rows ), rows


def check_package( root, base, package ):
    """
    Run the four checks on one package against a base revision.

    Requires:
        - root is a git working tree that holds the word list; base resolves to a commit
        - package is a repo-relative directory holding at least one in-scope .py file

    Ensures:
        - returns ( result, pairs ); result carries base (a full sha), package, changed_files, checks, counts, refusals and pass
        - the package's files are its own in-scope .py files only, never a subdirectory's
        - changed_files are the files directly in the package that differ from base, markdown excluded
        - pass is True only when every check ran and passed and no docstring key set differed
        - counts hold docstrings in the new text, docstrings whose text changed, and the words before and after in those

    Raises:
        - RuntimeError from git when base does not resolve
        - ValueError when the package has no in-scope .py file
    """
    configure_root( root )
    sha     = _git( root, "rev-parse", "--verify", f"{base}^{{commit}}" ).strip()
    changed = { p: m for p, m in changed_files( root, base ).items() if _is_own( p, package ) and in_scope( p ) and not p.endswith( DOC_SUFFIX ) }
    files   = sorted( { p for p in tracked_files( root, ( ".py", ) ) if _is_own( p, package ) } | { p for p in changed if p.endswith( ".py" ) } )
    if not files: raise ValueError( f"no in-scope .py files directly in {package}" )
    existing = [ p for p in files if os.path.exists( f"{root}/{p}" ) ]
    checks   = [
        _run( "docstring_lint", lambda: _lint_check( root, existing ) ),
        _run( "docs_only_diff", lambda: _docs_only_check( root, base, changed ) ),
        _run( "contract_diff", lambda: _contract_check( root, base, changed ) ),
        _run( "py_compile", lambda: _compile_check( root, changed ) )
    ]
    pairs, refusals = [], []
    for path in sorted( p for p in changed if p.endswith( ".py" ) ):
        try:
            found, refusal = match_docstrings( path, _show( root, base, path ), _show( root, None, path ) )
        except Exception as err:
            found, refusal = [], { "file": path, "reason": f"could not be compared: {type( err ).__name__}: {err}" }
        pairs += found
        if refusal is not None: refusals.append( refusal )
    docstrings = 0
    for path in existing:
        try:
            docstrings += len( keyed_docstrings( _show( root, None, path ) ) )
        except ( SyntaxError, ValueError ): pass
    counts = {
        "docstrings"         : docstrings,
        "docstrings_changed" : len( pairs ),
        "words_before"       : sum( count_markers( p[ "old" ] )[ "words" ] for p in pairs ),
        "words_after"        : sum( count_markers( p[ "new" ] )[ "words" ] for p in pairs )
    }
    result = {
        "base"          : sha,
        "package"       : package,
        "changed_files" : sorted( changed ),
        "checks"        : checks,
        "counts"        : counts,
        "refusals"      : refusals,
        "pass"          : all( c[ "pass" ] for c in checks ) and not refusals
    }
    return result, pairs


def refusal_result( package, message ):
    """
    Build the result.json content for a run that could not start.

    Requires:
        - package is the package argument and message says why the run was refused

    Ensures:
        - returns a dict with every key a normal result has: base None, changed_files and checks and refusals empty, zero counts
        - pass is False and refused holds the message, so a reader tells it from a run that found nothing

    Raises:
        - nothing
    """
    counts = { "docstrings": 0, "docstrings_changed": 0, "words_before": 0, "words_after": 0 }
    return { "base": None, "package": package, "changed_files": [], "checks": [], "counts": counts, "refusals": [], "pass": False, "refused": message }


def main( argv=None, out=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[ 1: ]

    Ensures:
        - writes result.json and pairs.json in --out, and nothing else, then prints one line per check
        - returns 0 only when every check passed and nothing was refused, 1 otherwise, result.json written either way
        - a check that raises any exception is recorded as did not run, so a bug in one module never costs the report
        - returns 2 when base does not resolve or the package holds no in-scope .py file, and then result.json holds the refusal with every key a normal result has, and pairs.json is not written and one left in --out by an earlier run is removed, so no reader takes a refusal for a run with nothing changed

    Raises:
        - nothing
    """
    out    = out if out is not None else sys.stdout
    parser = argparse.ArgumentParser( description="Run the four script checks on one rewritten package." )
    parser.add_argument( "--repo-root", default=".", help="git working tree; its working tree is the new text" )
    parser.add_argument( "--base", required=True, help="git revision that holds the old text" )
    parser.add_argument( "--package", required=True, help="repo-relative package directory" )
    parser.add_argument( "--out", required=True, help="directory to create for result.json and pairs.json" )
    args = parser.parse_args( sys.argv[ 1: ] if argv is None else argv )
    package = args.package.rstrip( "/" )
    try:
        result, pairs = check_package( args.repo_root, args.base, package )
    except ( RuntimeError, ValueError ) as err:
        result, pairs = refusal_result( package, str( err ) ), None
        out.write( f"REFUSED: {err}\n" )
    os.makedirs( args.out, exist_ok=True )
    for name, content in ( ( "result.json", result ), ( "pairs.json", pairs ) ):
        if content is None:
            if os.path.exists( f"{args.out}/{name}" ): os.remove( f"{args.out}/{name}" )
            continue
        with open( f"{args.out}/{name}", "w", encoding="utf-8" ) as handle:
            json.dump( content, handle, indent=2 )
            handle.write( "\n" )
    if "refused" in result: return 2
    for check in result[ "checks" ]: out.write( f"{'PASS' if check[ 'pass' ] else 'FAIL'} {check[ 'name' ]}{'' if check[ 'ran' ] else ' (did not run)'}\n" )
    for refusal in result[ "refusals" ]:
        keys = f", added {refusal[ 'added' ]}, removed {refusal[ 'removed' ]}" if "added" in refusal else ""
        out.write( f"REFUSED {refusal[ 'file' ]}: {refusal[ 'reason' ]}{keys}\n" )
    out.write( f"{'PASS' if result[ 'pass' ] else 'FAIL'} {result[ 'package' ]} at base {result[ 'base' ]}, {len( pairs )} changed docstrings\n" )
    return 0 if result[ "pass" ] else 1


if __name__ == "__main__":
    sys.exit( main() )
