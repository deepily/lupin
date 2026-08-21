"""
Step 6c — THE SWITCH, and it has already happened.

WHAT 6c SAID AND WHY THIS FILE LOOKS DIFFERENT. The Sequence describes 6c as "wire
`push_job` to `AskFlow.run()`" — the commit where the voice path changes hands. By the
time Lane A reached it there was nothing left to wire: the switch landed through
Rachel's cutover instead of through a delegation, and it landed in pieces.

  * 11a / 11b retired the router doors that took a question and called `push_job`;
    they answer 410 now and their table is closed by test.
  * step 12 moved the seven internal callers onto `flow.submit()` / `flow.ask()`.
  * door 8 — `/api/upload-and-transcribe-mp3`, the SPOKEN way in — hands the
    transcription to the flow in-process (speech.py). That is the one that matters
    here: it is the path a person's voice actually travels.

So `push_job` has no production caller. A delegating body added to it now would be a
body nothing calls, and the plan's own step-0 lesson says what that costs: a ~440-line
function that still greps as the live voice path is exactly the trap the deprecated
snapshot manager set, where the first thing a reader finds is the thing nobody runs.

WHAT THIS FILE DOES ABOUT IT. It makes the deadness ENFORCED rather than merely true on
the day somebody checked. A sweep of the whole tree — routers included — fails the
moment any production module calls `push_job(` again, whether that is a new door, a
revived one, or a helper that means well.

WHY THE SWEEP AND NOT A RAISE. Cheech's ruling allowed "raising or asserting" on entry.
Two reasons it is a sweep instead, both worth stating rather than leaving as a silent
substitution:

  1. `push_job`'s body is still under test — `test_todo_fifo_queue_coverage.py` drives
     roughly thirty questions through it, which is the coverage 7b and 7c will need
     while they delete its internals. A guard that raised on entry would take that
     coverage out before the steps that depend on it run.
  2. A runtime tripwire has one log, and that log is EVIDENCE right now. Steps 7a and
     7c rest on a live-traffic window whose verdict is "the probe file is absent, so
     zero trips". A probe firing on every unit run creates that file and poisons the
     window. Adding a fourth probe name in the middle of the window it would corrupt
     trades a fact somebody is gathering for one this sweep already gives.

The sweep is the stronger of the two anyway: a runtime probe reports a caller AFTER it
runs in production, and this refuses to let one be committed.

⚠️ Run scoped — `pytest src/tests/unit/...` — for the reason maya's step-12 file
records: an unscoped run collects `src/tmp/`, which exits at import time. The sweep
below walks the tree itself and excludes `tmp`, so its own result is unaffected.
"""

import os
import re
import sys

import pytest


# The tokenizer-based comment/string blanker lives in the step-12 sweep, which had to
# solve the same problem first: a raw text search there ACCUSED A DOCSTRING that was
# correctly explaining what the code used to be. Importing it keeps one implementation
# of "what counts as a call" instead of two that can drift apart — and this file has the
# same need, because speech.py's door-8 comment quotes the very call being swept for.
sys.path.insert( 0, os.path.dirname( __file__ ) )
from test_step12_internal_callers_use_flow_submit import _code_only, _repo_root


# Anchored on the paren so `push_job_agentic(` — a different method, with its own live
# callers — cannot be swept up. A sweep that failed against code nobody asked to change
# gets disabled, and a disabled guard guards nothing.
_PUSH_JOB_CALL = re.compile( r"\.push_job\s*\(" )

# `push_job` still lives on TodoFifoQueue and is still exercised by the queue's own
# coverage suite, which 7b and 7c need while they delete its internals. The definition's
# own module is therefore allowed to mention it; nothing else is.
_ALLOWED = { os.path.join( "src", "cosa", "rest", "todo_fifo_queue.py" ) }


