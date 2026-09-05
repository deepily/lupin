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


# ===========================================================================
# 🔴 THE TWO ARMS ABOVE PIN THE PER-FILE STUBS. THESE TWO PIN THE TIER-WIDE NET,
# AND THEY EXIST BECAUSE THE TWO MECHANISMS DID NOT COMPOSE (Rio ⚡, row b4e9b59e).
#
# The first net was an autouse fixture in conftest.py replacing the ask FUNCTION with
# a raiser. MEASURED, by printing the bound function at test-body time across the
# three files in this pair:
#
#     test_no_test_file_fires_a_live_human_ask.py        -> _refuse             (net live)
#     test_the_browser_actor_satisfies_both_endpoints.py -> _answered_in_process (net GONE)
#     test_the_edit_door_records_a_real_identity.py      -> _answered_in_process (net GONE)
#
# ⇒ A module-level autouse fixture is set up AFTER a conftest-level one, so the stub
# won the attribute — and the net was inert on EXACTLY the two files that leaked. 36
# tests passed with the net and without it. Nothing said so.
#
# ⇒ The net moved one layer down, to the notification module's own `requests` handle,
# where nothing at the function layer can revoke it. These arms are the proof, and
# they are written so that the stub above is HELD IN PLACE while they run — which is
# the bar this pair failed the first time.
# ===========================================================================


def _notify_module():
    """The module the net is installed on, imported here rather than at file scope."""
    from lupin_cli.notifications import notify_user_sync as mod
    return mod


def test_the_transport_net_survives_a_function_stub_of_the_kind_the_two_files_carry( monkeypatch ):
    """
    THE ACCEPTANCE ARM. Disable the net and this test fails WITH THE STUB IN PLACE.

    It installs the same shape of stub the two leaking files install — an override of
    `notify_user_sync` on its own module — and then asks whether the transport
    underneath is still refused. The first net answered no, silently.

    ⚠️ THE STUB IS INSTALLED FIRST AND DELIBERATELY. A version of this test that
    checked the transport on a clean module would pass against the OLD net too, and
    would therefore say nothing about the composition that actually broke.
    """
    mod = _notify_module()
    monkeypatch.setattr( mod, "notify_user_sync", lambda *a, **k: None, raising=True )
    assert mod.notify_user_sync.__name__ == "<lambda>", "the stub did not take"

    # 🔴 DECLINE BEFORE DRIVING, THE WAY THE END-TO-END ARM ALREADY DOES (Rachel 🕊️,
    # row 96d2341c). This arm proves the transport is netted by POSTING at it. With the
    # net absent that POST IS NOT REFUSED — it LEAVES THE PROCESS and lands on the real
    # notification surface. MEASURED, by object identity rather than by firing one:
    # with the autouse fixture off, `mod.requests` IS the real `requests` module.
    #
    # ⇒ So the arm that exists to catch a missing net would, on catching it, DO THE
    # THING THE NET PREVENTS — the miniature of the incident this whole file is about
    # (33 real prompts fired at Rick because nothing stopped them).
    #
    # ⚠️ THE CHECK COSTS NO DISCRIMINATION, WHICH IS WHY IT IS SAFE TO ADD. Net gone ->
    # this assertion fails and the test is RED, exactly as before; the only difference
    # is that it reddens WITHOUT a live POST. Net present -> it passes and the real
    # refusal below is still what proves the net works. Same verdict, no side effect.
    assert type( mod.requests ).__name__ == "_RefusingTransport", (
        "The transport net is not installed, so this arm is DECLINING to POST at the "
        "live notification surface to prove it is missing. That POST would reach a "
        "real person — the very failure this file exists to prevent. Restore the "
        "autouse fixture in src/tests/unit/conftest.py (row b4e9b59e)."
    )

    with pytest.raises( AssertionError ) as caught:
        mod.requests.post( "http://localhost:7999/api/notify", json={} )
    assert "LIVE human-notification transport" in str( caught.value )


