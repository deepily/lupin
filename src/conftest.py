"""
Root pytest config shared by BOTH test trees under `src/`:
  - the Lupin `src/tests/` tree, and
  - the in-tree CoSA `src/cosa/tests/` tree.

This file exists for cross-tree test-isolation guards (see below). Keep it minimal —
tree-specific fixtures belong in `src/tests/conftest.py` /
`src/cosa/tests/...conftest.py`, not here.
"""

import importlib._bootstrap
import errno
import os
import socket
import subprocess
import time
import sys
import traceback
from unittest.mock import patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# DB_PASSWORD for the local-Docker tests (row baac2474)
# ══════════════════════════════════════════════════════════════════════════════
# The postgres password used to sit as a plaintext default inside database.py and a
# dozen other files. It is gone from the tree; the value lives ONLY in the untracked,
# gitignored .env beside docker-compose.yml — the same file compose already reads for
# POSTGRES_PASSWORD, so nothing new has to be installed for this to work.
#
# A handful of tests really do connect to the local postgres (test_check_schema_at_head,
# the pgvector fixtures, test_auto_migrate). Without this they get
# "fe_sendauth: no password supplied" and read as a broken branch rather than a missing
# env var. An exported DB_PASSWORD always wins; this only fills a blank.
def _seed_db_password_from_dotenv( root=None ):

    if os.environ.get( "DB_PASSWORD" ): return

    if root is None: root = os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) )

    # A worktree has no .env of its own — it is untracked, so it exists only in the main
    # checkout. In a worktree `.git` is a FILE reading "gitdir: <main>/.git/worktrees/<n>";
    # that is how we reach the checkout that actually holds it, with no subprocess.
    candidates = [ os.path.join( root, ".env" ) ]
    git_marker = os.path.join( root, ".git" )
    if os.path.isfile( git_marker ):
        try:
            gitdir = open( git_marker ).read().split( "gitdir:", 1 )[ 1 ].strip()
            main   = os.path.dirname( gitdir.split( "/.git/worktrees/" )[ 0 ] + "/.git" )
            candidates.append( os.path.join( main, ".env" ) )
        except ( OSError, IndexError ):
            pass

    dotenv = next( ( c for c in candidates if os.path.isfile( c ) ), None )
    if dotenv is None: return

    try:
        with open( dotenv ) as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith( "POSTGRES_PASSWORD=" ): continue
                value = line.split( "=", 1 )[ 1 ].strip().strip( "\"'" )
                if value: os.environ[ "DB_PASSWORD" ] = value
                return
    except OSError:
        return


_seed_db_password_from_dotenv()


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
# 🔴 THE STATE LIVES IN A MODULE, NOT HERE — ONE COPY, HOWEVER OFTEN THIS FILE IS LOADED
# (row 89c3900a, measured 2026-08-28). It used to live in this file, and THIS FILE IS
# LOADED TWICE as two separate module objects: `pytest_runtest_setup` recorded the marker
# into one copy's dict while the socket patch actually installed read a DIFFERENT dict that
# nobody ever wrote to. So every `allows_outbound_network` marker in the repo was inert on a
# whole-directory run — including the one in this guard's own test sandbox — and every
# recorded attempt was blamed on `<collection>` instead of a test. The control was exact:
#
#   pytest src/tests/unit/                          -k TestLiveMistralRegression  ->  5 ERRORS
#   pytest src/tests/unit/test_dm_quality_judge.py  -k TestLiveMistralRegression  ->  5 PASSED
#
# ⚠️ WHY this file is loaded twice is NOT established, and the fix does not depend on
# knowing. A module under `cosa/` lives at exactly one key in `sys.modules`, so every copy
# of this conftest binds the SAME dict and the SAME list — the cause becomes irrelevant
# rather than removed. Full account, including one hypothesis tested and rejected, in
# `cosa/utils/unit_network_guard.py`.
from cosa.utils.unit_network_guard import (
    NETWORK_MODE     as _NETWORK_MODE,
    NETWORK_MODE_RAW as _NETWORK_MODE_RAW,
    arm              as _arm_network_guard,
    caller_frames    as _caller_frames,
    current_test     as _current_test,
    is_loopback      as _is_loopback,
    network_guard    as _network_guard,
    outbound_attempts as _outbound_attempts,
    set_current_test as _set_current_test,
)

