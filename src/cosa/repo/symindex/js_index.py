"""
JavaScript and TypeScript symbol extraction with the TypeScript compiler, run under Node.

The compiler is already a dependency of the repository (the typecheck gate runs it), so this
adds no package. `node` is found by absolute path because the cosa-voice subprocess may not
have nvm's bin directory on `PATH`.
"""
import glob
import json
import os
import pathlib
import shutil
import subprocess

from cosa.repo.symindex.errors import DependencyMissing

EXTRACTOR = pathlib.Path( __file__ ).resolve().with_name( "ts_extract.js" )
TIMEOUT   = 300


def find_node():
    """
    Find a node executable and return its absolute path.

    Ensures:
        - returns the absolute path of a node executable, searched in this order:
          $LUPIN_NODE, `PATH`, then the newest ~/.nvm/versions/node/*/bin/node
    Raises:
        - DependencyMissing( "node" ) when none is found
    """
    env = os.environ.get( "LUPIN_NODE" )
    if env and os.access( env, os.X_OK ): return env
    found = shutil.which( "node" )
    if found: return found
    nvm = sorted( glob.glob( os.path.expanduser( "~/.nvm/versions/node/*/bin/node" ) ) )
    if nvm: return nvm[ -1 ]
    raise DependencyMissing( "node", "not on PATH, $LUPIN_NODE unset, no ~/.nvm install" )


def find_typescript( root ):
    """
    Find the directory of the `typescript` package for an index root.

    Ensures:
        - returns the directory of the `typescript` package: <root>/node_modules/typescript,
          else the one beside the main checkout found through $LUPIN_ROOT
    Raises:
        - DependencyMissing( "typescript" ) when neither exists
    """
    cands = [ pathlib.Path( root ) / "node_modules" / "typescript" ]
    if os.environ.get( "LUPIN_ROOT" ): cands.append( pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "node_modules" / "typescript" )
    for c in cands:
        if ( c / "package.json" ).is_file(): return c
    raise DependencyMissing( "typescript", f"no node_modules/typescript under {cands[ 0 ]}" )


def typescript_version( ts_dir ):
    """Ensures: returns the version string in the package's package.json."""
    return json.loads( ( ts_dir / "package.json" ).read_text( encoding="utf-8" ) )[ "version" ]


def extract_js( root, files ):
    """
    Extract the function, class and method symbols of JavaScript and TypeScript files.

    Requires:
        - files are absolute paths under root
    Ensures:
        - returns a list of symbol dicts (lang "ts", file, name, kind, sig, doc, pin, line, public)
        - private and protected members are not returned
        - an empty file list returns [] without starting node
    Raises:
        - DependencyMissing when node or typescript is absent
        - RuntimeError when the compiler script exits non-zero
    """
    if not files: return []
    out = []
    for r in _run( root, files, {} ):
        out.append( { "lang": "ts", "file": r[ "file" ], "name": r[ "name" ], "kind": r[ "kind" ], "sig": r[ "sig" ],
                      "doc": r[ "doc" ], "pin": r[ "pin" ], "line": r[ "line" ], "public": True } )
    return out


def _run( root, files, extra ):
    """
    Run the compiler script once and return its decoded JSON.

    Requires:
        - files is a non-empty list of absolute paths under root
    Raises:
        - DependencyMissing when node or typescript is absent
        - RuntimeError when the compiler script exits non-zero
    """
    node = find_node()
    ts   = find_typescript( root )
    req  = json.dumps( { "root": str( root ), "files": [ str( f ) for f in files ], "typescript": str( ts ), **extra } )
    res  = subprocess.run( [ node, str( EXTRACTOR ) ], input=req, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT )
    if res.returncode != 0: raise RuntimeError( f"ts_extract.js failed: {res.stderr.strip()[ :400 ]}" )
    return json.loads( res.stdout )


def extract_js_shapes( root, files, public_only=False ):
    """
    Extract the structural shape of every function-like definition in script files.

    Requires:
        - files are absolute paths under root
    Ensures:
        - returns { "scanned": [ file relative to root ], "skipped": [ file ], "defs": [ { file, name, kinds } ] }
        - a file the parser reported errors for is in skipped and contributes no definition
        - kinds is the pre-order list of node kind names of the definition, identifier names and literal values erased
        - nested functions are named <parent>.<locals>.<name>; an anonymous callback is walked but not reported
        - private and protected members, including functions held in a private or protected class property,
          and nested functions, are returned unless public_only
        - an empty file list returns an empty result without starting node
    Raises:
        - DependencyMissing when node or typescript is absent
        - RuntimeError when the compiler script exits non-zero
    """
    if not files: return { "scanned": [], "skipped": [], "defs": [] }
    return _run( root, files, { "mode": "shapes", "public_only": bool( public_only ) } )