def test_the_net_refuses_at_the_layer_the_incident_entered_rather_than_below_it():
    """
    THE END-TO-END ARM, driven through the gate the incident actually came through.

    The two leaking tests did not call `requests.post` — they called the promotion
    gate with enforcement active and no `ask_fn`, and the gate walked down to the live
    surface on its own. So this drives the same door: a caller who IS a manager, the
    real `_default_ask` left in place, nothing stubbed.

    ⚠️ THE GATE SWALLOWS THE REFUSAL RATHER THAN RAISING IT, BY DESIGN — a broken ask
    becomes `allowed=False` with the exception named. That is why this asserts on the
    refusal TEXT and not on a raise: an assertion on `pytest.raises` here would fail
    while the net was working perfectly.

    ⚠️ AND THIS IS WHY THE NET MUST NOT RAISE A `requests` EXCEPTION.
    `_poll_notification_response` catches `RequestException` and returns None, so a net
    built out of one would be swallowed one level lower still and the test would pass
    having asked nobody.
    """
    from cosa.rest import task_promotion_gate as gate

    # 🔴 THE NET IS CHECKED BEFORE THE PATH IS DRIVEN, AND THE ORDER IS THE WHOLE
    # SAFETY OF THIS ARM. This test drives the REAL ask. With the net installed that
    # goes nowhere. Without it, the POST leaves the process and a live card appears in
    # front of a person — so an arm that drove first and asserted afterwards would
    # REPRODUCE THE INCIDENT every time it caught it. It declines instead.
    assert type( _notify_module().requests ).__name__ == "_RefusingTransport", (
        "The tier-wide transport net is not installed, so this arm is DECLINING to "
        "drive the live ask rather than firing a real yes/no card at a person to "
        "prove the net is missing. Restore the autouse fixture in "
        "src/tests/unit/conftest.py (row b4e9b59e)."
    )

    approval = gate.approval_for_promotion(
        session_id      = "a4f2c0f8",
        actor           = "operator foolish goat",
        task_id         = "not-a-real-row",
        title           = "a row that must never reach a human from a unit test",
        is_manager_fn   = lambda *a, **k: True,
        account_persona = None,
    )

    assert approval.allowed is False, (
        "The gate ALLOWED a promotion from a unit test. Either the net is gone and a "
        "live card just went to a human, or the ask was answered by something that "
        "should not have been reachable from here."
    )
    # 🔴 RE-POINTED AT JOHN'S BOUNDARY, AND IT PINS WHICH GUARD ANSWERS (Rachel 🕊️,
    # row 96d2341c, 2026-09-04). Two guards now sit on this seam at DIFFERENT LAYERS
    # and john's is the OUTER one, so it is the one that answers here:
    #
    #   john's  HumanAskInTestError  -> INSIDE notify_user_sync(), at the ask
    #   Rio's   _RefusingTransport   -> on notify_user_sync.requests, at the transport
    #
    # This arm drives the ask function, so john's fires first and Rio's is never
    # reached. Asserting Rio's wording here was correct before john's line existed and
    # is unreachable after it — that is the ONLY thing the composition broke.
    #
    # ⚠️ ASSERTED ON ONE GUARD, NOT ON EITHER. A disjunction over both wordings would
    # pass whichever fired and could never tell you WHICH — and which one answers is
    # exactly the composition fact this arm now exists to pin. If john's boundary is
    # ever removed, this must go RED and be re-pointed deliberately, not silently fall
    # through to the layer below.
    #
    # ⚠️ AND RIO'S NET IS NOT REDUNDANT — DO NOT DELETE IT ON THE STRENGTH OF THIS ARM.
    # MEASURED: with his autouse fixture off, `notify_user_sync.requests` is the REAL
    # requests module. john's guard cannot cover that layer, because a caller reaching
    # the transport directly never enters the function his guard lives in. The two
    # guards protect DIFFERENT populations; the precondition above and
    # test_the_transport_net_survives_a_function_stub_of_the_kind_the_two_files_carry
    # are what keep the lower one honest.
    assert "A TEST TRIED TO BLOCK ON A HUMAN" in ( approval.refusal or "" ), (
        f"The gate refused, but not because the ask failed to reach anybody: "
        f"{approval.refusal!r}. A refusal for some OTHER reason — a credential check, "
        f"an unrecognised answer — would let this arm pass while the defect it names "
        f"was live, which is the whole failure mode it exists to close."
    )

    # ⚠️ AND THE ATTRIBUTION, WHICH IS THE HALF THAT WAS SILENT. Before row 96d2341c
    # this same call returned allowed=True with approval_source='keypress' — Rick's own
    # answer recorded for a question that never left the process. A refusal that
    # nonetheless carried his name would satisfy every assertion above.
    assert approval.approval_source is None, (
        f"The gate refused but still stamped an approval source "
        f"({approval.approval_source!r}). The one thing it must never do is put "
        f"Rick's name on a decision he did not make."
    )


