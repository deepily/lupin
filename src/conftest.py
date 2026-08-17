"""
Root pytest config shared by BOTH test trees under `src/`:
  - the Lupin `src/tests/` tree, and
  - the in-tree CoSA `src/cosa/tests/` tree.

This file exists for cross-tree test-isolation guards (see below). Keep it minimal —
tree-specific fixtures belong in `src/tests/conftest.py` /
`src/cosa/tests/...conftest.py`, not here.
"""

import importlib._bootstrap
import os
import socket
import sys
import traceback
from unittest.mock import patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# GUARD: a UNIT test that dials OUT (row 7c84b8b8)
# ══════════════════════════════════════════════════════════════════════════════
# A unit test that opens a network connection does not pass or fail on the code — it
# passes or fails on whether a server happened to be up. Five tests in test_v2_eval.py
# dialled :8000 for a git sha and cost ten seconds of socket timeout each whenever that
# server was busy; the red set MOVED between identical runs, and two seats independently
# read that movement as a difference between branch and base. The unit tier is a merge
# gate, so a suite whose red count wanders makes every comparison argue about the wrong
# number.
#
# ⚠️ IT REPORTS THE STACK AT THE CONNECT, NOT THE TEST IN FLIGHT. The first instrument
# recorded only which test was running and named test_dm_sender_project_required.py — a
# file containing no networking code at all. The dial actually came from production code
# the test reaches (dm.py's inline DM grader, row ec5cf83a). An instrument that names the
# victim instead of the culprit sends the next reader to the wrong file.
#
# THREE MODES, chosen by LUPIN_UNIT_NETWORK:
#   off   (default) — inert. Integration/e2e runs, which legitimately use the network, are
#                     untouched because their runners do not set the variable.
#   count           — record and ALLOW, printing a summary. What the unit runners set
#                     today: every dial-out is VISIBLE without holding the merge gate
#                     hostage to fallout owned by another lane (row ec5cf83a).
#   block           — record and RAISE, naming the test, the address and the frames.
#
# ⚠️ WHY count EXISTS AT ALL, measured 2026-08-17: run in block mode, the FIRST offender
# was at COLLECTION time, and a collection error takes the rest of the tier with it — one
# offender hid every other one and the run looked finished at a count of 1. A census that
# stops at its first finding is not a census.
#
# THE ESCAPE HATCH IS A MARKER, never an environment default:
# @pytest.mark.allows_outbound_network on a test that genuinely needs the network, so the
# exemption lives in the file that needs it and is greppable.
_NETWORK_MODE       = os.environ.get( "LUPIN_UNIT_NETWORK", "off" ).strip().lower()
_LOOPBACK_HOSTS     = { "127.0.0.1", "::1", "localhost", "0.0.0.0", "" }
_outbound_attempts  = []                       # (test id, address, formatted frames)
_current_test       = { "id": "<collection>", "exempt": False }

_real_socket_connect    = socket.socket.connect
_real_socket_connect_ex = socket.socket.connect_ex


def _is_loopback( address ):
    """
    Ensures:
        - returns True for anything that is not a routed address, so AF_UNIX and
          in-process transports are never touched
        - returns True for loopback: TestClient and the real-socket arms in
          test_model_server_liveness.py bind 127.0.0.1 deliberately, and a guard that
          breaks legitimate tests gets switched off — which is worse than no guard
    """
    if not isinstance( address, tuple ) or not address:
        return True
    host = address[ 0 ]
    if host in _LOOPBACK_HOSTS:
        return True
    return isinstance( host, str ) and host.startswith( "127." )


def _caller_frames():
    """The repo frames beneath the connect, so a report names the CULPRIT, not the victim."""
    frames = [ f for f in traceback.extract_stack()[ :-2 ]
               if "/site-packages/" not in f.filename and "/lib/python" not in f.filename ]
    return [ f"{f.filename}:{f.lineno} in {f.name}" for f in frames[ -6: ] ]


def _network_guard( real ):
    def wrapper( self, address, *args, **kwargs ):
        if _NETWORK_MODE in ( "count", "block" ) and not _is_loopback( address ) \
           and not _current_test[ "exempt" ]:
            frames = _caller_frames()
            _outbound_attempts.append( ( _current_test[ "id" ], address, frames ) )
            if _NETWORK_MODE == "block":
                raise RuntimeError(
                    f"OUTBOUND NETWORK BLOCKED in a unit test (row 7c84b8b8).\n"
                    f"  test    : {_current_test[ 'id' ]}\n"
                    f"  address : {address}\n"
                    f"  from    :\n    " + "\n    ".join( frames ) + "\n"
                    f"  A unit test that dials out passes or fails on whether a server "
                    f"happened to be up. Inject the seam, or mark the test with "
                    f"@pytest.mark.allows_outbound_network if it genuinely needs the network."
                )
        return real( self, address, *args, **kwargs )
    return wrapper


