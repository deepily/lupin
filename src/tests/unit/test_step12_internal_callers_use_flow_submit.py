"""
Step 12 THROUGH-PATH: the six internal callers go through `flow.submit()`.

WHAT STEP 12 SAYS. Sixteen doors die and their callers move to `/api/v2/submit`, but
six callers have NO endpoint to disable — they push work onto the queue from inside the
process. They must reach `flow.submit()` like everyone else, and `job_persistence:830`
— the boot-time catch-up restore — is RULED IN by Rick precisely because it is *"the
caller least likely to be noticed misbehaving: startup, unattended, re-enqueueing work
an interruption left behind."*

HELD OUT OF THE SUITE until step 12 lands: `flow.submit()` does not exist yet, so every
assertion here is red today. It goes in with the step-12 sha.

THE SIX, RE-VERIFIED AT HEAD `efadc2bc` RATHER THAN COPIED FROM THE PLAN — the plan's
line numbers were written this morning and one path in it was wrong:

    src/cosa/rest/dead_queue_watchdog.py:486             self.todo_queue.push( bfe_job )
    src/cosa/rest/test_suite_completion_watchdog.py:282  self.todo_queue.push( tfe_job )
    src/cosa/rest/job_persistence.py:830                 todo_queue.push( job )
    src/cosa/rest/arbiter_bootstrap.py:184               todo_queue.push( job )
    src/cosa/agents/test_fix_expediter/orchestrator.py:2174  todo_queue.push( validation_job )
    src/cosa/agents/bug_fix_expediter/job.py:586         todo_queue.push( new_job )

⚠️ `arbiter_bootstrap.py` lives under `src/cosa/rest/`, NOT `src/lupin_app/`. Every
other line number checked out exactly.

🔴 AND THE SIX ARE THE WHOLE POPULATION — measured, not taken on faith. A repo-wide
sweep for `todo_queue.push(` outside routers and tests returns exactly these six. The
other nineteen call sites are the RETIRED DOORS themselves (`routers/*.py`), which step
11 tombstones, and `src/tmp/*` scratch files. That measurement is why
`test_no_internal_caller_still_pushes_directly` below is a POPULATION check rather than
a list check: the plan's own lesson is that *"a loop that silently covers fifteen is how
door 8 stayed invisible for a day"*, and a hand-list of six rots the same way.
"""

import ast
import os
import re

import pytest

# ( repo-relative path, the local name the call is made on )
SIX_INTERNAL_CALLERS = [
    ( "src/cosa/rest/dead_queue_watchdog.py",                    "dead_queue_watchdog" ),
    ( "src/cosa/rest/test_suite_completion_watchdog.py",         "test_suite_completion_watchdog" ),
    ( "src/cosa/rest/job_persistence.py",                        "job_persistence" ),
    ( "src/cosa/rest/arbiter_bootstrap.py",                      "arbiter_bootstrap" ),
    ( "src/cosa/agents/test_fix_expediter/orchestrator.py",      "tfe_orchestrator" ),
    ( "src/cosa/agents/bug_fix_expediter/job.py",                "bfe_job" ),
]

_PUSH_CALL = re.compile( r"todo_queue\s*\.\s*push\s*\(" )
_SUBMIT_CALL = re.compile( r"\.submit\s*\(" )


def _repo_root():
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be set — see CLAUDE.md § PATH MANAGEMENT"
    return root


def _read( rel ):
    with open( os.path.join( _repo_root(), rel ) ) as fh:
        return fh.read()


@pytest.mark.skip( reason="DRAFT — lands with step 12; red until flow.submit() exists" )
@pytest.mark.parametrize( "rel,label", SIX_INTERNAL_CALLERS, ids=[ label for _r, label in SIX_INTERNAL_CALLERS ] )
def test_each_internal_caller_submits_through_the_flow( rel, label ):
    """One reported case per caller — a loop reporting one aggregate hides the fifth."""
    source = _read( rel )
    assert not _PUSH_CALL.search( source ), (
        f"{rel} still calls todo_queue.push( ... ) directly; step 12 routes every internal "
        f"caller through flow.submit() so the guarded write-back applies to it too"
    )
    assert _SUBMIT_CALL.search( source ), f"{rel} no longer pushes, but nothing in it submits either"


