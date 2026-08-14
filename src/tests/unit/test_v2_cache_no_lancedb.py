#!/usr/bin/env python3
"""
Storage guard for CJ Flow v2 (unit C2) — Rick's ruling 2026-08-14: "LanceDB is
out, do not use in any way shape or form. We are going with PostgreSQL +
embeddings." (Handoff §3.C R-C4, ratified with amendment.)

WHAT THIS GUARDS, AND WHAT IT DELIBERATELY DOES NOT — read before "strengthening":

    The ban is on USING the LanceDB store, which in this codebase is the module
    `cosa.memory.lancedb_solution_manager`. This test asserts that module is
    absent from v2's TRANSITIVE import graph — so a v2 module cannot reach it,
    not even through a delegating shim (the §4 option-1 threat).

    It does NOT — and MUST NOT — assert the third-party `lancedb` PACKAGE is
    absent. Importing SolutionSnapshot (which v2 must, to hand the executor a
    replay-ready snapshot) transitively pulls the lancedb package via the memory
    layer's other LanceDB-era table modules — ~55 modules — with NO way to avoid
    it while replaying a snapshot at all. v1's whole memory layer already carries
    it. A guard asserting "no lancedb package" is UNSATISFIABLE the moment you
    replay a snapshot, and an unsatisfiable guard gets deleted by whoever hits it
    next week. Ratified by Mr Radio 🦉 2026-08-14 (verified: the package is
    present, the manager module is not).

    ⇒ Guard the MODULE, transitively. Never the package.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

BANNED_MODULE = "cosa.memory.lancedb_solution_manager"

_LUPIN_ROOT = Path( os.environ[ "LUPIN_ROOT" ] )
_SRC        = _LUPIN_ROOT / "src"
_V2_DIR     = _SRC / "cosa" / "rest" / "v2"


def test_lancedb_solution_manager_absent_from_v2_transitive_closure():
    """
    Import cosa.rest.v2.cache in a CLEAN interpreter and assert the banned
    manager module never entered sys.modules — the true runtime transitive graph,
    including relative and load-time imports.

    Proven able to fail: adding `import cosa.memory.lancedb_solution_manager` to
    cache.py makes this list non-empty and reds the test (receipt in the unit
    report). Reverting restores green.
    """
    env = dict( os.environ )
    env[ "PYTHONPATH" ] = os.pathsep.join( [ str( _SRC ), env.get( "PYTHONPATH", "" ) ] )
    probe = (
        "import cosa.rest.v2.cache, sys; "
        "print( [ m for m in sys.modules if 'lancedb_solution_manager' in m ] )"
    )
    completed = subprocess.run(
        [ sys.executable, "-c", probe ],
        env=env, capture_output=True, text=True, check=True,
    )
    leaked = completed.stdout.strip().splitlines()[ -1 ] if completed.stdout.strip() else "[]"
    assert leaked == "[]", (
        f"{BANNED_MODULE} reached v2's transitive import graph: {leaked}\n"
        f"stderr: {completed.stderr}"
    )


def _v2_source_files():
    return sorted( _V2_DIR.glob( "*.py" ) )


def _imported_names( path ):
    """Yield every top-level imported dotted name in a source file (Import + ImportFrom)."""
    tree = ast.parse( path.read_text() )
    for node in ast.walk( tree ):
        if isinstance( node, ast.Import ):
            for alias in node.names:
                yield alias.name
        elif isinstance( node, ast.ImportFrom ):
            if node.module is not None:
                yield node.module


def test_no_v2_source_file_imports_lancedb_directly():
    """
    AST-scan every file under src/cosa/rest/v2/ and assert none imports the
    lancedb package or the banned manager DIRECTLY — the §9 "walk the v2 source
    with ast" check, covering a lazy/in-function import the closure test's
    import-time snapshot would miss. Scoped to v2 source, so the memory layer's
    legitimate lancedb imports are out of scope by construction.

    Proven able to fail: adding `import lancedb` (or an import of the manager) to
    any v2 file trips this (receipt in the unit report).
    """
    offenders = []
    for path in _v2_source_files():
        for name in _imported_names( path ):
            if name == "lancedb" or name.startswith( "lancedb." ) or "lancedb_solution_manager" in name:
                offenders.append( f"{path.name}: {name}" )
    assert offenders == [], f"v2 source directly imports LanceDB: {offenders}"