# Armed at IMPORT, not in a fixture — the dial that started row 7c84b8b8 evaluated at
# COLLECTION, before any fixture existed to catch it. Idempotent, so a second load of this
# file does not wrap the guard around itself.
_arm_network_guard()


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
# ══════════════════════════════════════════════════════════════════════════════
# GUARD: a coverage figure nobody can attribute (row aa41fa66)
# ══════════════════════════════════════════════════════════════════════════════
# Neither `data_file` nor COVERAGE_FILE is set anywhere in this repo, so every
# session working in lupin writes the SAME `.coverage` at the repo root — and
# pytest-cov ERASES that file at startup. A twenty-minute tier run and a
# nine-second targeted run share one mutable file, the short one wins, and NOTHING
# IN THE OUTPUT SAYS SO: the run exits 0 and prints a floor-reached line.
#
# MEASURED (María, 2026-08-25): a 19:44-20:04 tier run reported "Required test
# coverage of 96.0% reached. Total coverage: 96.59%" — GREEN, and false. 391 files,
# ALL under src/cosa, 34,322 statements against 62,305 in the same session's 19:04
# run. ~28,000 statements vanished from a frame the config says holds them,
# src/lib among them at 0.0% (that package was DELETED 2026-08-26, row e2099400
# §3b — the example is kept because it is what was measured, not what is
# measurable today). THE DIRECTION IS THE HAZARD: the vanished files are
# the known-worse-than-average ones, so dropping them RAISED the mean —
# 95.62 -> 96.59 while nothing improved. A red gate did not turn green; the report
# stopped measuring the red part.
#
# WHY A GUARD AND NOT A DEFAULT. The obvious fix — set the path ourselves — does
# not work, measured four ways (row aa41fa66): coverage's config expansion reads
# the environment and cannot compute a PID; COVERAGE_FILE outranks `data_file`
# anyway; `parallel = true` makes it WORSE, since each run's own combine globs the
# shared prefix and concurrent runs would MERGE rather than ignore each other; and
# setting COVERAGE_FILE from this file is simply TOO LATE — pytest-cov reads it
# before the rootdir conftest is imported, so a per-PID basename came back
# rewritten and a per-PID directory fell back to the root `.coverage` entirely.
# An EXPORTED COVERAGE_FILE is honored exactly. By the time any repo code runs the
# path is already chosen, so the one thing this file can still do is REFUSE TO
# PRODUCE AN UNATTRIBUTABLE FIGURE.
#
# Escape hatch for a deliberate shared-file run: LUPIN_ALLOW_SHARED_COVERAGE=1.
# ══════════════════════════════════════════════════════════════════════════════
# GUARD: a TEST that writes into the OPERATOR'S LIVE NOTIFICATION FEED (row ebb2c061)
# ══════════════════════════════════════════════════════════════════════════════
# Rick received eight "Stop — notify error" cards and read them as a stuck worker. They
# were a unit test. `AnythingElseCardContextTest` mocks the notify transport with a
# side_effect that raises ON PURPOSE, to stop `_ask_anything_else` once the card is built;
# that hook catches every exception and its handler's only action is
# `send_tts( f"Stop — notify error: {e}" )` — a THIRD transport the test never patched.
# Four test methods, four cards, twice over two tier runs: exactly the eight he saw.
#
# ⚠️ THE ESCAPE IS NOT THE TEST'S FAULT, AND NEITHER EXISTING GUARD COULD CATCH IT:
#   · `is_tts_enabled()` reads HOOK_TTS_ENABLED with a default of "true", so a test
#     process is opt-OUT, not opt-in — nothing had to go wrong for the line to be live.
#   · The outbound-network guard above exempts LOOPBACK_HOSTS on purpose, and the
#     notification server IS local. That run logged "outbound connections: 0" and was,
#     by that line, perfectly clean. A green guard line is not evidence that nothing
#     left the process.
#
# THIS BELONGS IN conftest, NOT IN A RUNNER SCRIPT. The run that produced the cards was a
# bare `python -m pytest src/tests/unit/`, not `run-unit-tests.sh` — an export in the
# runners would have missed it exactly as it missed this. Here it covers every invocation:
# runner, ad-hoc, IDE, CI.
#
# setdefault, NOT a hard set: a test that deliberately exercises the enabled path can
# still export HOOK_TTS_ENABLED=true for itself. The default is what changes — from
# "speak unless told otherwise" to "silent unless asked".
os.environ.setdefault( "HOOK_TTS_ENABLED", "false" )


