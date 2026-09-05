#!/usr/bin/env python3
"""
THE CENSUS SEAM — is the isolated directory really what the gate reads?

🔴 WHY THIS FILE EXISTS, AND IT IS A POSITIVE CONTROL RATHER THAN A FEATURE TEST.
`src/tests/unit/conftest.py` gained `_isolate_session_bridge_dir` on 2026-09-04, after
53 unit tests failed on a busy box with "FLEET CAP REFUSED THIS SPAWN — the cap is 8 and
the fleet is already running 8". The fixture points `session_bridge.SESSION_DIR` at a
per-test tmp dir, and the tier went 53 failed -> 0.

⚠️ THAT NUMBER ALONE PROVES NOTHING, and the manager who asked for this was right to say
so. "The tests stopped failing" is satisfied by TWO different worlds:

    · the seam works — the census reads the tmp dir, which is empty
    · the seam is INERT — the census still reads the live directory, and the fleet
      happened to be under the cap when I looked

**Those are indistinguishable from a green run.** An empty result is the one finding that
looks identical whether you did the work or not.

⇒ So this file plants bridges INSIDE the fixture's directory and asserts the gate SEES
them. A seam that reads nothing and a seam that reads the wrong empty thing produce the
same silence; only a POSITIVE reading tells them apart.
"""
import atexit
import json
import os
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import session_bridge
from lupin_mcp import session_spawner


# 🔴 THE PID COMES FROM THE FILENAME, NOT FROM THE JSON — and getting that wrong is how
# this file earned its keep. The first cut planted `cc-9000.json` with a live `cc_pid`
# INSIDE the body; `find_active_sessions` calls `_extract_pid_from_filename( path.name )`
# and drops the bridge before it ever opens the file, so all three planted seats vanished
# and the positive control failed.
#
# ⚠️ THAT FAILURE IS THE EVIDENCE THIS TEST IS REAL. A fixture that quietly satisfied the
# assertion would have told me nothing about whether the census runs its actual liveness
# chain. These pids are processes that genuinely exist, so the bridges survive the same
# filter a real seat's does.
# ⚠️ AND `1` IS NOT USABLE HERE, WHICH THE SECOND FAILURE TAUGHT ME. init is obviously
# running, but `_is_pid_alive( 1 )` is False for an unprivileged user — `os.kill( 1, 0 )`
# raises PermissionError, which the helper reads as dead. Measured rather than reasoned:
# with pids [ getpid(), getppid(), 1 ] the census returned 2, not 3.
#
# ⇒ THAT 2 IS ITSELF THE PROOF THE SEAM WORKS. An inert seam pointing at the operator's
# live directory would have returned whatever the box was running (8 at the time); a seam
# pointing at a directory nothing writes would have returned 0. Only a seam reading the
# planted directory can return "the planted count, minus the one bridge whose pid the
# liveness filter rejects".
# 🔴 AND THE PIDS ARE OUR OWN CHILDREN, NOT OUR ANCESTORS — row 3a00898d, 2026-09-05.
#
# This file used to source them with `_ancestor_pids( 3 )`, walking /proc upward from
# `os.getpid()`. That satisfies every requirement above and adds one nobody stated: it
# needs the run to SIT AT LEAST THREE DEEP IN THE PROCESS TREE. How deep a pytest run
# sits is a property of HOW IT WAS LAUNCHED, never of the machine or the code.
#
# MEASURED, one variable, same file / tree / sha / minute:
#     attached to a shell  ->  5 passed        ancestry 5 deep, [ …, 1558, 1326 ]
#     the SAME command
#     under `setsid`       ->  2 FAILED        ancestry [ <pytest>, 1326 ]
# A detached run — `--bg`, `nohup`, `setsid`, any harness that reparents — hangs straight
# off `systemd --user`, whose parent is init, so the walk terminates at TWO and
# `_plant( 3 )` fails its own precondition before the census is ever consulted.
#
# ⚠️ IT LOOKED EXACTLY LIKE AN ORDER-DEPENDENT POLLUTER AND IS NOT ONE. Green alone, red
# in a full tier, at three shas in three worktrees — the signature of a dirty fixture
# leaking between tests. The three tier logs settle it instead: every one shows the same
# two-deep chain ending at systemd --user, [ 592174, 1326 ] · [ 1039777, 1326 ] ·
# [ 1108955, 1326 ]. The tiers were detached; the passing runs were attached. Nothing
# about test ORDER was ever involved, and a bisect for the polluter would have searched
# 22,000 innocent tests.
#
# ⇒ SO SPAWN THE PROCESSES RATHER THAN INHERITING THEM. Children we start ourselves are
#   guaranteed to exist, guaranteed to be the count we asked for, and same-user — which
#   the `1` lesson above shows is the binding constraint, since `os.kill( 1, 0 )` raises
#   PermissionError for an unprivileged user and the liveness helper reads that as dead.
#   Launch context stops being an input.
#
# ⚠️ A SKIP WOULD HAVE BEEN THE WRONG FIX, and it is the tempting one. Skipping when the
#   ancestry is short retires this positive control in exactly the venue where tiers
#   actually run — a check that passes having compared nothing.
_HELPERS = [ ]


