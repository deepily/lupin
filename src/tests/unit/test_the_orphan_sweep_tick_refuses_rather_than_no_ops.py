#!/usr/bin/env python3
"""
The four arms of `orphan-sweep-tick.sh`, IN THE TREE.

WHY THIS FILE EXISTS AT ALL. These arms were run by hand and reported in a DM, and Cheech
called that a defect rather than a shortfall — correctly. A receipt in a DM proves the
script worked ONCE, on one evening, on one machine, and it protects nobody afterwards: the
next edit to that script is unwatched, and the DM is not where anyone looks. **An arm that
lives in a message is a measurement; an arm that lives in the tree is a guard.**

WHAT IT PINS — the tick's whole contract is its EXIT CODE, because cron reads nothing else:

    0  swept, category (i) clean            -> the NEGATIVE CONTROL, and the one nobody asks for
    1  category (i) found AND delivered
    2  could not look                       -> the ANTI-NO-OP: never 0
    3  found, and DELIVERY FAILED           -> detection worked, the alarm did not arrive

🔴 ARM A (exit 0) IS THE LOAD-BEARING ONE. A tick that alarmed unconditionally would pass
every other arm in this file. A line that always appears carries no information, so the
clean case is what makes the firing case mean something.

🔴 AND EXIT 2 IS THE POINT OF THE WHOLE SCRIPT. Its own doctrine — lupin CLAUDE.md, § A
CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED — is that a step which cannot finish must
DECLINE and say what it did not do. The interpreter guard here failed that rule INSIDE the
refusal that implements it: it read `[ ! -x "$PY" ] && [ -z "$PY" ]`, so it fired only when
the path was both unusable AND empty, and a non-empty BROKEN path (a stale venv, a moved
interpreter) sailed through into the run. `-x` is already false for the empty string, so
the second test could never add anything and could only subtract. Cheech caught it in
review; `test_a_broken_interpreter_is_refused_not_ignored` is the arm that would have.

VENUE: :7999-eligible. Builds throwaway git repos under tmp_path, never touches the fleet,
never delivers (the API base is pointed at a closed port). ~5s.
"""
import os
import subprocess
import sys

import pytest

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src not in sys.path:
    sys.path.insert( 0, _src )

ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
TICK = os.path.join( ROOT, "src", "scripts", "orphan-sweep-tick.sh" )
PIP  = os.environ.get( "PLANNING_IS_PROMPTING_ROOT",
                       "/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting" )
SWEEP = os.path.join( PIP, "workflow", "scripts", "orphaned_head_sweep.py" )

# A port nothing listens on: delivery must FAIL, so no arm here can fire a live notify.
DEAD_API = "http://127.0.0.1:9"


def _git( cwd, *args ):
    subprocess.run( [ "git", "-C", str( cwd ), *args ], check=True,
                    capture_output=True, text=True )


@pytest.fixture
def repo( tmp_path ):
    """A repo with ONE detached worktree whose HEAD is still branch-reachable."""
    r = tmp_path / "r"
    r.mkdir()
    _git( r, "init", "-q", "-b", "the-line" )
    _git( r, "config", "user.email", "t@t" )
    _git( r, "config", "user.name",  "t" )
    ( r / "a.txt" ).write_text( "base\n" )
    _git( r, "add", "-A" )
    _git( r, "commit", "-qm", "base" )
    _git( r, "worktree", "add", "-q", "--detach", str( r / "wt" ), "HEAD" )
    return r


def _run( repo, **env ):
    e = dict( os.environ )
    e.update( {
        "LUPIN_ROOT"                   : str( repo ),
        "PLANNING_IS_PROMPTING_ROOT"   : PIP,
        "CONTEXT_TICK_TARGET_BRANCH"   : "the-line",
        "ORPHAN_TICK_API_BASE"         : DEAD_API,
    } )
    e.update( env )
    p = subprocess.run( [ "bash", TICK ], capture_output=True, text=True, env=e, timeout=300 )
    return p.returncode, p.stdout + p.stderr


@pytest.mark.skipif( not os.path.isfile( SWEEP ),
                     reason=f"planning-is-prompting sweep not resolvable at {SWEEP}" )
class TestTheTickExitCodes:
    """Each code is a different fact. Two of them used to be reachable only by accident."""

    def test_a_clean_tree_exits_0_and_delivers_NOTHING( self, repo ):
        """
        🔴 THE NEGATIVE CONTROL. Without this, a tick that alarmed unconditionally passes
        every other test here — and an alarm that always fires carries no information.
        """
        rc, out = _run( repo )
        assert rc == 0, out
        assert "clean — nothing to deliver" in out
        assert "delivering" not in out

    def test_an_orphaned_head_is_found_and_attempted( self, repo ):
        """
        ONE VARIABLE from the arm above: a commit made inside the detached worktree, so its
        HEAD is reachable from no branch. Exit 3 = found, delivery refused by the dead port
        — which also proves this suite can never fire a live notification.
        """
        wt = repo / "wt"
        ( wt / "orphan.txt" ).write_text( "work\n" )
        _git( wt, "add", "-A" )
        _git( wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "orphaned" )

        rc, out = _run( repo )
        assert rc == 3, out
        assert "category (i) UNREACHABLE" in out
        assert "DELIVERY FAILED"          in out

    def test_a_missing_sweep_is_REFUSED_never_reported_clean( self, repo, tmp_path ):
        """The anti-no-op. 'I could not look' must never share an exit code with 'clean'."""
        rc, out = _run( repo, PLANNING_IS_PROMPTING_ROOT=str( tmp_path / "nope" ) )
        assert rc == 2, out
        assert "REFUSING"          in out
        assert "Nothing was scanned" in out

    def test_a_broken_interpreter_is_refused_not_ignored( self, repo ):
        """
        🔴 THE ARM CHEECH'S REVIEW BOUGHT. The guard read `! -x && -z`, so a NON-EMPTY
        broken path — a stale venv, a moved interpreter, the realistic case — fell through
        into the run instead of refusing. An empty path refused only because `-z` happened
        to be true for it.
        """
        rc, out = _run( repo, ORPHAN_TICK_PY="/nonexistent/python" )
        assert rc == 2, out
        assert "no usable interpreter" in out
        assert "Nothing was scanned"   in out

    def test_a_GOOD_interpreter_still_runs( self, repo ):
        """
        POSITIVE CONTROL for the arm above. Without it, a guard that refused
        UNCONDITIONALLY would satisfy the broken-interpreter test and break the script.
        """
        rc, out = _run( repo, ORPHAN_TICK_PY=sys.executable )
        assert rc == 0, out
        assert "clean — nothing to deliver" in out


@pytest.mark.skipif( not os.path.isfile( SWEEP ),
                     reason="planning-is-prompting sweep not resolvable" )
def test_the_tick_never_delivers_category_ii():
    """
    Rick ruled option B: category (i) only. María ruled (ii) must never be an alert, having
    BUILT the alert version, measured it (23 of 31 branches fired) and killed it — "a wall
    of corpses, and a wall trains its reader to stop looking."

    Pinned by reading the script: the delivered payload is sliced from the (i) block and
    stops at the (ii) header. If someone widens that slice, this reddens.
    """
    text = open( TICK, encoding="utf-8" ).read()
    assert "/(i) UNREACHABLE/,/(ii)/p" in text, \
        "the delivered slice no longer stops at the (ii) header — category (ii) may now be pushed"