if _NETWORK_MODE in ( "count", "block" ):
    # Patched at IMPORT, not in a fixture: the dial-out that started this lives in a
    # `@pytest.mark.skipif( not _mistral_reachable(), ... )` argument, which evaluates at
    # COLLECTION — before any fixture exists to catch it.
    socket.socket.connect    = _network_guard( _real_socket_connect )
    socket.socket.connect_ex = _network_guard( _real_socket_connect_ex )


# ══════════════════════════════════════════════════════════════════════════════
# GUARD: a re-import-hostile package was UNLOADED and LOADED AGAIN (row e1da2b5f)
# ══════════════════════════════════════════════════════════════════════════════
# SQLAlchemy cannot survive a partial eviction: re-importing after one raises
# `AssertionError: Type <class 'object'> is already registered`. Something evicting
# it mid-suite therefore breaks a LATER test, in a DIFFERENT file, with an error that
# names neither the evictor nor the cause.
#
# Two evictors are on record:
#   `patch.dict( 'sys.modules', ... )`  — restores a pre-patch snapshot on exit,
#       dropping everything the patched code imported while inside   (bug e9e31de7)
#   coverage's `sys_modules_saved()`    — same shape, different actor (bug 1b8ec2b9)
#
# ⚠️ WHY THIS WATCHES THE RE-LOAD AND NOT THE EVICTION. Three detectors were built
# against the eviction and all three were blind:
#   1. sys.modules diff, setup vs teardown  — victims are imported DURING the test,
#      so they were never in the setup snapshot
#   2. session high-water mark              — load AND unload complete inside ONE
#      test body; no between-tests hook ever observes the package present
#   3. a spy on `mock._patch_dict._unpatch_dict` — proven live by a control that
#      fired, yet silent on the real test
# All three aimed AT the effect. The observable is one step upstream: the *re-load*.
#
# MEASURED, both arms predicted before running (2026-07-27):
#   defect present : test 1 loads 60 sqlalchemy modules inside the patch,
#                    test 2 RE-loads 8   -> the failure
#   defect fixed   : 0 and 0             -> silent
_PROTECTED_ROOTS  = ( "sqlalchemy", )
_ever_loaded      = set()
_reloaded_by_test = []

_real_find_and_load = importlib._bootstrap._find_and_load


def _find_and_load_watching_reimports( name, import_ ):
    """
    Wrap the import machinery's cache-MISS path to notice a protected re-load.

    Ensures:
        - behaviour is identical to the wrapped function in every case
        - a protected module loaded a SECOND time in one session is recorded
        - never raises on its own; the fixture decides what a recording means, so an
          import can never fail because of this instrument
    """
    root = name.split( "." )[ 0 ]
    if root in _PROTECTED_ROOTS and name in _ever_loaded:
        _reloaded_by_test.append( name )
    if root in _PROTECTED_ROOTS:
        _ever_loaded.add( name )
    return _real_find_and_load( name, import_ )


importlib._bootstrap._find_and_load = _find_and_load_watching_reimports


# ══════════════════════════════════════════════════════════════════════════════
# GUARD: worktree false-green — ROOT wiring (row 71249e0f; guard by Rio, a9f87d29)
# ══════════════════════════════════════════════════════════════════════════════
# MOVED here from src/tests/conftest.py so ONE call site covers BOTH test trees.
# pytest loads THIS root conftest for src/tests/** AND src/cosa/tests/**, but it
# never loads src/tests/conftest.py for the cosa tree — so wiring the guard only
# there left the cosa tier (a merge-pyramid gate since 2026-08-13) UNPROTECTED: a
# worktree run with LUPIN_ROOT pointing at another tree imports `cosa` from the
# WRONG tree via conftest's sys.path bootstrap, and a revert-to-verify RED check
# reports a false GREEN — unguarded and unwarned (finding 2ed1be74). Wiring it at
# the root closes that gap with no second call site to drift.
#
# The pure predicate is Rio's tests/worktree_tree_guard.py (unchanged); this is
# thin wiring only. The import is DEFERRED into the hook on purpose: this root
# conftest loads BEFORE the per-tree conftests that bootstrap `src` onto sys.path,
# so a module-level `from tests...` here could precede that bootstrap. By
# collection-modify time the invoking tree's conftest (src/tests/ or
# src/cosa/tests/) has run and `tests` is importable. Fail-SAFE lives in the pure
# predicate: it is silent unless BOTH tree roots resolve AND differ, so a correct
# main-tree or matched-worktree run never trips.
def pytest_runtest_setup( item ):
    """Name the test the guard will blame, and honour its opt-out marker (row 7c84b8b8)."""
    _current_test[ "id" ]     = item.nodeid
    _current_test[ "exempt" ] = item.get_closest_marker( "allows_outbound_network" ) is not None