def _production_sources():
    """Every production .py file, tests and scratch excluded, ROUTERS INCLUDED.

    maya's step-12 sweep skips `routers/` on purpose — the retired doors are step 11's
    business and they still name what they replaced. This sweep does NOT skip them,
    because a door is exactly where a new caller would appear: the doors are the thing
    that used to call `push_job`, and reviving one is the failure this test exists to
    catch.
    """
    root = _repo_root()
    for dirpath, dirnames, filenames in os.walk( os.path.join( root, "src" ) ):
        dirnames[ : ] = [ d for d in dirnames if d not in ( "__pycache__", "tmp", "tests", ".git", "rnd" ) ]
        for name in filenames:
            if not name.endswith( ".py" ): continue
            full = os.path.join( dirpath, name )
            yield os.path.relpath( full, root ), full


def test_no_production_module_calls_push_job():
    """
    THE SWITCH, ENFORCED. The voice path runs through AskFlow; `push_job` is what it
    used to run through. Zero production callers is the property, and it is a property
    rather than an observation only while something checks it.

    RED ON REVERT: point any door or internal caller back at `push_job` — the shape the
    cutover removed — and this names the file.
    """
    offenders = []
    for rel, full in _production_sources():
        if rel in _ALLOWED: continue
        with open( full, errors="ignore" ) as fh:
            if _PUSH_JOB_CALL.search( _code_only( fh.read() ) ):
                offenders.append( rel )

    assert not offenders, (
        f"these production modules call push_job( ... ), which has no live path any more — "
        f"the voice door goes through AskFlow now (11a/11b retired the router doors, step 12 "
        f"moved the internal callers, door 8 hands the transcription to the flow): {sorted( offenders )}"
    )


def test_the_spoken_door_reaches_the_flow_and_not_the_queue():
    """
    THE POSITIVE HALF, and the one that makes the test above mean something. "Nothing
    calls push_job" is also true of a build where the spoken door calls nothing at all,
    or 500s. Door 8 must reach the FLOW.

    RED ON REVERT: point speech.py's agent branch back at the queue and the first
    assertion fails; delete the hand-off entirely and the second does.
    """
    source = _code_only( open( os.path.join( _repo_root(), "src", "cosa", "rest", "routers", "speech.py" ),
                               errors="ignore" ).read() )

    assert not _PUSH_JOB_CALL.search( source ), "the spoken door calls push_job again"
    assert re.search( r"\.ask\s*\(", source ), (
        "the spoken door no longer hands its transcription to the flow — a door that calls "
        "neither the queue nor the flow is not a door"
    )


def test_the_sweep_can_actually_fail( tmp_path, monkeypatch ):
    """
    THE PROBE'S OWN LESSON, applied to a static guard: "nothing was found" and "nothing
    was looked at" produce exactly the same green. A sweep that has never been seen to
    fail is an untested assertion about an untested assertion.

    So: plant a production-shaped file that calls push_job, in a tree the sweep is
    pointed at, and require the sweep to name it.
    """
    fake_root = tmp_path / "repo"
    ( fake_root / "src" / "cosa" / "rest" / "routers" ).mkdir( parents=True )
    door = fake_root / "src" / "cosa" / "rest" / "routers" / "revived_door.py"
    door.write_text( "def handler( q ):\n    return todo_queue.push_job( q, 's', 'u', 'e' )\n" )
    monkeypatch.setenv( "LUPIN_ROOT", str( fake_root ) )

    with pytest.raises( AssertionError, match="revived_door.py" ):
        test_no_production_module_calls_push_job()


def test_a_comment_naming_push_job_is_not_a_caller( tmp_path, monkeypatch ):
    """
    The other direction, and it is not hypothetical: door 8's comment QUOTES
    `todo_queue.push_job( munger.transcription )` to record the bug that cutover closed.
    That sentence is the most useful thing in the file for the next reader, and a sweep
    that accused it would get the sentence deleted rather than the guard fixed — which
    is precisely what happened to the step-12 sweep before it started tokenizing.
    """
    fake_root = tmp_path / "repo"
    ( fake_root / "src" / "cosa" ).mkdir( parents=True )
    ( fake_root / "src" / "cosa" / "historian.py" ).write_text(
        '"""This used to call todo_queue.push_job( question ) — it does not any more."""\n'
        "# nor does this: todo_queue.push_job( question )\n"
        "def handler( q ):\n    return flow.ask( q )\n"
    )
    monkeypatch.setenv( "LUPIN_ROOT", str( fake_root ) )

    test_no_production_module_calls_push_job()      # must not raise
