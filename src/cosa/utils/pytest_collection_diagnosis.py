"""
Turn a pytest collection error into a diagnosis instead of silence — row bc83f2df.

WHY THIS EXISTS. A collection error is not a failing test. It is the suite never
running. Cheech hit two of them in one afternoon from different causes, and each was
diagnosed from scratch, because nothing carried the diagnosis forward. That repetition
is the defect this module exists to end — not either individual cause, both of which
were fixed the same day.

WHAT WAS MEASURED (2026-08-17, both shapes built deliberately and run):

| shape | where the error lands | exit | junit written? | hooks fired | what the tooling said |
|---|---|---|---|---|---|
| A | a TEST module (`ModuleNotFoundError`) | 2 | yes, `tests=1 errors=1` | collectreport, collection_finish, sessionfinish, cmdline_main | **"FAILED"** |
| B | a CONFTEST (`TypeError`, arg count) | 4 | **no** | **none at all** | "NOT EXECUTED" |

Both readings are wrong in their own direction:

  · Shape A is reported as **FAILED**, byte-identical to a genuine red. It is not a red —
    nothing ran. Worse, in the measured case the directory held 3 tests across 2 files and
    the junit accounted for exactly 1. The other 2 never ran and appear NOWHERE, so the
    report understates its own blast radius while sounding precise.
  · Shape B reaches the right state by accident — the counts are all zero because nothing
    could be parsed — but carries no diagnosis at all. And **no pytest hook fires**, not
    even in the outermost conftest, so a plugin cannot catch it. Only the wrapper can,
    by reading the exit code.

That asymmetry is why this is a module and not a plugin: shape A is reachable in-process,
shape B is reachable only from outside, and a fix that handles one shape is a fix that
still goes quiet on the other.

WHAT THIS MODULE DOES NOT DO. It does not decide anything. It reads an exit code and the
captured output and returns a description, so both the in-pytest plugin and the scheduled
job can render the SAME diagnosis. Judgement about pass/fail belongs to the caller.
"""

import os
import re
import subprocess
from typing import Dict, List, Optional


# The third state. Deliberately not "FAILED" and not "NOT EXECUTED": a reader who sees
# this must not conclude the product is broken, and must not conclude anything is green.
COLLECTION_ERROR = "COLLECTION ERROR"

# pytest's own exit codes. 2 and 4 are the two collection-error shapes; 5 is the adjacent
# silence (nothing matched), which is also not a pass.
EXIT_INTERRUPTED   = 2   # collection error inside a test module
EXIT_USAGE_ERROR   = 4   # conftest failed to import — no hooks fire, no junit written
EXIT_NO_TESTS      = 5   # nothing collected at all