def pytest_terminal_summary( terminalreporter, exitstatus, config ):
    """
    Report every outbound dial the run made, or say plainly that it made none.

    ⚠️ THE ZERO CASE IS PRINTED TOO, deliberately. A guard that says nothing when it found
    nothing is indistinguishable from a guard that was never armed — which is the exact
    shape of defect it exists to catch.
    """
    if _NETWORK_MODE not in ( "count", "block" ):
        return
    if not _outbound_attempts:
        terminalreporter.write_line( f"[unit-network:{_NETWORK_MODE}] outbound connections: 0" )
        return
    terminalreporter.write_line(
        f"[unit-network:{_NETWORK_MODE}] outbound connections: {len( _outbound_attempts )}"
    )
    for test_id, address, frames in _outbound_attempts:
        terminalreporter.write_line( f"  {test_id} -> {address}" )
        for frame in frames[ -3: ]:
            terminalreporter.write_line( f"      {frame}" )


def pytest_collection_modifyitems( config, items ):
    from tests.worktree_tree_guard import check_paths as _worktree_check_paths
    _drift = _worktree_check_paths(
        [ str( item.path ) for item in items if getattr( item, "path", None ) is not None ],
        os.environ.get( "LUPIN_ROOT" ),
    )
    if _drift is not None:
        raise pytest.UsageError( _drift )


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSIS: a collection error is SILENCE, not a red test (row bc83f2df)
# ══════════════════════════════════════════════════════════════════════════════
# A collection error takes the whole DIRECTORY down before anything runs. Read it as a
# regression and you hunt a breakage that does not exist; read the absence of a red as a
# pass and you ship on a suite that never executed. Cheech hit two of them in one
# afternoon, from different causes, and each was diagnosed from scratch. That repetition
# is the defect — the two individual causes were both fixed the same day.
#
# ⚠️ THIS HOOK COVERS ONLY ONE OF THE TWO SHAPES, and the docstring says so rather than
# implying full cover. Measured 2026-08-17:
#   · error in a TEST module   -> exit 2, hooks DO fire  -> caught here
#   · error in a CONFTEST      -> exit 4, NO hook fires at all, not even in this root
#                                 conftest, and no junit is written -> INVISIBLE here
# The conftest shape is reachable only from outside the process, by exit code, which is
# why the shared logic lives in cosa.utils.pytest_collection_diagnosis and is called
# from the suite runner too. A fix that handled only this half would still go quiet on
# the case that cost the most time.
_collect_failures = []


def pytest_collectreport( report ):
    """Record a failed collection so sessionfinish can explain it."""
    if report.failed:
        _collect_failures.append( getattr( report, "longreprtext", "" ) or str( report.longrepr ) )


def pytest_sessionfinish( session, exitstatus ):
    """
    Print the diagnosis block for a collection error, in place of leaving a bare
    "Interrupted" line that reads like a run which finished.

    Ensures:
        - prints only when collection actually failed; a normal pass or a normal failure
          is untouched, because a diagnoser that fires on everything makes the state
          meaningless
        - never raises: a broken diagnostic must not be able to change a suite's outcome
    """
    if not _collect_failures:
        return
    try:
        from cosa.utils.pytest_collection_diagnosis import diagnose, render
        # where_hint is stated, not inferred: this hook only ever fires because a collect
        # report FAILED, and the "Interrupted" banner it would otherwise be matched on is
        # written by the terminal reporter, not carried in the report's traceback.
        diag = diagnose( int( exitstatus ), "\n".join( _collect_failures ),
                         where_hint="test module" )
        if diag is not None:
            print( render( diag ) )
    except Exception as e:
        print( f"\n[collection-diagnosis] could not render a diagnosis: {e!r}\n"
               f"  The collection error above is still real — read the traceback.\n" )


