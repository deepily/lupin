"""
Index specification: which directories of a repository are indexed, and which are skipped.

The skip rules match directory names in the path RELATIVE to the index root, so a fixture
repository that lives under a `tests/` directory is still indexed when it is the root.
"""
import hashlib
import os
import pathlib
import subprocess

LUPIN_PY_PACKAGES = ( "cosa", "lupin_cli", "lupin_mcp", "lupin_app", "lupin_arbiter_app", "lupin_model_server", "scripts" )
LUPIN_JS_DIR      = "src/lupin_app/static/js"
SKIP_PARTS        = frozenset( { "tests", "migrations", ".venv", "vendor", "node_modules", "rnd", "__pycache__", ".git" } )
DART_SKIP_PARTS   = frozenset( { "generated", ".dart_tool", "build" } )
SKIP_SUFFIXES     = ( ".d.ts", ".min.js", ".g.dart", ".freezed.dart" )


class NotARepo( Exception ):
    """Raised when a directory is not inside a git working tree."""


class IndexSpec:
    """
    What to index under one root.

    Requires:
        - root is an existing directory
    Ensures:
        - py_roots, js_roots and dart_roots are absolute directories that exist
        - module_base is the directory dotted Python module names are taken relative to
    """

    def __init__( self, root, name, py_roots, js_roots, dart_roots, module_base, skip_parts ):
        self.root        = pathlib.Path( root )
        self.name        = name
        self.py_roots    = tuple( py_roots )
        self.js_roots    = tuple( js_roots )
        self.dart_roots  = tuple( dart_roots )
        self.module_base = pathlib.Path( module_base )
        self.skip_parts  = frozenset( skip_parts )


def git_toplevel( start=None ):
    """
    Return the git working-tree root that contains `start` (default: the current directory).

    Requires:
        - git is on PATH
    Ensures:
        - returns an absolute pathlib.Path
    Raises:
        - NotARepo if `start` is not inside a git working tree
    """
    cwd = str( start ) if start is not None else os.getcwd()
    res = subprocess.run( [ "git", "rev-parse", "--show-toplevel" ], cwd=cwd, capture_output=True, text=True )
    if res.returncode != 0: raise NotARepo( f"not a git working tree: {cwd}" )
    return pathlib.Path( res.stdout.strip() )


def is_lupin_tree( root ):
    """
    Ensures:
        - True iff `root` holds the lupin source layout (src/cosa and src/lupin_mcp)
    """
    root = pathlib.Path( root )
    return ( root / "src" / "cosa" ).is_dir() and ( root / "src" / "lupin_mcp" ).is_dir()


def spec_for( root ):
    """
    Build the IndexSpec for a repository root.

    Ensures:
        - a lupin tree indexes the lupin packages and the web client's js directory
        - a Flutter tree (pubspec.yaml + lib/) indexes lib/ as Dart
        - any other tree indexes every Python and JS/TS file under the root
    """
    root = pathlib.Path( root ).resolve()
    skip = set( SKIP_PARTS )
    if is_lupin_tree( root ):
        py  = [ root / "src" / p for p in LUPIN_PY_PACKAGES ]
        js  = [ root / LUPIN_JS_DIR ]
        return IndexSpec( root, root.name, [ p for p in py if p.is_dir() ], [ p for p in js if p.is_dir() ], [], root / "src", skip )
    if ( root / "pubspec.yaml" ).is_file() and ( root / "lib" ).is_dir():
        return IndexSpec( root, root.name, [], [], [ root / "lib" ], root, skip | DART_SKIP_PARTS )
    return IndexSpec( root, root.name, [ root ], [ root ], [], root, skip )


def skipped( rel_path, skip_parts ):
    """
    Ensures:
        - True iff a DIRECTORY component of the relative path is in skip_parts
        - the file name itself is never matched, only checked against SKIP_SUFFIXES
    """
    rel = pathlib.PurePosixPath( rel_path )
    if any( part in skip_parts for part in rel.parts[ :-1 ] ): return True
    return rel.name.endswith( SKIP_SUFFIXES )


def iter_files( spec, roots, suffixes ):
    """
    Ensures:
        - returns a sorted list of absolute paths under `roots` with one of `suffixes`
        - a path is dropped when it would be skipped relative to spec.root
        - each path appears once even when roots overlap
    """
    seen = set()
    for base in roots:
        for p in base.rglob( "*" ):
            if p.suffix not in suffixes or not p.is_file(): continue
            if skipped( p.relative_to( spec.root ).as_posix(), spec.skip_parts ): continue
            seen.add( p )
    return sorted( seen )


def all_files( spec ):
    """
    Ensures:
        - returns the full indexed population: Python, JS/TS and Dart files, one sorted list
        - build() and the freshness check both read this function, so they never disagree
    """
    return sorted( set( iter_files( spec, spec.py_roots, { ".py" } ) )
                   | set( iter_files( spec, spec.js_roots, { ".js", ".ts", ".tsx" } ) )
                   | set( iter_files( spec, spec.dart_roots, { ".dart" } ) ) )


def manifest( spec ):
    """
    Ensures:
        - returns a hex digest of the sorted (relative path, mtime_ns, size) set of indexed files
        - an added, deleted, resized or touched file changes the digest
    """
    h = hashlib.sha1()
    for p in all_files( spec ):
        st = p.stat()
        h.update( f"{p.relative_to( spec.root ).as_posix()}\0{st.st_mtime_ns}\0{st.st_size}\n".encode( "utf-8" ) )
    return h.hexdigest()
