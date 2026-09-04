#!/usr/bin/env python3
"""
THE TWO FILES THAT FIRED LIVE YES/NO CARDS AT RICK STAY STUBBED — row 1544d51e.

🔴 WHAT HAPPENED, MEASURED 2026-09-04 OFF THE `:7999` CONTAINER LOG. Rick reported a
promotion prompt that "double-fires — no matter how you respond it will also refire as
soon as you answer." It was not a double-fire and it was not in the promotion code.
Twenty promotion asks sat in the log across one evening, carrying **twenty DISTINCT row
ids** and two hard-coded fixture titles, actor `operator foolish goat` every time. They
were unit tests. Two files drove `not_approved -> queued` with `enforcement_active=True`
and stubbed nothing, so `approval_for_promotion` fell through to its real
`_default_ask` -> `notify_user_sync` -> `POST http://localhost:7999/api/notify`, and a
live card appeared in his browser with `human_only=True` and 120 seconds on the clock.

⇒ Answering one card only let the notification queue promote the next. **The answer
could not matter, because the two cards were never the same question.**

=== WHY NOTHING CAUGHT IT, AND WHY THAT MATTERS FOR THIS FILE ===

⚠️ **THE TESTS PASSED EITHER WAY.** A human "yes" and a 120-second timeout BOTH return
allowed, so the assertions were green whether Rick answered, ignored the card, or was
asleep. The only symptom was two minutes of wall clock on a 22,000-test suite, which
nobody would ever attribute to one test.

⚠️ **AND THE OUTBOUND-NETWORK GUARD CANNOT SEE IT** — for two independent reasons,
either sufficient alone. `cosa/utils/unit_network_guard.py` is inert unless
`LUPIN_UNIT_NETWORK` is set (a tier prints `network=off (defaulted)`), and its
`LOOPBACK_HOSTS` exempts `localhost` and `127.*` **by construction**. The ask goes to
`localhost:7999`. So even at `LUPIN_UNIT_NETWORK=block` it sails straight through.

⇒ There was no control on this path at all. A boundary at the ask seam is being landed
separately; **this file is the per-file regression guard for the two specific files
that actually leaked**, and it is deliberately NOT that boundary.

=== WHAT THIS FILE ASSERTS, AND WHAT IT DOES NOT ===

It asserts the two files still carry an autouse fixture that moves
`lupin_cli.notifications.notify_user_sync.notify_user_sync`. Delete the fixture, rename
it, or re-point it at the wrong seam, and this goes red.

⚠️ **IT IS A WIRING CHECK AND IT SAYS SO.** It cannot prove no ask was fired — proving
that needs the boundary at the seam, which is somebody else's control and the right
place for it. What it prevents is the specific, cheap regression: a future edit that
drops the stub, restoring a defect whose only symptom is a prompt on a human's screen
that no test output mentions.

🔴 **AND IT PINS THE SEAM STRING, NOT MERELY "SOMETHING IS PATCHED."** The seam is
load-bearing and non-obvious: `approval_for_promotion` binds `ask_fn=_default_ask` as a
DEFAULT ARGUMENT, evaluated once at def time, so patching the module attribute
`_default_ask` does NOT reach it. `_default_ask` imports `notify_user_sync` INSIDE its
body, so that name resolves at CALL time and is the one seam a test can move. A stub
aimed anywhere else is decorative, and a check that accepted any patch at all would pass
a decorative one.

=== THE ARM — RUN, NOT ASSERTED ===

Baseline, stub present: **29 passed, 0 failed** across both files, and the `:7999` log
gained **0** asks (counted before and after).

Arm: the fixture's fake replaced with a raise, simulating the boundary refusing.
**Exactly 2 failed** — `test_the_browser_actor_is_admitted_when_its_LOGIN_ACCOUNT_is_an_approver`
and `test_the_TRANSITION_door_records_a_person_too`, one per file — while the other 27
stayed green. Restore verified by sha.

⇒ Two things at once, and the second is the one worth having. The stub is **load-bearing
rather than decorative**: exactly those two tests reach the seam. And it
**discriminates**: 27 tests were unmoved, so the arm is not a syntax error reddening
everything — a kill count at the size of the corpus is a broken arm until proven
otherwise.

Venue: :7999-eligible — reads two source files, no network, no mutation.
"""
import ast
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# The seam every guard on this path depends on. Spelled out here rather than imported,
# so that moving the real one has to move this string too — a constant shared with the
# thing under test would agree with it automatically, which is no test at all.
ASK_SEAM = "lupin_cli.notifications.notify_user_sync.notify_user_sync"

# The two files measured firing live cards, with the fixture each one now carries.
LEAKED = {
    "test_the_browser_actor_satisfies_both_endpoints.py": "a row waiting in the holding area",
    "test_the_edit_door_records_a_real_identity.py"     : "a row somebody edits from a browser",
}


def _module_source( basename ):
    """
    The text of one unit-test file, read from THIS tree.

    Requires:
        - basename names a file in src/tests/unit/

    Ensures:
        - returns the file's source
        - fails loudly and by name if the file has moved, rather than returning ""
          and letting every assertion below pass over an empty string
    """
    path = os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), basename )
    assert os.path.exists( path ), (
        f"{basename} is gone from src/tests/unit/. If it was renamed, this guard has to "
        f"be re-pointed — do not delete it. It is the only thing standing between a "
        f"future edit and a live prompt on Rick's screen (row 1544d51e)."
    )
    return open( path, encoding="utf-8" ).read()


