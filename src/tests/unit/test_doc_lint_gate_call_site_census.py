"""
A census of the places where the commit gate reads a file or starts a process.

Each place is fed an OSError and a UnicodeDecodeError in turn, and the gate's answer is compared with a table.
A new place has no row, so the test fails until its answer is decided and written down.
"""

import ast
import builtins
import io
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest

from cosa.repo.doc_lint import counts, gate, tool_runners as tr, ts_counts, ts_doc_exists, tsdoc_lint, word_list

PACKAGE = os.path.dirname( os.path.abspath( gate.__file__ ) )
WORDS   = [ "not", "never", "the" ]
SEEDED  = "This is NOT fine.\n"

# The modules the gate module imports from its own package, directly or through another of them.
MODULES = ( "changed_ranges", "cli", "comment_lint", "counts", "docstring_lint", "gate", "links", "marker_counts", "md_lint", "rule_lists",
            "swept_scope", "text_rules", "tool_runners", "ts_counts", "ts_doc_exists", "tsdoc_lint", "waivers", "word_list" )

# The range gate is a separate entry point of the same package: the pre-push chain runs it, a commit does not.
# Its places are enumerated here so a new one needs a row; they are not injected, because no commit reaches them.
RANGE_MODULES = ( "range_gate", )

# What the gate does when the place fails. CRASH is the loud line and exit 0, the top-level handler of gate.main.
# SAID is a warning or a refusal that names the failure, with no crash. OFF is a place no commit reaches: a
# command-line entry point of another tool, or a reader the gate replaces with its own. SAFE is a call that
# answers False or swallows the failure by contract (os.path.exists, rmtree with ignore_errors), so there is no
# failure to inject and no answer to compare.
CRASH = "crash, commit allowed"
SAID  = "said so, no crash"
OFF   = "not on the gate's path"
RANGE = "range gate entry point, not a commit's path"
SAFE  = "cannot raise, nothing to inject"

# A call is a place when its resolved name is one of these, however the module was imported, or when it is a
# method of this name on any object. Resolving the name means `from subprocess import run as go` is still seen.
# The claim is every spelling of a name in WATCHED and METHODS: a call the scanner cannot resolve to a name
# (getattr, __import__, eval, exec) or a bare alias of a watched builtin is itself a place, so it needs a row.
WATCHED = {
    "subprocess" : { "run", "check_output", "check_call", "call", "Popen", "getoutput", "getstatusoutput" },
    "os"         : { "listdir", "scandir", "walk", "popen", "system", "stat", "fdopen" },
    "io"         : { "open" },
    "tempfile"   : { "mkdtemp", "mkstemp", "TemporaryDirectory", "NamedTemporaryFile" },
    "shutil"     : { "copy", "copy2", "copyfile", "copytree", "move", "rmtree" },
    "glob"       : { "glob", "iglob" },
}
METHODS    = { "read_text", "read_bytes", "iterdir", "glob", "rglob", "open", "write_text", "write_bytes", "stat", "exists" }
UNRESOLVED = { "getattr", "__import__", "eval", "exec" }
ALIASED    = { "open" }

