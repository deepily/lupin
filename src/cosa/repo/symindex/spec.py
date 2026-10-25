"""
Index specification: which directories of a repository are indexed, and which are skipped.

The skip rules match directory names in the path relative to the index root.
A fixture repository under a `tests/` directory is therefore still indexed when it is the root.
"""
import hashlib
import os
import pathlib
import subprocess

LUPIN_PY_PACKAGES = ( "cosa", "lupin_cli", "lupin_mcp", "lupin_app", "lupin_arbiter_app", "lupin_model_server", "scripts" )
LUPIN_JS_DIRS     = ( "src/lupin_app/static/js", "src/scripts", "src/cosa/repo/symindex", "src/conf" )          # the script roots of a lupin tree; test_script_files_census names what is left out
SKIP_PARTS        = frozenset( { "tests", "migrations", ".venv", "vendor", "node_modules", "rnd", "__pycache__", ".git" } )
DART_SKIP_PARTS   = frozenset( { "generated", ".dart_tool", "build" } )
SKIP_SUFFIXES     = ( ".d.ts", ".min.js", ".g.dart", ".freezed.dart" )
SCRIPT_SUFFIXES   = ( ".js", ".mjs", ".cjs", ".ts", ".tsx" )          # what a script file is, for every reader of the index
TESTS_DIRS        = ( "src/tests", "src/cosa/tests" )                  # where the tests spec reads: neither is under any LUPIN_PY_PACKAGES root
SUFFIX_LANG       = { ".py": "py", ".js": "ts", ".mjs": "ts", ".cjs": "ts", ".ts": "ts", ".tsx": "ts", ".dart": "dart" }          # the `lang` of a record, by suffix


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

    def __init__( self, root, name, py_roots, js_roots, dart_roots, module_base, skip_parts, scopes=None ):
        """
        Store the index spec fields, converted to Path, tuples and a frozenset.

        Requires:
            - py_roots, js_roots and dart_roots are iterables of directories
            - skip_parts is an iterable of directory names to leave out
            - scopes is None for the build's own search scopes, or a tuple of record scopes this spec publishes as searchable

        Ensures:
            - root and module_base are pathlib.Path; the three root sets are tuples; skip_parts is a frozenset
            - no directory is checked here; spec_for lists only the ones that exist
        """
        self.root        = pathlib.Path( root )
        self.name        = name
        self.py_roots    = tuple( py_roots )
        self.js_roots    = tuple( js_roots )
        self.dart_roots  = tuple( dart_roots )
        self.module_base = pathlib.Path( module_base )
        self.skip_parts  = frozenset( skip_parts )
        self.scopes      = None if scopes is None else tuple( scopes )


def git_toplevel( start=None ):
    """
    Return the git working-tree root that contains `start` (default: the current directory).

    Requires:
        - git is on `PATH`
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
    Say whether a directory is a lupin checkout.

    Ensures:
        - True iff `root` holds the lupin source layout (src/cosa and src/lupin_mcp)
    """
    root = pathlib.Path( root )
    return ( root / "src" / "cosa" ).is_dir() and ( root / "src" / "lupin_mcp" ).is_dir()


def spec_for( root ):
    """
    Build the IndexSpec for a repository root.

    Ensures:
        - a lupin tree indexes the lupin packages and the script roots of LUPIN_JS_DIRS (the web client's js directory, src/scripts, the index's own extractors and src/conf)
        - a Flutter tree (pubspec.yaml + lib/) indexes lib/ as Dart
        - any other tree indexes every Python, JavaScript and TypeScript file under the root
    """
    root = pathlib.Path( root ).resolve()
    skip = set( SKIP_PARTS )
    if is_lupin_tree( root ):
        py  = [ root / "src" / p for p in LUPIN_PY_PACKAGES ]
        js  = [ root / d for d in LUPIN_JS_DIRS ]
        return IndexSpec( root, root.name, [ p for p in py if p.is_dir() ], [ p for p in js if p.is_dir() ], [], root / "src", skip )
    if ( root / "pubspec.yaml" ).is_file() and ( root / "lib" ).is_dir():
        return IndexSpec( root, root.name, [], [], [ root / "lib" ], root, skip | DART_SKIP_PARTS )
    return IndexSpec( root, root.name, [ root ], [ root ], [], root, skip )


