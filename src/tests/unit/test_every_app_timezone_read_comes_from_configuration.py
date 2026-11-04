"""
Census guard: `app timezone` is read through one reader, with no default or literal zone.

Rick's rule: the zone comes only from configuration. A default= or a zone name written
beside the read is a second source, and it answers the same with the key absent. The shared reader
is `cosa.config.app_timezone.get_app_timezone`.
"""
import ast
import re
import subprocess

import pytest

import cosa.utils.util as du

KEY      = "app timezone"
READER   = "src/cosa/config/app_timezone.py"
IANA     = re.compile( r"^(UTC|[A-Z][A-Za-z_]+(/[A-Za-z_+\-0-9]+)+)$" )
SKIPPED  = ( "/tests/", "/rnd/", "/.venv/", "/history/", "/test_" )


def findings( source ):
    """Every way a source file breaks the rule, as ( line, what ) pairs.

    Flags three things. A call naming the key with default=. A call naming the key that is not
    get_required. Any bare string that is a zone name ( a docstring is not a bare string ).
    """
    tree  = ast.parse( source )
    found = []
    for node in ast.walk( tree ):
        if isinstance( node, ast.Call ) and node.args and isinstance( node.args[ 0 ], ast.Constant ) and node.args[ 0 ].value == KEY:
            if any( kw.arg == "default" for kw in node.keywords ):
                found.append( ( node.lineno, "default= on the key" ) )
            if not ( isinstance( node.func, ast.Attribute ) and node.func.attr == "get_required" ):
                found.append( ( node.lineno, "read not through get_required" ) )
    docstrings = { id( n.body[ 0 ].value ) for n in ast.walk( tree )
                   if isinstance( n, ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef ) )
                   and n.body and isinstance( n.body[ 0 ], ast.Expr ) and isinstance( n.body[ 0 ].value, ast.Constant ) }
    for node in ast.walk( tree ):
        if isinstance( node, ast.Constant ) and isinstance( node.value, str ) and id( node ) not in docstrings and IANA.match( node.value ):
            found.append( ( node.lineno, f"literal zone {node.value!r}" ) )
    return found


def _tracked_files_naming_the_key():
    """Tracked non-test .py files naming the key, and the whole population walked."""
    root  = du.get_project_root()
    files = subprocess.run( [ "git", "ls-files", "*.py" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    files = [ f for f in files if not any( skip in "/" + f for skip in SKIPPED ) ]
    named = []
    for rel in files:
        with open( f"{root}/{rel}", encoding="utf-8" ) as handle:
            if KEY in handle.read(): named.append( rel )
    return named, files


def test_the_finder_can_find_each_way_to_break_the_rule():
    """Positive control: a planted default=, a bare get, and a literal zone are each flagged."""
    assert findings( 'x = cfg.get( "app timezone", default="America/New_York" )' ) == [
        ( 1, "default= on the key" ), ( 1, "read not through get_required" ), ( 1, "literal zone 'America/New_York'" ) ]
    assert findings( 'x = cfg.get( "app timezone" )' ) == [ ( 1, "read not through get_required" ) ]
    assert findings( 'zone = "Europe/Madrid"' ) == [ ( 1, "literal zone 'Europe/Madrid'" ) ]
    assert findings( 'zone = "UTC"' ) == [ ( 1, "literal zone 'UTC'" ) ]


def test_the_finder_passes_the_shape_the_rule_requires():
    """The shared reader call, a docstring naming a zone, and ordinary strings are all clean."""
    clean = 'def f( cfg ):\n    """Reads the zone, e.g. America/New_York."""\n    return cfg.get_required( "app timezone" )\n'
    assert findings( clean ) == []
    assert findings( 'path = "src/cosa/foo"\nname = "a/b c"' ) == []


def test_the_census_walks_a_real_population_that_includes_the_reader():
    """Assert the loop will find something before it loops."""
    named, files = _tracked_files_naming_the_key()
    assert len( files ) > 1000, f"only {len( files )} tracked .py files walked"
    assert READER in named


def test_every_tracked_file_that_names_the_key_reads_it_with_no_default_and_no_literal_zone():
    """No tracked non-test .py file gives `app timezone` a default or a literal zone."""
    named, _ = _tracked_files_naming_the_key()
    root     = du.get_project_root()
    bad      = {}
    for rel in named:
        with open( f"{root}/{rel}", encoding="utf-8" ) as handle:
            hits = findings( handle.read() )
        if hits: bad[ rel ] = hits

    assert not bad, "the zone must come from configuration only:\n" + "\n".join(
        f"  {rel}:{line} {what}" for rel, hits in sorted( bad.items() ) for line, what in hits )