def pytest_configure( config ):
    """
    Refuse a coverage run that cannot be attributed to this process.

    Requires:
        - config is the pytest Config for this session

    Ensures:
        - raises pytest.UsageError when --cov is active and COVERAGE_FILE is unset
          or blank, aborting BEFORE any measurement is written
        - returns silently when --cov is inactive, when COVERAGE_FILE is exported,
          or when LUPIN_ALLOW_SHARED_COVERAGE is set
    """
    cov_active = bool( getattr( config.option, "cov_source", None ) ) and \
                 not getattr( config.option, "no_cov", False )
    if not cov_active: return
    if os.environ.get( "LUPIN_ALLOW_SHARED_COVERAGE" ): return
    if os.environ.get( "COVERAGE_FILE", "" ).strip(): return

    raise pytest.UsageError(
        "COVERAGE_FILE is not set, so this --cov run would write the shared "
        "repo-root .coverage that every other session also writes and pytest-cov "
        "erases at startup. A concurrent run would silently overwrite this one and "
        "the resulting figure would be unattributable — that is how a tier run "
        "reported 96.59% while ~28,000 statements had quietly left the denominator "
        "(row aa41fa66). Export a path of your own first, e.g.\n"
        "    export COVERAGE_FILE=/tmp/cov-$USER-$$.data\n"
        "To run against the shared file on purpose, set LUPIN_ALLOW_SHARED_COVERAGE=1."
    )


def pytest_runtest_setup( item ):
    """Name the test the guard will blame, and honour its opt-out marker (row 7c84b8b8)."""
    _set_current_test( item.nodeid,
                       item.get_closest_marker( "allows_outbound_network" ) is not None )


# ONE IMPLEMENTATION, EVERY CALLER. These used to be defined here, which meant the
# node/c8 runners could not reach them — a green from those tiers carried no tree at all.
# They now live in `cosa.utils.tree_state`, which this file imports and which
# `src/scripts/lib/tree-state.sh` runs directly, so both paths render the SAME line from
# the SAME code rather than drifting apart. Design: §6b of
# `src/rnd/v0.2.0/2026.08.26-every-green-states-its-tree.md`, written before the code.
#
# `_coarse_age` comes along because it has three call sites, not one: the fetch age, the
# coverage-file age, and the module itself.
from cosa.utils.tree_state import (
    _coarse_age,
    _fetch_age,
    _git_reader,
    _primary_branch,
    _run_span,
    _tree_state_line,
    capture_start_sha,
    tree_state_line,
)


