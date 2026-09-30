"""
The browser's copy of the 202 marker must match the one the server actually emits.

🔴 A THIRD RECORD OF ONE FACT. The string `awaiting_human_approval` is written in the
router (`cosa/rest/routers/tasks.py`), in the MCP client (`lupin_mcp/task_store_tools.py`,
pinned by `test_the_promotion_poll_answers_like_a_synchronous_call.py`), and now in the
browser's holding-area store. None of the three can import from another — the browser
cannot import Python at all — so the copies are pinned by test rather than shared.

⚠️ THIS GUARDS ONE CLIENT, NOT BOTH, AND THE ASYMMETRY IS DELIBERATE. `notifications.js`
discriminates on the STATUS CODE (202), not on the marker, because the raw Response is in
hand there; it therefore has no copy of this string to drift. `HoldingAreaStore` cannot do
that — `ApiClient.request` returns the parsed body and never surfaces the status — so it
reads the marker and is the only browser file this parity test has anything to pin.

Run via:
    pytest src/tests/unit/test_the_browser_202_marker_matches_the_server.py -v
"""

import os
import re

import cosa.utils.util as cu


def _read( *parts ):
    """
    Read one repo file as text.

    Requires:
        - parts spell a path relative to the project root

    Ensures:
        - returns the file's UTF-8 contents

    Raises:
        - FileNotFoundError if the path does not exist
    """
    return open( os.path.join( cu.get_project_root(), *parts ), encoding="utf-8" ).read()


def test_the_browser_marker_matches_the_one_the_server_emits():
    """
    🔴 THE DRIFT THIS MAKES LOUD. If the router's 202 body is respelled and the browser's
    copy is not, `HoldingAreaStore` stops recognising the pending answer and silently
    returns to reporting an unanswered promotion as approved — the exact defect the guard
    in `holding_area_store_202_is_not_a_success.test.ts` was written for, restored without
    that guard going red, because the guard feeds itself the marker it expects.

    ⚠️ BOTH POSITIVE CONTROLS FIRE FIRST. A pattern that finds nothing would make the
    comparison vacuous, and "I found no marker" and "the two disagree" are different facts
    wanting opposite fixes.
    """
    router_src  = _read( "src", "cosa", "rest", "routers", "tasks.py" )
    browser_src = _read( "src", "lupin_app", "static", "js", "multiplexer", "stores", "HoldingAreaStore.ts" )

    emitted = re.findall( r'"status"\s*:\s*"(awaiting_human_approval)"', router_src )
    watched = re.findall( r'AWAITING_HUMAN_APPROVAL\s*=\s*"([^"]+)"', browser_src )

    assert emitted, (
        "found no '\"status\": \"awaiting_human_approval\"' in the router — this guard did "
        "not fail, it was unable to look. Either the 202 body changed shape or the pattern "
        "is wrong, and those want opposite fixes."
    )
    assert watched, (
        "found no AWAITING_HUMAN_APPROVAL constant in HoldingAreaStore.ts — same distinction: "
        "the guard could not look, which is not the same as the two disagreeing."
    )
    assert set( watched ) <= set( emitted ), (
        f"the browser watches for {set( watched )!r} and the server emits {set( emitted )!r} — "
        f"a 202 would reach the holding-area pane as a completed approval, and the row would "
        f"paint approved for a promotion Rick has not been asked about"
    )


def test_the_vanilla_client_discriminates_on_the_code_rather_than_the_marker():
    """
    🔴 THE ASYMMETRY IS LOAD-BEARING, SO IT IS ASSERTED RATHER THAN LEFT AS PROSE.
    `notifications.js` has the raw Response and checks `response.status === 202`. If some
    later edit switched it to the marker instead, it would acquire a fourth copy of the
    string with nothing pinning it — and this file would still pass, because it only knows
    about the store. Asserting the shape here is what keeps that change from being silent.

    🔴 SCOPED TO THE METHOD BODY, AND THAT IS NOT TIDINESS — IT IS THE WHOLE ASSERTION.
    A whole-file `"response.status === 202" in js` PASSES WITHOUT THE FIX. Measured
    2026-09-08 by breaking the transition check and watching this test stay green:
    `_handleBounceClick` contains that identical string for the /api/system/bounce door
    (notifications.js:7974), so the file-wide search is satisfied by code that has nothing
    to do with promotions. An assertion satisfiable by more than one path cannot tell you
    which one ran, and this one was reading the wrong one.

    ⚠️ THE POSITIVE CONTROL FIRES FIRST. A method that could not be located would make the
    check vacuous, and "could not look" and "the check is gone" want opposite fixes.
    """
    js = _read( "src", "lupin_app", "static", "js", "notifications.js" )

    start = js.find( "async _transitionTask(" )
    assert start != -1, (
        "could not find _transitionTask in notifications.js — this guard was unable to look, "
        "not able to look and find nothing"
    )
    # The next method definition bounds the body. `_transitionTask` is followed by
    # `_patchTaskFields`-style siblings, so the next `\n    async ` at method indentation
    # is the end of it.
    end  = js.find( "\n    async ", start + 1 )
    body = js[ start : end if end != -1 else len( js ) ]

    assert "response.status === 202" in body, (
        "_transitionTask no longer discriminates the 202 on the status code; if it now reads "
        "the body marker it needs its own parity pin, which this file does not provide. "
        "(Searched only the method body — a file-wide search passes on the unrelated bounce "
        "handler at notifications.js:7974.)"
    )