@pytest.fixture( autouse=True )
def _fail_on_protected_module_reimport():
    """
    Fail the test that RE-LOADED a package which cannot survive re-import.

    ⚠️ The failure it prevents is not this test's — it is the NEXT one's, in another
    file, with an assertion about a call that never happened. Attributing it here, to
    the test that actually did the unloading, is the entire value.

    Ensures:
        - a test that re-loads any `_PROTECTED_ROOTS` module fails, naming the modules
        - a test that does not is untouched
        - the recording buffer is cleared per test, so one offender cannot cascade
          into blaming every test that follows it
    """
    _reloaded_by_test.clear()
    yield
    if _reloaded_by_test:
        offenders = sorted( set( _reloaded_by_test ) )[ :6 ]
        raise AssertionError(
            f"This test RE-LOADED {len( set( _reloaded_by_test ) )} protected module(s) "
            f"— e.g. {offenders}. Something unloaded them mid-test (most often "
            f"`patch.dict( 'sys.modules', ... )`, which restores a PRE-PATCH snapshot on "
            f"exit and drops whatever the patched code imported while inside). "
            f"SQLAlchemy cannot survive that: the next re-import raises "
            f"'Type <class \\'object\\'> is already registered', and the test that FAILS "
            f"will be a later one in a different file. Fix: import the module at test-"
            f"MODULE scope so it sits in the pre-patch snapshot (see "
            f"src/cosa/tests/unit/rest/test_system_router.py), or stop stubbing "
            f"sys.modules around code that imports it. Row e1da2b5f."
        )


@pytest.fixture( autouse=True )
def _evict_real_fastapi_main_after_test():
    """
    Cross-file test-isolation guard (2026-06-03 Gate-Zero finding).

    Many router / auth tests import the REAL `lupin_app.main` at module load (to
    build a TestClient against the live app). That import persists in `sys.modules`
    AND sets `main` as an attribute on the `lupin_app` package object. The PARENT
    ATTRIBUTE is the trap: `import lupin_app.main as m` resolves it (not the
    `sys.modules['lupin_app.main']` entry), so a later test's
    `patch.dict(sys.modules, {"lupin_app.main": <fake>})` is silently defeated —
    the code under test gets the real, un-started module whose `config_mgr` /
    `jobs_todo_queue` are None, and fails depending ONLY on suite run-order.

    Evicting after every test makes each test start able to mock `lupin_app.main`
    cleanly, regardless of which earlier test imported the real app. Tests that
    legitimately use the real app hold their own module-level `app` reference, which
    is a live object unaffected by this `sys.modules` eviction.

    Ensures:
        - after each test, `sys.modules['lupin_app.main']` is removed (if present)
        - after each test, the `lupin_app.main` parent-package attribute is removed
          (if present), so it cannot shadow a future `sys.modules` patch
    """
    yield
    sys.modules.pop( "lupin_app.main", None )
    pkg = sys.modules.get( "lupin_app" )
    if pkg is not None and hasattr( pkg, "main" ):
        delattr( pkg, "main" )


@pytest.fixture( autouse=True )
def _redirect_dm_traffic_corpus( tmp_path ):
    """
    Cross-tree test-isolation guard (row 334569d6).

    `execute_dm_send` appends one JSON row per ACCEPTED send to
    `cosa.rest.routers.dm._DM_TRAFFIC_JSONL` — a real file under `src/tmp/` resolved
    via `cu.get_project_root()`. Under test that resolves to the HOST repo, so ANY
    send-path test (this tree or the CoSA tree) silently appends fixture rows into
    Rick's live four-day DM corpus. A per-file redirect is the shape that gets
    forgotten the next time someone adds a send-path test, so the guard lives here.

    Redirects the sink to a unique per-test file WHENEVER the dm router is loaded.
    Send-path test files import the router at MODULE scope, so it is already in
    `sys.modules` by the time this fixture runs — no forced heavy import is paid by
    the thousands of tests that never touch DMs.

    Ensures:
        - during any test with the dm router loaded, `_DM_TRAFFIC_JSONL` points inside
          the test's `tmp_path`, never the production corpus
        - the module attribute is restored after the test
        - inert (no-op) when the dm router is not loaded
    """
    dm = sys.modules.get( "cosa.rest.routers.dm" )
    if dm is None or not hasattr( dm, "_DM_TRAFFIC_JSONL" ):
        yield
        return
    with patch.object( dm, "_DM_TRAFFIC_JSONL", str( tmp_path / "dm_traffic.jsonl" ) ):
        yield