# ══════════════════════════════════════════════════════════════════════════════
# EVERY GREEN STATES THE TREE IT WAS EARNED ON (row e2099400)
# ══════════════════════════════════════════════════════════════════════════════
# A pass is a statement about a TREE, not about a repository. On a tree several
# people commit to, "the suite is green" decays the moment somebody else lands a
# commit, and nothing in the output says which tree earned it. The same defect one
# layer over: a coverage data file read seventy minutes apart reported 99% and then
# 38% for one file, because a report is rendered against the source ON DISK NOW
# rather than the source that was MEASURED (2026-08-26, row e2099400).
#
# So the run says so itself. Every pytest run — pass or fail — prints the sha it ran
# on, how far behind its comparison ref it is, and whether the tree was dirty. Then a
# green quoted tomorrow carries the tree it belongs to, and a stale one is visible
# instead of being re-derived by whoever doubts it.
#
# MOTIVATION NOTE: this reports; it decides nothing. Whether a stale worktree should
# be refreshed or reaped stays manager-gated and is deliberately not ruled here.
#
# ORDERING HOLDS BY MECHANISM: `_pytest.terminal.TerminalReporter.pytest_sessionfinish`
# is a hookimpl WRAPPER — it yields, calls `config.hook.pytest_terminal_summary(...)`
# (every plugin's line, this one included), and only THEN `self.summary_stats()`, which
# writes the counts line. So this line cannot be last on any run shape. After a pytest
# upgrade, read that one function rather than re-running a fixture and hoping.
#
# ⚠️ THE UNKNOWN CASE IS PRINTED TOO, for the same reason the network guard prints its
# zero: an instrument that goes quiet when it cannot answer is indistinguishable from
# one that was never armed, and silence would read as "not behind".



def _coverage_file_at_start():
    """
    What COVERAGE_FILE named, and whether that file ALREADY EXISTED, read once at import.

    FOUR OUTCOMES, KEPT APART: dated (it existed), fresh (absent, and this run CAN write it),
    and two flavours of unknown — the stat failed, or the parent directory is missing so no
    write will land there either. "fresh" is a promise about the next write, so it is only
    said when the directory to write into actually exists.

    ⚠️ REPORTS EXISTENCE AND AGE, AND INFERS NOTHING FURTHER. Whether a pre-existing file
    gets combined into, overwritten, or ignored depends on how the run was invoked, and a
    diagnostic that guessed at that would be asserting something it did not measure. It
    states what was on disk when this process started; the reader draws the conclusion.

    WHY IT IS READ AT IMPORT: conftest is imported before collection, and the data file is
    written at the END of a run — so a file present now is a PRIOR run's, which is exactly
    the thing worth knowing. Read it later and this process's own output is indistinguishable
    from someone else's.
    """
    path = os.environ.get( "COVERAGE_FILE" )
    if not path: return ( None, None, None )
    try:
        return ( path, _coarse_age( time.time() - os.path.getmtime( path ) ), None )
    except FileNotFoundError:
        # ⚠️ "fresh" PROMISES THIS RUN WILL WRITE HERE, so it is only honest when the
        # directory exists. Under a missing parent, coverage cannot write it either — the
        # file is absent for a reason that predicts a failing run, not because nobody has
        # got to it yet. dirname is "" for a bare filename, which means the cwd, and the
        # cwd exists by construction.
        parent = os.path.dirname( path ) or "."
        if os.path.isdir( parent ): return ( path, None, None )
        return ( path, None, "no parent dir" )
    except OSError as e:                     # ⚠️ NOT folded into the clause above, deliberately
        # "I could not look" is not "I looked and it was not there". Measured: a parent at
        # chmod 000 raises PermissionError and a path under a missing parent raises
        # FileNotFoundError, and one `except OSError` rendered BOTH as (fresh) — the second
        # merely unproven, the FIRST actively wrong, because coverage will not be able to
        # write there either. A reader needs to tell a fresh run from a blind one.
        return ( path, None, errno.errorcode.get( e.errno, str( e.errno ) ) )


_COVERAGE_FILE_AT_START = _coverage_file_at_start()


# THE SHA THIS RUN STARTED ON — captured HERE, at import, for the same reason
# `_COVERAGE_FILE_AT_START` is: a "state at start" value has to be read at the start, and
# the two live beside each other so a reader finds them together.
#
# The `[tree-state]` line is emitted from the terminal-summary hook, i.e. at the END of a
# run — so a commit landing mid-run was invisible (row 11253df9, gap 1). Measured: the
# branch moved 20+ commits inside one session, and the unit tier alone runs ~13 minutes, so
# this is an ordinary occurrence rather than a corner. With this, the line describes an
# INTERVAL and says plainly when the two ends differ.
#
# ONE git call, not a second full probe. The gap is a SHA question; branch/behind/ahead/
# fetched/dirty at start answer questions nobody asked at eight times the cost. Design:
# `src/rnd/v0.2.0/2026.08.28-tree-state-gap-1-start-and-end-sha.md` §2.
_TREE_STATE_START_SHA = capture_start_sha( _git_reader( os.path.dirname( os.path.abspath( __file__ ) ) ) )



