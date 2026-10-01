"""
JavaScript and TypeScript symbol extraction with the TypeScript compiler, run under Node.

The compiler is already a dependency of the repository (the typecheck gate runs it), so this
adds no package. `node` is found by absolute path because the cosa-voice subprocess may not
have nvm's bin directory on PATH.
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
    Ensures:
        - returns the absolute path of a node executable, searched in this order:
          $LUPIN_NODE, PATH, then the newest ~/.nvm/versions/node/*/bin/node
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
    Extract the function, class and method symbols of JS/TS files.

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
    node = find_node()
    ts   = find_typescript( root )
    req  = json.dumps( { "root": str( root ), "files": [ str( f ) for f in files ], "typescript": str( ts ) } )
    res  = subprocess.run( [ node, str( EXTRACTOR ) ], input=req, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT )
    if res.returncode != 0: raise RuntimeError( f"ts_extract.js failed: {res.stderr.strip()[ :400 ]}" )
    out = []
    for r in json.loads( res.stdout ):
        out.append( { "lang": "ts", "file": r[ "file" ], "name": r[ "name" ], "kind": r[ "kind" ], "sig": r[ "sig" ],
                      "doc": r[ "doc" ], "pin": r[ "pin" ], "line": r[ "line" ], "public": True } )
    return out
