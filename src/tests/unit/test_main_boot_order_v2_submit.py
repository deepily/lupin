"""
Boot-order pin for step 12's ruled-in caller: the catch-up restore.

WHY (brain-integration cascade plan, step 12, B0(ii)). `job_persistence:830` — the
boot-time restore of jobs an interruption left behind — is ruled to go through
`flow.submit()` like every other caller. The plan's own precondition says the flow,
the registry and the executor must all exist before the restore runs, and that
`main.py`'s construction order was UNREAD when the step was written. This file reads
it and pins it.

WHAT WAS READ, at HEAD, in `src/lupin_app/main.py`:

    lifespan()                              569 .. 1218
      jobs_todo_queue = TodoFifoQueue(...)  :731
      jobs_run_queue  = RunningFifoQueue(…) :734
      restore_pending_jobs( ... )           :1038

    The AskFlow is NOT built during lifespan at all. `routers/v2_ask.build_ask_flow`
    has exactly one call site — the `get_ask_flow` FastAPI dependency (:124), memoised
    in `_ASK_FLOW_CACHE` (:134) — and that dependency runs on an HTTP request. The
    restore runs before any request exists, so there is no flow to call submit() on.

    That is the finding, not a green light. Step 12 has to CREATE the flow during
    lifespan, before the restore, and park it where the route dependency can find it.
    Two facts settle the shape: get_ask_flow() raises HTTPException(503) when
    `v2 flow enabled` is false (:139), which must not fire at boot; and the flow is
    one-per-process today only because ConfigurationManager carries @singleton
    (configuration_manager.py:72) and the cache is keyed on id(config_mgr).

WHAT WOULD BREAK IT: a future edit that hoists the restore above the queue
construction, or that builds the flow during lifespan AFTER the restore. Both go red
here.

These are SOURCE-ORDER assertions on purpose. Importing `lupin_app.main` runs a heavy
module-level graph; the ordering fact lives in the source and is checked there.
"""

import ast
import inspect
import os

import pytest


def _lifespan_body_source():
    """Parse main.py and return ( tree, the lifespan FunctionDef )."""
    root = os.environ.get( "LUPIN_ROOT" )
    assert root, "LUPIN_ROOT must be set — see CLAUDE.md § PATH MANAGEMENT"
    path = os.path.join( root, "src", "lupin_app", "main.py" )
    with open( path ) as fh:
        tree = ast.parse( fh.read() )
    for node in ast.walk( tree ):
        if isinstance( node, ast.AsyncFunctionDef ) and node.name == "lifespan":
            return tree, node
    pytest.fail( "lupin_app.main has no async lifespan() — the pin's premise is gone" )


def _first_lineno( node, predicate ):
    """Lowest line number under `node` for which predicate( child ) is true, or None."""
    hits = [ child.lineno for child in ast.walk( node ) if predicate( child ) ]
    return min( hits ) if hits else None


def _is_call_to( child, name ):
    return (
        isinstance( child, ast.Call )
        and isinstance( child.func, ast.Name )
        and child.func.id == name
    )


def _is_assignment_from( child, callee ):
    return (
        isinstance( child, ast.Assign )
        and isinstance( child.value, ast.Call )
        and isinstance( child.value.func, ast.Name )
        and child.value.func.id == callee
    )


# ── the ordering fact ────────────────────────────────────────────────────────

def test_todo_queue_is_constructed_before_the_catch_up_restore():
    """The restore hands jobs to jobs_todo_queue — it cannot run before that exists."""
    _tree, lifespan = _lifespan_body_source()
    queue_line   = _first_lineno( lifespan, lambda c: _is_assignment_from( c, "TodoFifoQueue" ) )
    restore_line = _first_lineno( lifespan, lambda c: _is_call_to( c, "restore_pending_jobs" ) )
    assert queue_line   is not None, "TodoFifoQueue is no longer constructed in lifespan()"
    assert restore_line is not None, "restore_pending_jobs is no longer called in lifespan()"
    assert queue_line < restore_line, (
        f"boot order broken: restore_pending_jobs at :{restore_line} runs before "
        f"TodoFifoQueue at :{queue_line}"
    )


def test_running_queue_is_constructed_before_the_catch_up_restore():
    """Step 12's submit path runs work; the running queue must already be up."""
    _tree, lifespan = _lifespan_body_source()
    run_line     = _first_lineno( lifespan, lambda c: _is_assignment_from( c, "RunningFifoQueue" ) )
    restore_line = _first_lineno( lifespan, lambda c: _is_call_to( c, "restore_pending_jobs" ) )
    assert run_line is not None, "RunningFifoQueue is no longer constructed in lifespan()"
    assert run_line < restore_line, (
        f"boot order broken: restore_pending_jobs at :{restore_line} runs before "
        f"RunningFifoQueue at :{run_line}"
    )


# ── what makes the flow available at that point ──────────────────────────────

def test_if_the_flow_is_built_in_lifespan_it_is_built_before_the_restore():
    """
    The pin that survives step 12 rather than being deleted by it.

    Today build_ask_flow is not called from lifespan at all, and the assertion below
    is that the restore does not reach for a flow that does not exist. When step 12
    moves construction into lifespan, the same assertion becomes the ordering check —
    the flow must be built BEFORE the restore, never after.
    """
    _tree, lifespan = _lifespan_body_source()
    build_line   = _first_lineno( lifespan, lambda c: _is_call_to( c, "build_ask_flow" ) )
    restore_line = _first_lineno( lifespan, lambda c: _is_call_to( c, "restore_pending_jobs" ) )
    if build_line is None:
        # Pre-step-12 state: no flow in lifespan, so the restore must not name one.
        submit_line = _first_lineno( lifespan, lambda c: (
            isinstance( c, ast.Call )
            and isinstance( c.func, ast.Attribute )
            and c.func.attr == "submit"
            and isinstance( c.func.value, ast.Name )
            and c.func.value.id == "flow"
        ) )
        assert submit_line is None, (
            f"lifespan calls flow.submit() at :{submit_line} but never builds a flow — "
            f"step 12 must construct it before restore_pending_jobs at :{restore_line}"
        )
        return
    assert build_line < restore_line, (
        f"boot order broken: restore_pending_jobs at :{restore_line} runs before "
        f"build_ask_flow at :{build_line}"
    )


def test_build_ask_flow_needs_only_the_config_manager():
    """
    The restore can construct the flow itself only if the flow's construction needs
    nothing that lifespan builds. Its signature is the falsifiable form of that.
    """
    from cosa.rest.routers.v2_ask import build_ask_flow
    params = list( inspect.signature( build_ask_flow ).parameters )
    assert params == [ "config_mgr" ], (
        f"build_ask_flow now takes {params} — a new dependency may not exist at "
        f"restore time; re-read main.py's construction order before step 12 lands"
    )


def test_the_flows_ingredients_import_without_any_app_state():
    """Registry, executor factory and cache must be constructible at restore time."""
    from cosa.rest.v2.executor import make_executor
    from cosa.rest.v2.registry import REGISTRY, resolve
    from cosa.rest.v2.cache    import V2Cache          # noqa: F401  (import is the assertion)

    assert REGISTRY, "the command registry is empty at import time"
    assert resolve( "agent router go to todo", crud_enabled=False ) is not None
    assert make_executor( "inline" ) is not None