def _autouse_fixture_names( source ):
    """
    Every function in a module decorated as an autouse pytest fixture.

    Parsed with `ast` rather than matched with a regex, because a regex over source
    cannot tell a decorator from the same words inside a docstring — and this file's
    subjects are two modules whose docstrings discuss autouse fixtures at length.

    Ensures:
        - returns the set of function names carrying @pytest.fixture( autouse=True )
        - a module with none returns an empty set, never None
    """
    found = set()
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ):
            continue
        for dec in node.decorator_list:
            if not isinstance( dec, ast.Call ):
                continue
            if not any( kw.arg == "autouse" and getattr( kw.value, "value", False ) is True
                        for kw in dec.keywords ):
                continue
            found.add( node.name )
    return found


@pytest.mark.parametrize( "basename", sorted( LEAKED ) )
def test_the_file_still_carries_an_autouse_fixture( basename ):
    """
    The stub is AUTOUSE, so it cannot be forgotten by a new test in the same file.

    ⚠️ AUTOUSE IS THE WHOLE POINT AND NOT A STYLE CHOICE. A named fixture protects only
    the tests that remember to request it, and the test that leaked was written by
    somebody who did not know there was anything to remember. A per-test opt-in
    re-creates the defect for test number two.
    """
    names = _autouse_fixture_names( _module_source( basename ) )
    assert names, (
        f"{basename} has NO autouse fixture. The stub that stops it firing a live "
        f"yes/no card at a human has been removed or renamed (row 1544d51e)."
    )


@pytest.mark.parametrize( "basename", sorted( LEAKED ) )
def test_the_file_moves_the_ask_seam_and_not_something_adjacent( basename ):
    """
    The stub patches the ONE name that actually intercepts the live ask.

    🔴 AIMING THIS ANYWHERE ELSE IS DECORATIVE, AND IT LOOKS IDENTICAL IN A DIFF.
    Patching `task_promotion_gate._default_ask` reads like the obvious fix and does
    nothing: `approval_for_promotion` binds `ask_fn=_default_ask` as a default argument,
    evaluated once at def time, so the caller never re-reads the module attribute.
    `_default_ask` imports `notify_user_sync` inside its body, so THAT name is resolved
    at call time — which is why it is the seam, and why this asserts the string.
    """
    source = _module_source( basename )
    assert ASK_SEAM in source, (
        f"{basename} no longer patches {ASK_SEAM}. Whatever it patches instead does not "
        f"intercept the promotion gate's ask: `ask_fn=_default_ask` is a DEFAULT "
        f"ARGUMENT bound at def time, so moving `_default_ask` itself reaches nothing. "
        f"The import inside `_default_ask` is the only seam resolved at call time."
    )


@pytest.mark.parametrize( "basename", sorted( LEAKED ) )
def test_the_fixture_that_moves_the_seam_is_the_autouse_one( basename ):
    """
    THE TWO CHECKS ABOVE PASS SEPARATELY ON A FILE WHERE THE STUB IS NOT AUTOUSE.

    ⚠️ THIS IS THE ARM THE FIRST DRAFT WAS MISSING, and it is the multi-cause defect
    this repo keeps naming: "an autouse fixture exists" and "the seam string appears
    somewhere" are both satisfiable by a file whose seam patch sits in an opt-in fixture
    a new test forgets to request. Two true assertions, and the conjunction they imply
    is not what either one measures. So bind them: the seam has to be moved INSIDE a
    body that is autouse.
    """
    source = _module_source( basename )
    tree   = ast.parse( source )
    autouse = _autouse_fixture_names( source )

    movers = {
        node.name
        for node in ast.walk( tree )
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) )
        and ASK_SEAM in ast.dump( node )
    }
    assert movers & autouse, (
        f"{basename} mentions {ASK_SEAM} but not inside an autouse fixture "
        f"(autouse: {sorted( autouse )}; moves the seam: {sorted( movers )}). An opt-in "
        f"stub protects only the tests that remember to ask for it, and the test that "
        f"leaked was written by somebody who did not know there was anything to "
        f"remember."
    )


def test_the_guard_can_actually_fail():
    """
    THE POSITIVE CONTROL. Without it, every assertion above could be passing over an
    empty parse and nobody would know — an absence is the one finding that looks the
    same whether the work was done or not.

    Ensures:
        - the ast helper finds nothing in a module that has nothing (no false positive)
        - it finds an autouse fixture in a module that has one (the instrument works)
    """
    assert _autouse_fixture_names( "def plain():\n    pass\n" ) == set()

    positive = (
        "import pytest\n"
        "@pytest.fixture( autouse=True )\n"
        "def _stub( monkeypatch ):\n"
        f"    monkeypatch.setattr( \"{ASK_SEAM}\", lambda **k: None )\n"
    )
    assert _autouse_fixture_names( positive ) == { "_stub" }
    assert ASK_SEAM in positive