def pytest_terminal_summary( terminalreporter, exitstatus, config ):
    """
    Report every outbound dial the run made, or say plainly that it made none.

    ⚠️ THE ZERO CASE IS PRINTED TOO, deliberately. A guard that says nothing when it found
    nothing is indistinguishable from a guard that was never armed — which is the exact
    shape of defect it exists to catch.
    """
    # FIRST, and outside every early return below: a run that ends before this has
    # printed is a green with no tree attached, which is the whole defect.
    try:
        terminalreporter.write_line( tree_state_line( _git_reader( os.path.dirname( os.path.abspath( __file__ ) ) ), _TREE_STATE_START_SHA ) )
    except Exception:                                    # pragma: no cover - a diagnostic may never fail a run
        terminalreporter.write_line( "[tree-state] UNKNOWN — the tree-state probe itself failed" )

    # SECOND, and also outside every early return: the environment that SHAPED this run.
    #
    # ⚠️ PRINTED UNCONDITIONALLY, INCLUDING network=off. The mode-gated report below says
    # nothing at all when the guard is disarmed — so a run with the guard off and a run with
    # the guard on and zero dials looked IDENTICAL in the output. Measured 2026-08-26: a unit
    # tier reported 5 errors that a baseline on the same code did not, and the whole of the
    # difference was that one run exported LUPIN_UNIT_NETWORK and the other did not. Nothing
    # in either result named the variable that decided it, so the gap read as a code change.
    #
    # A DEFAULTED MODE IS NOT THE SAME CLAIM AS A CHOSEN ONE, so the two are distinguished:
    # "off (defaulted)" says nobody asked for this, where a bare "off" would read as a decision.
    mode_txt     = _NETWORK_MODE if _NETWORK_MODE_RAW is not None else f"{_NETWORK_MODE} (defaulted)"
    cov_path, cov_age, cov_unknown = _COVERAGE_FILE_AT_START
    if cov_path is None:
        coverage_txt = "UNSET"
    elif cov_unknown is not None:
        coverage_txt = f"{cov_path} (unknown: {cov_unknown})"
    elif cov_age is None:
        coverage_txt = f"{cov_path} (fresh)"
    else:
        coverage_txt = f"{cov_path} (pre-existing, {cov_age}-ago)"
    terminalreporter.write_line( f"[test-env] network={mode_txt} coverage-file={coverage_txt}" )

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

    # ⚠️ BLOCK MODE CANNOT RELY ON ITS OWN RAISE. Measured 2026-08-17 on the cosa tier: 88
    # blocked dials produced ZERO failures in the files that made them. The raise fires at
    # the socket, but the code under test catches it — the DM quality judge is documented to
    # never raise, so every attempt was swallowed and degraded into a fallback grade. A guard
    # whose enforcement depends on the caller not catching exceptions is not enforcement; it
    # is a suggestion, and it reports GREEN on exactly the tests it was built to fail.
    #
    # So the verdict rides the SUMMARY, which nothing can swallow: in block mode, a run that
    # recorded any unexempt attempt FAILS here, whatever the individual tests decided. count
    # mode is unchanged — it reports and stays out of the way.
    if _NETWORK_MODE == "block":
        terminalreporter.write_line(
            f"[unit-network:block] FAILING THE RUN: {len( _outbound_attempts )} outbound "
            f"connection(s) from tests that did not declare @pytest.mark.allows_outbound_network. "
            f"The per-socket raise is not enough — a caller that catches exceptions swallows it, "
            f"so the run is failed here where nothing can."
        )
        # The exit status itself is set in pytest_sessionfinish, which is where pytest reads
        # it back from; this hook only says WHY, next to the list it applies to.