# ===========================================================================
# 🔴 `offline` IS THE MEMBER SOMEBODY WILL DELETE, SO IT GETS ITS OWN GUARD.
#
# María read THE_NOTIFICATION_SYSTEM_ANSWERED and asked why `offline` was in a set
# about reaching a human, since an offline Rick was not reached. The question is
# correct and the membership is also correct — they are answers to different
# questions. `offline` is a SERVER-SENT SSE event: the ask got through, the server
# looked Rick up, found him not connected, and answered authoritatively with the
# default. `connection_error` is the opposite — nothing left the process, so nothing
# knows anything about him.
#
# ⇒ MEASURED, and this is why the guard exists rather than a comment: deleting
# `offline` from the set changes real behaviour — an offline Rick's promotion goes
# from ALLOWED (stamped default) to REFUSED — and the whole failing set stays
# BYTE-IDENTICAL. Nothing caught it. That is the third state this repo keeps naming:
# present, correct, and untestable-if-wrong.
#
# ⚠️ AND IT POINTS THE DANGEROUS WAY. The wrong edit is the one that LOOKS like a
# tightening, so a future reader removes it in good faith and makes Rick's absence a
# blocker — the exact standing rule this gate exists to honour.
# ===========================================================================
def test_an_offline_rick_still_gets_his_promotion_and_it_is_not_called_a_keypress():
    """
    Rick's standing rule: his ABSENCE must not become a blocker.

    Ensures:
        - an `offline` response still ALLOWS the promotion
        - it is stamped as a default, never as his keypress
        - the refusal path is not taken, so no 403 reaches the caller
    """
    from cosa.rest import task_promotion_gate as gate

    class _Offline:
        """The server's own answer: it reached the surface, he was not connected."""
        response_value = "yes"
        default_used   = True
        exit_code      = 0
        status         = "offline"

    mod = _notify_module()
    original = mod.notify_user_sync
    try:
        mod.notify_user_sync = lambda request=None, **k: _Offline()
        approval = gate.approval_for_promotion(
            session_id      = "guard",
            actor           = "operator foolish goat",
            task_id         = "a-row-promoted-while-he-was-away",
            title           = "a row promoted while he was away",
            is_manager_fn   = lambda *a, **k: True,
            account_persona = None,
        )
    finally:
        mod.notify_user_sync = original

    assert approval.allowed is True, (
        f"An OFFLINE Rick was refused: {approval.refusal!r}. His absence must not "
        f"become a blocker — that is his standing rule, and it is why 'offline' is a "
        f"member of THE_NOTIFICATION_SYSTEM_ANSWERED. If you removed it because the "
        f"name reads like 'a human was reached', read the set's comment: the ask GOT "
        f"THROUGH and the server answered about him. connection_error is the case "
        f"where nothing left the process."
    )
    assert approval.approval_source == gate.APPROVAL_DEFAULT, (
        f"An offline Rick's promotion was stamped {approval.approval_source!r}. He "
        f"never saw a card, so it can never be his keypress."
    )