def tests_spec( root ):
    """
    Build the IndexSpec of a repository's test files.

    Ensures:
        - a lupin tree reads Python and script files under src/tests and src/cosa/tests, whichever exist
        - any other tree reads a `tests` or `src/tests` directory when it has one, and nothing otherwise
        - skip_parts is the main set less `tests`, so a test file is indexed here and nowhere else
        - the spec publishes the scope `test` as its searchable scope
    """
    root  = pathlib.Path( root ).resolve()
    names = TESTS_DIRS if is_lupin_tree( root ) else ( "tests", "src/tests" )
    dirs  = [ root / n for n in names if ( root / n ).is_dir() ]
    base  = root / "src" if is_lupin_tree( root ) else root
    return IndexSpec( root, root.name, dirs, dirs, [], base, set( SKIP_PARTS ) - { "tests" }, scopes=( "test", ) )


def is_test_path( rel_path ):
    """
    Say whether a relative path lies in a tests directory.

    Ensures:
        - True iff a directory component of the path is named `tests`
        - the file name itself is never matched
    """
    return "tests" in pathlib.PurePosixPath( rel_path ).parts[ :-1 ]


def skip_rule( rel_path, skip_parts ):
    """
    Name the rule that excludes a relative path from the index.

    Ensures:
        - returns the first directory component of the path that is in skip_parts
        - otherwise the SKIP_SUFFIXES entry the file name ends with
        - otherwise None: the path is not skipped
        - the file name itself is never matched against skip_parts
    """
    rel  = pathlib.PurePosixPath( rel_path )
    part = next( ( p for p in rel.parts[ :-1 ] if p in skip_parts ), None )
    if part is not None: return part
    return next( ( s for s in SKIP_SUFFIXES if rel.name.endswith( s ) ), None )


def skipped( rel_path, skip_parts ):
    """
    Say whether a relative path is excluded from the index.

    Ensures:
        - True iff skip_rule names a rule for it: a directory component in skip_parts, or a SKIP_SUFFIXES ending
        - the file name itself is never matched, only checked against SKIP_SUFFIXES
    """
    return skip_rule( rel_path, skip_parts ) is not None


def iter_files( spec, roots, suffixes, skipped_into=None ):
    """
    List the indexable files under some roots.

    Requires:
        - skipped_into is None, or a dict the call fills with { relative path: rule } for each file it drops

    Ensures:
        - returns a sorted list of absolute paths under `roots` with one of `suffixes`
        - a path is dropped when it would be skipped relative to spec.root
        - each path appears once even when roots overlap
        - a dropped file with one of `suffixes` is recorded in skipped_into under the rule that dropped it, once
    """
    seen = set()
    for base in roots:
        for p in base.rglob( "*" ):
            if p.suffix not in suffixes or not p.is_file(): continue
            rel  = p.relative_to( spec.root ).as_posix()
            rule = skip_rule( rel, spec.skip_parts )
            if rule is not None:
                if skipped_into is not None: skipped_into[ rel ] = rule
                continue
            seen.add( p )
    return sorted( seen )


def all_files( spec ):
    """
    List every file the index covers.

    Ensures:
        - returns the full indexed population: Python, JavaScript, TypeScript and Dart files, one sorted list
        - build() and the freshness check both read this function, so they never disagree
    """
    return sorted( set( iter_files( spec, spec.py_roots, { ".py" } ) )
                   | set( iter_files( spec, spec.js_roots, set( SCRIPT_SUFFIXES ) ) )
                   | set( iter_files( spec, spec.dart_roots, { ".dart" } ) ) )


def manifest( spec ):
    """
    Return a digest that changes whenever the set of indexed files changes.

    Ensures:
        - returns a hex digest of the sorted (relative path, mtime_ns, size) set of indexed files
        - an added, deleted, resized or touched file changes the digest
    """
    h = hashlib.sha1()
    for p in all_files( spec ):
        st = p.stat()
        h.update( f"{p.relative_to( spec.root ).as_posix()}\0{st.st_mtime_ns}\0{st.st_size}\n".encode( "utf-8" ) )
    return h.hexdigest()