def _live_pids( wanted ):
    """
    `wanted` pids that are genuinely alive and OURS, independent of how this run started.

    Requires:
        - wanted is a positive integer

    Ensures:
        - returns exactly `wanted` distinct pids, every one a running child of this process
        - the children are recorded for teardown, so nothing outlives the test session
        - never depends on the depth of this process's ancestry
    """
    while len( _HELPERS ) < wanted:
        _HELPERS.append( subprocess.Popen(
            [ sys.executable, "-c", "import time; time.sleep( 3600 )" ] ) )
    return [ helper.pid for helper in _HELPERS[ :wanted ] ]


def _reap_helpers():
    """Kill every helper we started. Idempotent; never raises."""
    while _HELPERS:
        helper = _HELPERS.pop()
        try:
            helper.kill()
            helper.wait( timeout=5 )
        except Exception:
            pass


atexit.register( _reap_helpers )


@pytest.fixture( autouse=True )
def _no_helper_outlives_its_test():
    """A helper that leaked would be a live `sleep` per test run on a shared box."""
    yield
    _reap_helpers()


def _plant( count ):
    """Write `count` live-looking persona bridges into whatever SESSION_DIR now names."""
    pids      = _live_pids( count )
    directory = session_bridge.SESSION_DIR
    directory.mkdir( parents=True, exist_ok=True )
    for n in range( count ):
        ( directory / f"cc-{pids[ n ]}.json" ).write_text( json.dumps( {
            "session_id"    : f"seat-{n}",
            "voice_persona" : { "name": f"persona-{n}" },
            "cwd"           : str( directory ),
        } ) )
    return directory


def test_the_fixture_really_redirects_the_directory():
    """The cheapest half: SESSION_DIR is not the operator's live one."""
    assert "session-bridges-that-do-not-exist" in str( session_bridge.SESSION_DIR )
    assert ".claude/sessions" not in str( session_bridge.SESSION_DIR )


def test_the_census_READS_the_isolated_directory_and_not_the_live_one():
    """
    🔴 THE POSITIVE CONTROL. Plant 3 bridges in the fixture's directory; the census must
    report 3. If the seam were inert this reads the live fleet and returns whatever the
    box happens to be running — a number that moves when a manager reaps a seat, which
    is precisely the non-determinism the fixture was added to remove.
    """
    _plant( 3 )
    sessions = session_bridge.find_active_voice_persona_sessions()
    assert len( sessions ) == 3, (
        f"the census must read the isolated directory — saw {len( sessions )}. "
        f"A count that is not 3 means SESSION_DIR is not what find_active_sessions globs."
    )


def test_the_gate_REFUSES_when_the_isolated_fleet_is_at_the_cap():
    """
    And the count reaches the POLICY, not just the scan. Three planted seats against a
    cap of 3 must refuse — driving the real `default_fleet_gate` with its own config
    seam, so the arithmetic and the message are the shipped ones.
    """
    _plant( 3 )

    class _Config:
        def get( self, key, default=None, return_type="string", silent=False ):
            return { "cc session fleet size cap"         : 3,
                     "cc session fleet size cap maximum" : 18 }.get( key, default )

    refusal = session_spawner.default_fleet_gate( 1, config_fn=lambda: _Config() )
    assert refusal is not None, "a full isolated fleet must refuse"
    assert "the cap is 3" in refusal and "already running 3" in refusal


def test_an_EMPTY_isolated_fleet_allows_the_spawn():
    """
    The negative arm, and it is what makes the positive one mean something. Same gate,
    same cap, nothing planted: it must ALLOW. A gate that refused here would pass the
    test above for the wrong reason.
    """
    class _Config:
        def get( self, key, default=None, return_type="string", silent=False ):
            return { "cc session fleet size cap"         : 3,
                     "cc session fleet size cap maximum" : 18 }.get( key, default )

    assert session_spawner.default_fleet_gate( 1, config_fn=lambda: _Config() ) is None


def test_the_planted_fleet_does_not_leak_between_tests():
    """
    Each test gets its own tmp dir, so the 3 seats planted above are gone. This is the
    property that makes the tier deterministic: no test can see another's fleet, and
    none can see the operator's.
    """
    assert session_bridge.find_active_voice_persona_sessions() == [ ]
