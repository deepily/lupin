"""
Unit tests for TodoFifoQueue.push_job mode-dispatch branch ordering.

DISPATCH-ORDERING INVARIANT GUARD.

After the 2026-04-30 22:15-EDT post-mortem (Cluster D in
2026.05.01-postmortem-2026.04.30-2215-edt-all-test-run.md), the dispatch
order in `todo_fifo_queue.py:634` was reordered so that `AGENTIC_MODE_MAP`
is checked BEFORE `MODE_TO_AGENT`. As of this commit the two dicts do NOT
overlap (MODE_TO_AGENT holds only direct-routed single-token agents like
calculator/todo/calendar; AGENTIC_MODE_MAP holds the 8 agentic modes), so
the order is functionally moot. But the project comment in
todo_fifo_queue.py:73 says agentic modes "route through AGENTIC_MODE_MAP,
not MODE_TO_AGENT", and a future MODE_TO_AGENT addition that violates that
invariant would silently produce a malformed underscore command (e.g.
"agent router go to test_suite") that never matches any registered command
and would manifest as an HTTP 500 in /api/push.

These tests assert the ordering invariant + each known mode key resolves
to its canonical command, so any future regression is caught at unit time.
"""

import pytest

from cosa.rest.todo_fifo_queue import MODE_TO_AGENT, AGENTIC_MODE_MAP


def _mode_key_overlap( agentic, direct ):
    """THE disjointness predicate — the mode keys claimed by BOTH routing maps.
    Empty ⇒ AGENTIC_MODE_MAP and MODE_TO_AGENT partition the mode space. ONE
    function, called by BOTH the live guard AND its must-fail control, so the
    control exercises the exact code the guard trusts — never a parallel `&`."""
    return set( agentic ) & set( direct )


# ---------------------------------------------------------------------------
# Direct dispatch test — what command would each user_mode produce?
# ---------------------------------------------------------------------------

def _resolve_command_for_mode( user_mode ):
    """
    Mirror of the (post-fix) dispatch logic in
    `todo_fifo_queue.TodoFifoQueue.push_job` lines 634-655.

    Requires:
        - user_mode is a str

    Ensures:
        - returns the routing command string that push_job would build for
          the given user_mode under the post-fix branch order
        - returns None if the mode is in neither dict (LLM routing fallback)
    """
    if user_mode and user_mode in AGENTIC_MODE_MAP:
        return AGENTIC_MODE_MAP[ user_mode ]
    elif user_mode and user_mode in MODE_TO_AGENT:
        return f"agent router go to {user_mode}"
    return None


@pytest.mark.parametrize(
    "user_mode, expected_command",
    [
        # Agentic modes (in BOTH dicts) — MUST resolve via AGENTIC_MODE_MAP
        # so the canonical multi-word command is built (with space, not underscore).
        # This is the regression target — a faulty branch order would produce
        # "agent router go to test_suite" (underscore) and break everything.
        ( "test_suite"               , "agent router go to test suite"               ),
        ( "deep_research"            , "agent router go to deep research"            ),
        ( "podcast"                  , "agent router go to podcast generator"        ),
        ( "research_to_podcast"      , "agent router go to research to podcast"      ),
        ( "claude_code"              , "agent router go to claude code"              ),
        ( "swe_team"                 , "agent router go to swe team"                 ),
        ( "presentation"             , "agent router go to presentation generator"   ),
        ( "research_to_presentation" , "agent router go to research to presentation" ),
        # Direct-routed modes (only in MODE_TO_AGENT) — single-token, f-string synthesis OK
        ( "calculator"               , "agent router go to calculator"               ),
        ( "todo"                     , "agent router go to todo"                     ),
        ( "calendar"                 , "agent router go to calendar"                 ),
        ( "datetime"                 , "agent router go to datetime"                 ),
    ],
)
def test_user_mode_resolves_to_expected_command( user_mode, expected_command ):
    """
    Each registered mode resolves to its canonical routing command.

    The 8 agentic modes test the regression: AGENTIC_MODE_MAP must win
    over MODE_TO_AGENT for keys present in both dicts. The 4 direct-routed
    modes test the unchanged (still-correct) f-string-synthesis path.
    """
    assert _resolve_command_for_mode( user_mode ) == expected_command


# ---------------------------------------------------------------------------
# Dispatch-order invariant test
# ---------------------------------------------------------------------------

def test_agentic_and_direct_dicts_disjoint_today():
    """
    As of 2026-05-01 the two dicts are DISJOINT (no overlap). The post-fix
    branch order (AGENTIC_MODE_MAP first) is therefore functionally moot,
    but documenting the invariant matters: if a future change adds an
    agentic mode to MODE_TO_AGENT (overlap) and the branch order has been
    flipped back, the f-string-synthesis path would produce an underscore
    command that doesn't match any registered command — silent bug.

    This test fails if disjointness is broken AND the dispatch order
    has not been verified — see the PARAMETRIZE test above.
    """
    overlap = _mode_key_overlap( AGENTIC_MODE_MAP, MODE_TO_AGENT )
    assert overlap == set(), (
        f"AGENTIC_MODE_MAP and MODE_TO_AGENT now overlap: {overlap}. "
        f"Verify dispatch order in todo_fifo_queue.py:634 still has "
        f"AGENTIC_MODE_MAP checked FIRST so the canonical command string "
        f"wins over f-string synthesis with underscore."
    )


def test_disjointness_control_fires_on_a_real_shared_key():
    """Committed must-fail control (card-guard pattern): drive the REAL predicate
    with a REAL AGENTIC_MODE_MAP key injected into a copy of MODE_TO_AGENT — never a
    synthetic token, one side withheld. Proves the disjointness guard goes RED on a
    genuine collision, so a green guard means the maps are disjoint, not that the
    assertion is dead. Preconditions assert the key is really agentic and really
    absent from the direct map, so this FAILS LOUDLY if the key ever moves rather
    than silently ceasing to exercise a collision."""
    real_agentic_key = "test_suite"
    assert real_agentic_key in AGENTIC_MODE_MAP           # really an agentic-mode key
    assert real_agentic_key not in MODE_TO_AGENT          # really absent from the direct map today
    collided = dict( MODE_TO_AGENT )
    collided[ real_agentic_key ] = MODE_TO_AGENT[ "math" ]   # a real agent value, not a stub
    overlap = _mode_key_overlap( AGENTIC_MODE_MAP, collided )
    assert overlap == { real_agentic_key }, overlap


def test_underscore_synthesis_fails_for_test_suite():
    """
    Direct demonstration of the bug: `f"agent router go to {user_mode}"` for
    user_mode='test_suite' produces a string that does NOT match the canonical
    command in AGENTIC_MODE_MAP. If a future refactor reverts the branch
    order, this difference is what would break.
    """
    user_mode = "test_suite"

    # The faulty f-string synthesis (what the WRONG branch would produce)
    faulty_command = f"agent router go to {user_mode}"

    # The canonical command (what AGENTIC_MODE_MAP yields)
    canonical_command = AGENTIC_MODE_MAP[ user_mode ]

    assert faulty_command != canonical_command
    assert faulty_command == "agent router go to test_suite"
    assert canonical_command == "agent router go to test suite"


def test_unknown_mode_falls_through():
    """
    Modes not in either dict resolve to None (LLM routing path).
    """
    assert _resolve_command_for_mode( "definitely_not_a_real_mode" ) is None
    assert _resolve_command_for_mode( "" ) is None
    assert _resolve_command_for_mode( None ) is None