@pytest.mark.skip( reason="DRAFT — lands with step 12; red until flow.submit() exists" )
def test_no_internal_caller_still_pushes_directly():
    """POPULATION CHECK — the guard a hand-list of six cannot give you.

    Sweeps the whole tree for `todo_queue.push(` and allows it ONLY in the retired-door
    routers (step 11 tombstones them) and in tests/scratch. Anything else is an internal
    caller that step 12 missed — including one added AFTER this file was written, which
    is exactly the case a fixed list of six would sail past.
    """
    root      = _repo_root()
    offenders = []
    for dirpath, dirnames, filenames in os.walk( os.path.join( root, "src" ) ):
        dirnames[ : ] = [ d for d in dirnames if d not in ( "__pycache__", "tmp", "tests", ".git" ) ]
        if f"{os.sep}routers" in dirpath: continue          # the retired doors — step 11's job
        for name in filenames:
            if not name.endswith( ".py" ): continue
            full = os.path.join( dirpath, name )
            with open( full, errors="ignore" ) as fh:
                if _PUSH_CALL.search( fh.read() ):
                    offenders.append( os.path.relpath( full, root ) )
    assert not offenders, (
        f"these modules still push onto the queue directly instead of going through "
        f"flow.submit(): {sorted( offenders )}"
    )


# ── the boot-order precondition, which the plan calls a precondition and not a nicety ──

@pytest.mark.skip( reason="DRAFT — lands with step 12; red until the flow is built in lifespan" )
def test_the_flow_exists_before_the_catch_up_restore_runs():
    """`job_persistence:830` restores jobs at BOOT. If the flow is not built yet, it has
    nothing to submit to.

    SOURCE-ORDER assertion on purpose, matching the idiom of
    `test_main_boot_order_v2_submit.py`: importing `lupin_app.main` runs the module
    graph but does NOT run `lifespan`, so the ordering fact is only visible in the
    source. That neighbouring file records the finding this test pins the fix for —
    at HEAD the flow is built by a REQUEST-time dependency (`v2_ask.get_ask_flow`),
    and the restore runs before any request exists.
    """
    path = os.path.join( _repo_root(), "src", "lupin_app", "main.py" )
    with open( path ) as fh:
        tree = ast.parse( fh.read() )

    lifespan = next( ( n for n in ast.walk( tree )
                       if isinstance( n, ast.AsyncFunctionDef ) and n.name == "lifespan" ), None )
    assert lifespan is not None, "lupin_app.main has no async lifespan() — this pin's premise is gone"

    def _first_line( predicate ):
        hits = [ child.lineno for child in ast.walk( lifespan ) if predicate( child ) ]
        return min( hits ) if hits else None

    flow_line = _first_line(
        lambda n: isinstance( n, ast.Attribute ) and n.attr in ( "ask_flow", "flow" )
                  and isinstance( n.value, ast.Attribute ) and n.value.attr == "state"
    )
    restore_line = _first_line(
        lambda n: isinstance( n, ast.Call ) and isinstance( n.func, ast.Name )
                  and n.func.id == "restore_pending_jobs"
    )

    assert restore_line is not None, "restore_pending_jobs() is no longer called in lifespan"
    assert flow_line is not None, (
        "lifespan never puts the flow on app.state. At HEAD the flow is built by the "
        "request-time dependency v2_ask.get_ask_flow, and the catch-up restore runs "
        "before any request exists — so the restore has nothing to submit to. Step 12 "
        "must construct it in lifespan, before the restore."
    )
    assert flow_line < restore_line, (
        f"the catch-up restore (main.py:{restore_line}) runs BEFORE the flow is placed on "
        f"app.state (main.py:{flow_line}) — the boot-time caller would submit to nothing"
    )