EXPECTED = {
    "changed_ranges.changed_line_ranges:subprocess.run#0" : ( CRASH, CRASH ),
    "cli.run_linter:open#0"                               : OFF,
    "cli.tracked_files:subprocess.run#0"                  : OFF,
    "counts._read_disk.read:open#0"                       : OFF,
    "counts.counted_paths:subprocess.run#0"               : ( CRASH, CRASH ),
    "counts.differing_rule_files:subprocess.run#0"        : ( CRASH, CRASH ),
    "counts.main:open#0"                                  : OFF,
    "counts.main:open#1"                                  : OFF,
    "counts.rule_files:subprocess.run#0"                  : ( CRASH, CRASH ),
    "counts.rules_stamp.disk:open#0"                      : OFF,
    "gate.git_toplevel:subprocess.run#0"                  : ( CRASH, CRASH ),
    "gate.head_table_text:subprocess.run#0"               : ( CRASH, CRASH ),
    "gate.incoming_commits:open#0"                        : ( SAID, CRASH ),
    "gate.incoming_commits:subprocess.run#0"              : ( CRASH, CRASH ),
    "gate.incoming_commits:subprocess.run#1"              : ( CRASH, CRASH ),
    "gate.staged_binary:subprocess.run#0"                 : ( CRASH, CRASH ),
    "gate.staged_bytes:open#0"                            : ( CRASH, CRASH ),
    "gate.staged_bytes:subprocess.run#0"                  : ( CRASH, CRASH ),
    "gate.staged_deleted:subprocess.run#0"                : ( CRASH, CRASH ),
    "gate.staged_entries:subprocess.run#0"                : ( CRASH, CRASH ),
    "gate.staged_source:subprocess.run#0"                 : ( CRASH, SAID ),
    "md_lint._read_text:open#0"                           : ( CRASH, CRASH ),
    "md_lint.sibling_paths:os.listdir#0"                  : ( CRASH, CRASH ),
    "tool_runners.run_dart_analyze:runner#0"              : OFF,
    "tool_runners.run_markdownlint:runner#0"              : ( CRASH, CRASH ),
    "tool_runners._ruff_check:runner#0"                   : ( CRASH, CRASH ),
    "ts_counts._disk_text:open#0"                         : OFF,
    "ts_counts.extract:open#0"                            : ( CRASH, CRASH ),
    "ts_counts.main:open#0"                               : OFF,
    "ts_counts.main:open#1"                               : OFF,
    "ts_doc_exists.extract:open#0"                        : ( CRASH, CRASH ),
    "ts_doc_exists.main:open#0"                           : OFF,
    "ts_doc_exists.main:open#1"                           : OFF,
    "ts_doc_exists.run_extractor:subprocess.run#0"        : ( CRASH, CRASH ),
    "tsdoc_lint.run_extractor:subprocess.run#0"           : ( CRASH, CRASH ),
    "tsdoc_lint.tracked_files:subprocess.run#0"           : ( CRASH, CRASH ),
    "word_list.load_words:open#0"                         : ( CRASH, CRASH ),
    "range_gate.git_bytes:subprocess.run#0"                  : RANGE,
    "range_gate.working_epoch_text:open#0"                   : RANGE,
    "range_gate.require_commit:subprocess.run#0"             : RANGE,
    "range_gate.committed_epoch_text:subprocess.run#0"       : RANGE,
    "range_gate.descends:subprocess.run#0"                   : RANGE,
    "range_gate.run_gate:subprocess.run#0"                   : RANGE,
    "range_gate.check_commit:open#0"                         : RANGE,
    "range_gate.check_commit:runner#0"                       : RANGE,
    "range_gate.sweep_stale:os.listdir#0"                    : RANGE,
    "range_gate.sweep_stale:subprocess.run#0"                : RANGE,
    "range_gate.sweep_stale:subprocess.run#1"                : RANGE,
    "range_gate.main:tempfile.mkdtemp#0"                     : RANGE,
    "range_gate.main:open#0"                                 : RANGE,
    "range_gate.main:subprocess.run#0"                       : RANGE,
    "ts_counts.extract:tempfile.mkdtemp#0"                   : ( CRASH, CRASH ),
    "ts_doc_exists.extract:tempfile.mkdtemp#0"               : ( CRASH, CRASH ),
    "links.markdown_link_findings:.exists#0"              : SAFE,
    "links.design_path_findings:.exists#0"                : SAFE,
    "tool_runners.find_tool:.exists#0"                    : SAFE,
    "tool_runners.find_tool:.exists#1"                    : SAFE,
    "ts_counts.extract:shutil.rmtree#0"                   : SAFE,
    "ts_doc_exists.extract:shutil.rmtree#0"               : SAFE,
    "range_gate.working_epoch_text:.exists#0"                : RANGE,
    "range_gate.check_commit:.exists#0"                      : RANGE,
    "range_gate.sweep_stale:.exists#0"                       : RANGE,
    "range_gate.sweep_stale:shutil.rmtree#0"                 : RANGE,
    "range_gate.main:shutil.rmtree#0"                        : RANGE,
}

ERRORS = ( OSError( 13, "injected for the census" ), UnicodeDecodeError( "utf-8", b"\xff", 0, 1, "injected for the census" ) )


def _aliases( tree ):
    """Map each name an import binds to the dotted name it stands for."""
    found = {}
    for node in ast.walk( tree ):
        if isinstance( node, ast.Import ):
            for alias in node.names: found[ alias.asname or alias.name ] = alias.name
        elif isinstance( node, ast.ImportFrom ) and node.level == 0 and node.module:
            for alias in node.names: found[ alias.asname or alias.name ] = f"{node.module}.{alias.name}"
    return found


