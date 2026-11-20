"""
Census guard: only `scratch_db` registers SQLite renderings of Postgres column types.

A rendering registered with `compiles` is global to the process, and the last module imported wins.
Several test modules each registering their own made the coverage of `scratch_db` depend on import order.
A test module that needs the hooks imports `cosa.research.preference_replay.scratch_db` and registers none.
"""
import ast
import subprocess

import cosa.utils.util as du

SHARED   = "src/cosa/research/preference_replay/scratch_db.py"
COMPILER = "sqlalchemy.ext.compiler"


def findings( source ):
    """
    Every place a source file registers or imports the compiler hook, as ( line, what ) pairs.

    Flags an import of sqlalchemy.ext.compiler in either form. Flags any call or decorator named compiles.
    So a dotted path does not hide a registration.
    """
    found = []
    for node in ast.walk( ast.parse( source ) ):
        if isinstance( node, ast.ImportFrom ) and node.module == COMPILER:
            found.append( ( node.lineno, f"imports from {COMPILER}" ) )
        elif isinstance( node, ast.Import ) and any( alias.name == COMPILER for alias in node.names ):
            found.append( ( node.lineno, f"imports {COMPILER}" ) )
        elif isinstance( node, ast.Call ):
            name = node.func.id if isinstance( node.func, ast.Name ) else node.func.attr if isinstance( node.func, ast.Attribute ) else None
            if name == "compiles": found.append( ( node.lineno, "calls compiles" ) )
    return found


def _tracked_python_files():
    """The tracked .py files, from git, so a vendored virtualenv is never in the population."""
    root = du.get_project_root()
    return subprocess.run( [ "git", "ls-files", "*.py" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()


def test_the_finder_can_find_each_way_to_register_a_hook():
    """Positive control: each spelling of the registration is flagged."""
    assert findings( 'from sqlalchemy.ext.compiler import compiles\n@compiles( JSONB, "sqlite" )\ndef f( e, c, **k ): return "JSON"' ) == [
        ( 1, "imports from sqlalchemy.ext.compiler" ), ( 2, "calls compiles" ) ]
    assert findings( 'import sqlalchemy.ext.compiler\n@sqlalchemy.ext.compiler.compiles( Vector, "sqlite" )\ndef g(): pass' ) == [
        ( 1, "imports sqlalchemy.ext.compiler" ), ( 2, "calls compiles" ) ]
    assert findings( 'from sqlalchemy.ext.compiler import compiles as register\n@register( JSONB, "sqlite" )\ndef h(): pass' ) == [
        ( 1, "imports from sqlalchemy.ext.compiler" ) ]


def test_the_finder_passes_a_module_that_imports_the_shared_hooks():
    """A module that imports scratch_db, and one that uses the word in text, are clean."""
    assert findings( 'from cosa.research.preference_replay import scratch_db  # noqa: F401\nnote = "compiles fine"\n' ) == []


def test_the_census_walks_a_real_population_that_includes_the_shared_module():
    """Assert the loop has something to walk, and that the shared module registers both hooks."""
    files = _tracked_python_files()
    assert len( files ) > 1000, f"only {len( files )} tracked .py files walked"
    assert SHARED in files
    with open( f"{du.get_project_root()}/{SHARED}", encoding="utf-8" ) as handle:
        assert len( [ hit for hit in findings( handle.read() ) if hit[ 1 ] == "calls compiles" ] ) == 2, "scratch_db registers the JSONB and Vector hooks"


def test_every_module_but_scratch_db_leaves_the_sqlite_type_hooks_to_it():
    """No other tracked .py file imports the compiler hook or registers one."""
    root = du.get_project_root()
    bad  = {}
    for rel in _tracked_python_files():
        if rel == SHARED: continue
        with open( f"{root}/{rel}", encoding="utf-8" ) as handle:
            hits = findings( handle.read() )
        if hits: bad[ rel ] = hits
    assert not bad, "import cosa.research.preference_replay.scratch_db instead of registering a hook:\n" + "\n".join(
        f"  {rel}: {hits}" for rel, hits in sorted( bad.items() ) )