def _find_uncommitted_python( project_root: Optional[ str ] = None ) -> List[ str ]:
    """
    List uncommitted .py files.

    Requires:
        - git is available and project_root is inside a work tree, or the result is empty

    Ensures:
        - returns repo-relative paths of modified/added/untracked .py files
        - returns [] rather than raising when git is unavailable

    WHY THIS IS PART OF A DIAGNOSIS. One of the two measured incidents was a required
    parameter added to `make_provenance` in a file that was never committed. `git log`
    showed nothing, so the change was invisible to everyone except its author, and that
    is exactly the case where diagnosis is hardest. Naming the uncommitted files turns
    "nothing in the history explains this" into a short list of suspects.
    """
    root = project_root or os.environ.get( "LUPIN_ROOT" ) or "."
    try:
        out = subprocess.run(
            [ "git", "-C", root, "status", "--porcelain" ],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return []
    if out.returncode != 0:
        return []
    files = []
    for line in out.stdout.splitlines():
        if len( line ) < 4:
            continue
        path = line[ 3: ].strip()
        if path.endswith( ".py" ):
            files.append( path )
    return files


def _classify_cause( output: str ) -> Dict[ str, str ]:
    """
    Name the likely cause class from the traceback text.

    Ensures:
        - returns a dict with cause_class / detail / remedy
        - returns the generic pair when nothing recognisable is present, rather than
          guessing — a confident wrong cause costs more than an honest "unrecognised"
    """
    # Shape A's signature: the test's subject is gone.
    m = re.search( r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", output )
    if m:
        return {
            "cause_class" : "orphaned import — the imported subject does not exist",
            "detail"      : f"missing module: {m.group( 1 )}",
            "remedy"      : ( "Either the subject was retired and this test was left behind (delete or "
                              "rewrite the test), or the module moved and the import was not updated." ),
        }
    # Shape B's signature: a signature change landed before its callers were updated.
    m = re.search( r"TypeError: (\w+)\(\) missing (\d+) required positional argument", output )
    if m:
        return {
            "cause_class" : "signature change ahead of its callers",
            "detail"      : f"{m.group( 1 )}() is being called with {m.group( 2 )} too few argument(s)",
            "remedy"      : ( f"A required parameter was added to {m.group( 1 )}() but at least one caller "
                              f"still uses the old signature. Update the callers, or give the parameter a "
                              f"default until they land." ),
        }
    m = re.search( r"ImportError: cannot import name ['\"]([^'\"]+)['\"] from ['\"]?([^'\" ]+)", output )
    if m:
        return {
            "cause_class" : "orphaned import — the name is gone from a module that still exists",
            "detail"      : f"cannot import {m.group( 1 )} from {m.group( 2 )}",
            "remedy"      : ( "The symbol was renamed or removed while the importer was not updated. "
                              "Check that module's recent history for a rename." ),
        }
    m = re.search( r"^E\s+(\w*Error: .+)$", output, re.MULTILINE )
    if m:
        return {
            "cause_class" : "unrecognised import-time failure",
            "detail"      : m.group( 1 )[ :200 ],
            "remedy"      : "Read the traceback above; this module did not recognise the shape.",
        }
    return {
        "cause_class" : "unrecognised import-time failure",
        "detail"      : "no recognisable exception line in the captured output",
        "remedy"      : "Read the traceback above; this module did not recognise the shape.",
    }


def diagnose( exit_code: int, output: str, project_root: Optional[ str ] = None,
              where_hint: Optional[ str ] = None ) -> Optional[ Dict ]:
    """
    Describe a collection error, or return None when this is not one.

    Requires:
        - exit_code is pytest's process exit code
        - output is the captured stdout+stderr of that run, OR a collect report's
          traceback text when `where_hint` is supplied

    Ensures:
        - returns None for exit codes 0 and 1 — a real pass and a real failure are NOT
          this module's business, and claiming them would be the same over-reach this
          module exists to prevent
        - returns a dict with state / where / cause_class / detail / remedy /
          uncommitted_suspects for exit codes 2, 4 and 5 when the output corroborates it
        - never raises on malformed input

    ⚠️ WHY `where_hint` EXISTS. The wrapper sees pytest's whole terminal output, which
    carries the "Interrupted: N errors during collection" banner. An IN-PROCESS caller
    (the pytest_collectreport hook) sees only a collect report's traceback, and that
    banner is written by the terminal reporter, not by the report — so inferring from
    text was silently returning None for the very case the hook exists to catch. A
    caller that already KNOWS collection failed states it instead of re-deriving it
    from a string it does not have.
    """
    if exit_code in ( 0, 1 ):
        return None
    output = output or ""

    if where_hint:
        where = where_hint
    elif exit_code == EXIT_USAGE_ERROR and "conftest" in output.lower():
        where = "conftest"
    elif exit_code == EXIT_INTERRUPTED and re.search( r"error(s)? during collection|Interrupted", output ):
        where = "test module"
    elif exit_code == EXIT_NO_TESTS:
        return {
            "state"                 : COLLECTION_ERROR,
            "where"                 : "nothing collected",
            "cause_class"           : "no tests matched",
            "detail"                : "pytest collected zero tests (exit 5)",
            "remedy"                : ( "Check the path, the -k/-m selection, and the addopts deselections in "
                                        "pytest.ini. Zero tests is not a pass." ),
            "uncommitted_suspects"  : [],
        }
    else:
        return None

    info = _classify_cause( output )
    return {
        "state"                 : COLLECTION_ERROR,
        "where"                 : where,
        "cause_class"           : info[ "cause_class" ],
        "detail"                : info[ "detail" ],
        "remedy"                : info[ "remedy" ],
        "uncommitted_suspects"  : _find_uncommitted_python( project_root ),
    }


def render( diag: Dict ) -> str:
    """
    Render a diagnosis as the block a human should see.

    Ensures:
        - leads with what the result is NOT, because both wrong readings of a collection
          error (a regression, or a quiet pass) are what cost the time
    """
    lines = [
        "",
        "=" * 78,
        "  COLLECTION ERROR — the suite did not run. This is NOT a test failure.",
        "=" * 78,
        "  Nobody's prior greens were falsified, and nobody's greens were confirmed.",
        "  There is no pass/fail number to read here, because no test executed.",
        "",
        f"  Where        : {diag[ 'where' ]}",
        f"  Likely cause : {diag[ 'cause_class' ]}",
        f"  Detail       : {diag[ 'detail' ]}",
        f"  Remedy       : {diag[ 'remedy' ]}",
    ]
    if diag[ "where" ] == "conftest":
        lines += [
            "",
            "  NOTE: a conftest failure fires NO pytest hooks and writes NO junit XML,",
            "  so nothing inside pytest can report it. It also takes the whole directory",
            "  down, so the file named above may have nothing to do with the tests you",
            "  were running.",
        ]
    suspects = diag.get( "uncommitted_suspects" ) or []
    if suspects:
        shown = suspects[ :10 ]
        lines += [
            "",
            f"  UNCOMMITTED .py FILES ({len( suspects )}) — check these FIRST:",
        ]
        lines += [ f"    · {s}" for s in shown ]
        if len( suspects ) > len( shown ):
            lines.append( f"    … and {len( suspects ) - len( shown )} more" )
        lines += [
            "",
            "  `git log` cannot see an uncommitted change. One of the two incidents behind",
            "  this diagnostic was exactly that: a required parameter added in a file that",
            "  was never committed, invisible to everyone but its author.",
        ]
    lines += [ "=" * 78, "" ]
    return "\n".join( lines )


def quick_smoke_test():
    """Exercise both measured shapes plus the two must-stay-silent controls."""
    import cosa.utils.util as du
    du.print_banner( "pytest_collection_diagnosis smoke test" )

    shape_a = ( 2, "E   ModuleNotFoundError: No module named 'cosa.memory.credential_watcher'\n"
                   "!!!! Interrupted: 1 error during collection !!!!" )
    shape_b = ( 4, "ImportError while loading conftest '/x/conftest.py'.\n"
                   "E   TypeError: make_provenance() missing 1 required positional argument: 'run_id'" )

    for label, ( code, out ) in ( ( "shape A (test module)", shape_a ), ( "shape B (conftest)", shape_b ) ):
        d = diagnose( code, out )
        ok = d is not None and d[ "state" ] == COLLECTION_ERROR
        print( f"  {'✓' if ok else '✗'} {label}: {d[ 'cause_class' ] if d else 'NOT DETECTED'}" )

    # Controls — a real pass and a real failure must stay invisible to this module.
    for label, code in ( ( "real pass", 0 ), ( "real failure", 1 ) ):
        d = diagnose( code, "5 passed, 1 failed" )
        print( f"  {'✓' if d is None else '✗'} {label} correctly ignored" )


if __name__ == "__main__":
    quick_smoke_test()