def _kind( call, aliases ):
    """Name the kind of place a call is, or None."""
    func = call.func
    if isinstance( func, ast.Name ):
        if func.id in ( "open", "runner" ): return func.id
        if func.id in UNRESOLVED: return func.id
        resolved = aliases.get( func.id, "" )
    elif isinstance( func, ast.Attribute ) and isinstance( func.value, ast.Name ):
        resolved = f"{aliases.get( func.value.id, func.value.id )}.{func.attr}"
    elif isinstance( func, ast.Attribute ):
        return f".{func.attr}" if func.attr in METHODS else None
    else:
        return None
    module, _, name = resolved.rpartition( "." )
    if name in WATCHED.get( module, () ): return resolved
    return f".{func.attr}" if isinstance( func, ast.Attribute ) and func.attr in METHODS else None


def _scan( module, path, tree ):
    """List the places of one parsed module as ( id, file, first line, last line )."""
    found, seen, aliases = [], {}, _aliases( tree )
    def walk( node, names ):
        for child in ast.iter_child_nodes( node ):
            inner = names + [ child.name ] if isinstance( child, ( ast.FunctionDef, ast.ClassDef ) ) else names
            kind  = _kind( child, aliases ) if isinstance( child, ast.Call ) else None
            if kind is None and isinstance( child, ast.Name ) and child.id in ALIASED and not ( isinstance( node, ast.Call ) and node.func is child ):
                kind = f"{child.id}-alias"
            if kind is not None:
                key = ( ".".join( names ), kind )
                found.append( ( f"{module}.{key[ 0 ]}:{key[ 1 ]}#{seen.get( key, 0 )}", path, child.lineno, child.end_lineno ) )
                seen[ key ] = seen.get( key, 0 ) + 1
            walk( child, inner )
    walk( tree, [] )
    return found


def _sites( modules=MODULES + RANGE_MODULES ):
    """List every place as ( id, file, first line, last line )."""
    found = []
    for module in modules:
        path = os.path.join( PACKAGE, f"{module}.py" )
        with open( path, encoding="utf-8" ) as handle: found += _scan( module, path, ast.parse( handle.read() ) )
    return found