# ZERO-ITEM BLIND SPOT (row 08f6be8e). The check below reads the items that SURVIVED
# collection, and a module-level skip or a file with no test functions leaves NONE — so a
# tree mismatch went unreported in exactly the runs where a reader most needs to be told
# why nothing ran. `pytest_collect_file` sees the file regardless, so it is recorded here
# and used only as a fallback: a run with items behaves byte-for-byte as before.
_collected_test_files = []


def pytest_collect_file( file_path, parent ):
    from tests.worktree_tree_guard import is_test_file as _is_test_file
    if _is_test_file( str( file_path ), parent.config.getini( "python_files" ) ):
        _collected_test_files.append( str( file_path ) )
    return None


def pytest_collection_modifyitems( config, items ):
    from tests.worktree_tree_guard import check_paths as _worktree_check_paths
    from tests.worktree_tree_guard import paths_to_scan as _worktree_paths_to_scan
    _drift = _worktree_check_paths(
        _worktree_paths_to_scan(
            [ str( item.path ) for item in items if getattr( item, "path", None ) is not None ],
            _collected_test_files,
        ),
        os.environ.get( "LUPIN_ROOT" ),
    )
    if _drift is not None:
        raise pytest.UsageError( _drift )


# ══════════════════════════════════════════════════════════════════════════════
# GUARD: a failing test must not write a credential to disk (row b0e97156)
# ══════════════════════════════════════════════════════════════════════════════
# `pytest.ini` carries `--showlocals`. A test that fails inside a frame holding a
# credential therefore dumps that frame's locals into the junit XML AND the run log
# under io/test-suite/artifacts/. A paired run failed on a 401 inside `_login` and
# wrote a live password there in plaintext.
#
# ⚠️ THE FLAG STAYS. `--showlocals` is the only reason a crashed run's v1 arm metrics
# survived at all — those numbers existed nowhere but a traceback's locals, and they
# are recorded on row d8d019f6 because of it. Deleting the flag would close the leak
# by destroying the instrument. So the secret is redacted and the traceback is kept.
#
# ONE SEAM, BOTH ARTIFACTS: junit XML and the terminal/log output are two renderings of
# the SAME report object, so redacting the report before anything reads it covers both.
# Redacting the XML writer alone would have left every run log leaking — and 10 of the
# 18 exposed artifacts measured on 2026-08-19 were `.log` files, not XML.
from cosa.utils.secret_redaction import redact_report


@pytest.hookimpl( hookwrapper=True )
def pytest_runtest_makereport( item, call ):
    """
    Scrub credentials out of a test report the moment it is built.

    A hookwrapper, not a plain hook, because the post-yield half runs after the report
    exists and before any consumer reads it — the junit writer and the terminal reporter
    both take it from `pytest_runtest_logreport`, which fires later.

    Ensures:
        - never changes an outcome: it rewrites text and touches nothing else
        - never raises. A redactor that can fail a run would be switched off, and a
          control that gets switched off is worse than none — so a failure here prints
          and leaves the report alone, LOUDLY, rather than pretending it scrubbed.
    """
    outcome = yield
    try:
        redact_report( outcome.get_result() )
    except Exception as e:                               # pragma: no cover - defensive
        print( f"\n[secret-redaction] WARNING: could not redact this report: {e!r}\n"
               f"  Treat any artifact from this run as UNREDACTED.\n" )


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
        # Redact BEFORE reading the text: a collection error renders locals too, and the
        # diagnosis block below PRINTS this string. Scrubbing the run reports but not
        # this one would leak the credential through the very feature built to make
        # collection errors visible.
        redact_report( report )
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
        - in block mode, a run that recorded ANY unexempt outbound dial exits non-zero,
          even when every test that dialled passed (row 7c84b8b8 — see the terminal-summary
          note: the per-socket raise is swallowed by callers that catch broadly, so the
          verdict has to be set here, where the outcome is actually read)
    """
    if _NETWORK_MODE == "block" and _outbound_attempts:
        session.exitstatus = 1

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
