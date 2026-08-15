#!/usr/bin/env python3
"""
Storage guard for CJ Flow v2 (unit C2) — Rick's ruling 2026-08-14: "LanceDB is
out, do not use in any way shape or form. We are going with PostgreSQL +
embeddings." (Handoff §3.C R-C4, ratified with amendment.)

WHAT THIS GUARDS, AND WHAT IT DELIBERATELY DOES NOT — read before "strengthening":

    The ban is on USING the LanceDB store. In this codebase that store is reached
    through TWO modules that each call `lancedb.connect()` just as hard:
      - `cosa.memory.lancedb_solution_manager` — the snapshot store manager.
      - `cosa.memory.query_log_table`          — the query-log sink (R-D7): its
        __init__ does `lancedb.connect()` (query_log_table.py:72) and log_query
        writes via `table.add()` (:297). The v2 handoff §7 sink #1 would have
        used it; extending the ban here means someone wiring that sink is caught
        (added 2026-08-15, row 03d41dd8 follow-on — the prior guard banned the
        manager module only, so the query-log sink would have slipped past).

    This test asserts BOTH modules are absent from v2's TRANSITIVE import graph —
    so a v2 module cannot reach either, not even through a delegating shim (the
    §4 option-1 threat).

    It does NOT — and MUST NOT — assert the third-party `lancedb` PACKAGE is
    absent. Importing SolutionSnapshot (which v2 must, to hand the executor a
    replay-ready snapshot) transitively pulls the lancedb package via the memory
    layer's other LanceDB-era table modules — ~55 modules — with NO way to avoid
    it while replaying a snapshot at all. v1's whole memory layer already carries
    it. A guard asserting "no lancedb package" is UNSATISFIABLE the moment you
    replay a snapshot, and an unsatisfiable guard gets deleted by whoever hits it
    next week. Ratified by Mr Radio 🦉 2026-08-14 (verified: the package is
    present, the manager module is not).

    ⇒ Guard the MODULES, transitively. Never the package.

    Both banned modules are verified ABSENT from v2's cache closure and the
    two-tier closure at add time, so the ban is satisfiable; and each is proven
    detectable — importing a module that DOES pull it (e.g. todo_fifo_queue pulls
    query_log_table) makes the leak list non-empty.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

# The LanceDB store is reached through these modules; both connect just as hard.
BANNED_MODULES = (
    "cosa.memory.lancedb_solution_manager",
    "cosa.memory.query_log_table",
)
# Substring tokens used for sys.modules membership (dotted names contain these).
_BANNED_TOKENS = ( "lancedb_solution_manager", "query_log_table" )

_LUPIN_ROOT = Path( os.environ[ "LUPIN_ROOT" ] )
_SRC        = _LUPIN_ROOT / "src"
_V2_DIR     = _SRC / "cosa" / "rest" / "v2"


def _leaked_banned_modules( import_target ):
    """
    Import `import_target` in a CLEAN interpreter and return the list of banned
    modules that entered sys.modules — the true runtime transitive graph,
    including relative and load-time imports.

    Requires:
        - import_target is an importable dotted module name
    Ensures:
        - returns the printed leak-list string ("[]" when none leaked)
        - raises CalledProcessError if the probe import itself fails
    """
    env = dict( os.environ )
    env[ "PYTHONPATH" ] = os.pathsep.join( [ str( _SRC ), env.get( "PYTHONPATH", "" ) ] )
    probe = (
        f"import {import_target}, sys; "
        f"print( [ m for m in sys.modules if any( t in m for t in {list( _BANNED_TOKENS )!r} ) ] )"
    )
    completed = subprocess.run(
        [ sys.executable, "-c", probe ],
        env=env, capture_output=True, text=True, check=True,
    )
    leaked = completed.stdout.strip().splitlines()[ -1 ] if completed.stdout.strip() else "[]"
    return leaked, completed.stderr


def test_banned_lancedb_modules_absent_from_v2_transitive_closure():
    """
    Import cosa.rest.v2.cache in a CLEAN interpreter and assert NEITHER banned
    LanceDB module (the snapshot manager OR the query-log sink) entered
    sys.modules.

    Proven able to fail: adding `import cosa.memory.lancedb_solution_manager` OR
    `import cosa.memory.query_log_table` to cache.py makes this list non-empty
    and reds the test. Reverting restores green. (Detector proven live: pointing
    the same probe at cosa.rest.todo_fifo_queue — which DOES pull query_log_table
    — returns ['cosa.memory.query_log_table'].)
    """
    leaked, stderr = _leaked_banned_modules( "cosa.rest.v2.cache" )
    assert leaked == "[]", (
        f"a banned LanceDB module ({', '.join( BANNED_MODULES )}) reached v2's "
        f"transitive import graph: {leaked}\nstderr: {stderr}"
    )


def test_banned_lancedb_modules_absent_from_two_tier_module_closure():
    """
    The extracted module cosa.memory.two_tier_question_search is what v2 now reuses
    (row 29e98243). Guard it DIRECTLY, not only through v2/cache: import it in a
    CLEAN interpreter and assert NEITHER banned LanceDB module entered sys.modules.
    Importing SolutionSnapshot still pulls the third-party lancedb PACKAGE (allowed);
    the MODULES must stay out.

    Proven able to fail: an `import cosa.memory.lancedb_solution_manager` OR an
    `import cosa.memory.query_log_table` in the new module makes this list
    non-empty and reds.
    """
    leaked, stderr = _leaked_banned_modules( "cosa.memory.two_tier_question_search" )
    assert leaked == "[]", (
        f"a banned LanceDB module ({', '.join( BANNED_MODULES )}) reached "
        f"two_tier_question_search's transitive import graph: {leaked}\nstderr: {stderr}"
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
    lancedb package OR either banned LanceDB module DIRECTLY — the §9 "walk the v2
    source with ast" check, covering a lazy/in-function import the closure test's
    import-time snapshot would miss. Scoped to v2 source, so the memory layer's
    legitimate lancedb imports are out of scope by construction.

    Proven able to fail: adding `import lancedb`, an import of the manager, or an
    import of query_log_table to any v2 file trips this.
    """
    offenders = []
    for path in _v2_source_files():
        for name in _imported_names( path ):
            is_banned = (
                name == "lancedb"
                or name.startswith( "lancedb." )
                or any( token in name for token in _BANNED_TOKENS )
            )
            if is_banned:
                offenders.append( f"{path.name}: {name}" )
    assert offenders == [], f"v2 source directly imports a banned LanceDB target: {offenders}"