def _package_imports( module ):
    with open( os.path.join( PACKAGE, f"{module}.py" ), encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    names = set()
    for node in ast.walk( tree ):
        if isinstance( node, ast.ImportFrom ) and node.level == 1:
            names |= { node.module } if node.module else { alias.name for alias in node.names }
    return names


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _stage( root, files ):
    for rel, text in files.items():
        full = root / rel
        full.parent.mkdir( parents=True, exist_ok=True )
        full.write_text( text, encoding="utf-8" )
    _git( root, "add", "-f", *files )


def _doc( line ):
    return f'def f():\n    """\n    Return it.\n\n    {line}\n    """\n'


def _build( root, new_stamp ):
    """Build a repository whose staged commit sends the gate down many of its paths."""
    root.mkdir()
    _git( root, "init", "-q" )
    ( root / "src" / "conf" ).mkdir( parents=True )
    ( root / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )     # left untracked: staged_bytes reads it from the disk
    for rel in ts_counts.STAMP_FILES + ts_doc_exists.STAMP_FILES:
        if not ( root / rel ).exists(): _stage( root, { rel: f"stamp file {rel}\n" } )
    _stage( root, {
        counts.TABLE_PATH    : counts.table_text( {}, counts.rules_stamp( str( root ) ) ),
        ts_counts.TABLE_PATH : counts.table_text( {}, ts_counts.rules_stamp( str( root ) ) ),
        ts_doc_exists.TABLE_PATH : counts.table_text( {}, ts_doc_exists.rules_stamp( str( root ) ) ),
        "docs/split.md"      : "# Split\n\nThe index.\n",
        "docs/split/01-a.md" : "# Part\n\nA part.\n",
    } )
    _git( root, "commit", "-q", "--no-verify", "-m", "base" )
    ( root / ".git" / "MERGE_HEAD" ).write_text( _git( root, "rev-parse", "HEAD" ), encoding="utf-8" )
    _stage( root, { "src/pkg/a.py": _doc( "This is NOT fine." ), "src/tests/t.py": _doc( "This is NOT fine." ), "src/web/a.ts": "/** Fine. */\n", "docs/split/02-b.md": SEEDED } )
    if new_stamp:
        _stage( root, { counts.TABLE_PATH: counts.table_text( {}, "another-stamp" ), ts_counts.TABLE_PATH: counts.table_text( {}, "another-stamp" ), ts_doc_exists.TABLE_PATH: counts.table_text( {}, "another-stamp" ) } )
    return root


@pytest.fixture( scope="module" )
def scenarios( tmp_path_factory ):
    base = tmp_path_factory.mktemp( "census" )
    yield [ _build( base / "plain", False ), _build( base / "regenerated", True ) ]
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _run( root, monkeypatch, target=None, error=None ):
    """Run the gate once with error raised at target; return ( exit code, lines, reached )."""
    reached = set()
    sites   = _sites()
    real    = { "subprocess.run": subprocess.run, "open": builtins.open, "os.listdir": os.listdir, "tempfile.mkdtemp": tempfile.mkdtemp }

    def place( kinds ):
        frame = sys._getframe( 2 )
        file  = os.path.abspath( frame.f_code.co_filename )
        return next( ( site for site, path, first, last in sites if path == file and first <= frame.f_lineno <= last and site.split( ":" )[ 1 ].split( "#" )[ 0 ] in kinds ), None )

    def proxy( kind ):
        def call( *args, **kwargs ):
            site = place( ( kind, "runner" ) if kind == "subprocess.run" else ( kind, ) )
            if site is not None:
                reached.add( site )
                if site == target: raise error
            if kind == "subprocess.run" and args[ 0 ][ 0 ] == "node" and args[ 0 ][ 1 ].endswith( "ts_export_extract.mjs" ):     # the export extractor: every file gets an export record with no symbols
                return SimpleNamespace( returncode=0, stderr="", stdout="\n".join( '{"kind": "exports", "file": "%s", "parse_errors": [], "reexports": 0, "symbols": []}' % name for name in args[ 0 ][ 4 : ] ) )
            if kind == "subprocess.run" and args[ 0 ][ 0 ] == "node":                              # no test needs Node: every file gets its file record
                return SimpleNamespace( returncode=0, stderr="", stdout="\n".join( '{"kind": "file", "file": "%s", "ts_version": "5", "parse_errors": []}' % name for name in args[ 0 ][ 4 : ] ) )
            if kind == "subprocess.run" and site is not None and site.split( ":" )[ 1 ].startswith( "runner" ):
                counted = "Linting: %d file(s)\n" % len( args[ 0 ][ 3: ] ) if "--no-globs" in args[ 0 ] else ""
                return SimpleNamespace( returncode=0, stdout=counted, stderr="" )                  # ruff and markdownlint-cli2 stand-ins that report nothing
            return real[ kind ]( *args, **kwargs )
        return call

    with monkeypatch.context() as patch:
        patch.setenv( "LUPIN_RUFF", str( root ) )
        patch.setenv( "LUPIN_MARKDOWNLINT", str( root ) )
        patch.setattr( gate, "run_ruff", lambda r, paths, sources=None: tr.run_ruff( r, paths, runner=subprocess.run, sources=sources ) )
        patch.setattr( gate, "run_markdownlint", lambda r, paths: tr.run_markdownlint( r, paths, runner=subprocess.run ) )
        patch.setattr( subprocess, "run", proxy( "subprocess.run" ) )
        patch.setattr( builtins, "open", proxy( "open" ) )
        patch.setattr( os, "listdir", proxy( "os.listdir" ) )
        patch.setattr( tempfile, "mkdtemp", proxy( "tempfile.mkdtemp" ) )
        err  = io.StringIO()
        code = gate.main( [ "--repo-root", str( root ), "--blocking" ], err )
    return code, err.getvalue().split( "\n" ), reached


SPELLINGS = """
import glob
import io
import os
import shutil
import subprocess as sp
import tempfile
from os import walk as tree_walk
from pathlib import Path
from subprocess import run as go


def f( x ):
    sp.check_output( [ "git" ] )
    sp.Popen( [ "git" ] )
    go( [ "git" ] )
    os.scandir( x )
    tree_walk( x )
    io.open( x )
    tempfile.mkdtemp()
    Path( x ).read_text()
    x.iterdir()
    open( x )
    runner( [ "git" ] )
    os.listdir( x )
    sp.run( [ "git" ] )
    os.popen( x )
    os.system( x )
    os.stat( x )
    os.fdopen( x )
    sp.getoutput( x )
    shutil.copy( x, x )
    glob.glob( x )
    Path( x ).open()
    Path( x ).write_text( "" )
    Path( x ).exists()
    getattr( sp, "run" )( x )
    __import__( "os" )
    fn = open


def g( x ):
    x.run()
    x.read()
    print( os.path.join( "a", "b" ) )
"""


def test_the_scanner_sees_every_spelling_of_a_place_and_nothing_else():
    found = [ ( site.split( ":" )[ 0 ], site.split( ":" )[ 1 ].split( "#" )[ 0 ] ) for site, _p, _a, _b in _scan( "m", "m.py", ast.parse( SPELLINGS ) ) ]
    assert found == [ ( "m.f", kind ) for kind in ( "subprocess.check_output", "subprocess.Popen", "subprocess.run", "os.scandir", "os.walk", "io.open",
                                                    "tempfile.mkdtemp", ".read_text", ".iterdir", "open", "runner", "os.listdir", "subprocess.run",
                                                    "os.popen", "os.system", "os.stat", "os.fdopen", "subprocess.getoutput", "shutil.copy", "glob.glob",
                                                    ".open", ".write_text", ".exists", "getattr", "__import__", "open-alias" ) ]


def test_the_module_list_is_every_module_the_gate_imports_from_its_package():
    closure, queue = { "gate" }, [ "gate" ]
    while queue:
        for name in _package_imports( queue.pop() ) - closure:
            closure.add( name )
            queue.append( name )
    assert sorted( closure ) == list( MODULES )


def test_every_place_the_gate_reads_a_file_or_starts_a_process_has_a_row():
    sites = [ site for site, _path, _first, _last in _sites() ]
    assert len( sites ) == len( set( sites ) ) == 64 and sorted( sites ) == sorted( EXPECTED )
    lines = [ ( path, site.split( ":" )[ 1 ].split( "#" )[ 0 ], first ) for site, path, first, _last in _sites() ]
    assert len( lines ) == len( set( lines ) )                                                    # one place of a kind on a line, so a frame names its place
    assert [ sum( 1 for row in EXPECTED.values() if row == kind ) for kind in ( OFF, RANGE, SAFE ) ] == [ 12, 19, 6 ]
    assert sum( 1 for row in EXPECTED.values() if row not in ( OFF, RANGE, SAFE ) ) == 27


def test_every_place_on_the_gates_path_answers_an_oserror_and_a_decode_error_as_its_row_says( scenarios, monkeypatch ):
    quiet   = [ _run( root, monkeypatch ) for root in scenarios ]
    reached = [ run[ 2 ] for run in quiet ]
    on_path = sorted( site for site, row in EXPECTED.items() if row not in ( OFF, RANGE, SAFE ) )
    assert sorted( reached[ 0 ] | reached[ 1 ] ) == on_path                                       # every row is reached by a scenario, and no place marked OFF is
    assert [ ( code, [ ln for ln in lines if "GATE CRASHED" in ln ] ) for code, lines, _reached in quiet ] == [ ( gate.REFUSAL_EXIT, [] ) ] * 2
    answers = {}
    for site in on_path:
        which = 0 if site in reached[ 0 ] else 1
        found = []
        for error in ERRORS:
            code, lines, fired = _run( scenarios[ which ], monkeypatch, site, error )
            assert site in fired and code in ( 0, gate.REFUSAL_EXIT )
            crashed = [ ln for ln in lines if ln.startswith( "[doc-lint] GATE CRASHED, commit allowed: " ) ]
            added   = [ ln for ln in lines if ln not in quiet[ which ][ 1 ] and ( "WARNING" in ln or "REFUSED" in ln ) ]
            if crashed: assert code == 0
            assert crashed or added, f"{site} failed with {type( error ).__name__} and the gate said nothing about it"
            found.append( CRASH if crashed else SAID )
        answers[ site ] = tuple( found )
    assert answers == { site: EXPECTED[ site ] for site in on_path }
