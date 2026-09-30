"""
The wake alert's identity clause must DISTINGUISH three states, not print one constant.

THE DEFECT THIS PINS (row 7ad5eba6, measured 2026-09-03). `render_alert` rendered
`assessment.persona or "unknown persona"` and `assessment.session_id or "unknown
session"`. On the LIVE path the arm supplies neither — `arm_watches_for_spawn` hands
the watch a `tmux_session` and nothing else, and `persona` is not even a parameter of
`verify_respin_wake`. On a no-receipt DEAD_NO_WAKE there is no receipt to fall back to
either, so BOTH fields are None and the alert printed "unknown persona / unknown
session" on every such alarm, unconditionally.

⚠️ THE STRING WAS NEVER WRONG. IT SIMPLY NEVER VARIED. A manager read it as evidence
about the arm's inputs, built five one-variable cases on top of it, and reached a
diagnosis that had to be retracted off a closed row. A constant that looks like a
variable is worse than a missing field, because a missing field prompts a question.

⇒ WHAT THESE TESTS ASSERT, AND WHY IT IS NOT "SOME IDENTITY-ISH TEXT APPEARED".
A test satisfied by "the tmux name shows up somewhere" would pass whichever branch ran
— the same shape as the defect, one level down. So the load-bearing assertion here is
PAIRWISE DIFFERENCE: the not-supplied render and the nothing-known render must be
DIFFERENT STRINGS. Collapse them back into one constant and that assertion is the one
that fails.
"""

import datetime as dt

import pytest

from cosa.agents.heartbeat_arbiter.respin_wake_check import (
    WakeAssessment, WakeVerdict, render_alert, check_respin_wake,
)


def _assessment( *, persona=None, session_id=None, tmux_session=None ):
    """A DEAD_NO_WAKE assessment differing ONLY in which identity it carries."""
    return WakeAssessment( session_id=session_id, persona=persona,
                           verdict=WakeVerdict.DEAD_NO_WAKE,
                           reason="no boot receipt 90s after the re-spin fired",
                           is_alarm=True, tmux_session=tmux_session )


# ---------------------------------------------------------------------------
# The three states, one at a time
# ---------------------------------------------------------------------------

def test_a_known_identity_is_named():
    line = render_alert( _assessment( persona="Rio", session_id="abc12345" ) )
    assert "Rio" in line
    assert "abc12345" in line


def test_an_identity_that_never_reached_the_watch_names_the_tmux_session_it_was_armed_on():
    """The LIVE shape: tmux_session and nothing else."""
    line = render_alert( _assessment( tmux_session="cc-reviewer-mrradio-1" ) )
    assert "cc-reviewer-mrradio-1" in line
    # It must not dress an unsupplied identity as an unknown seat.
    assert "unknown persona" not in line
    assert "unknown session" not in line


def test_no_identity_at_all_says_so_rather_than_inventing_an_unknown_seat():
    line = render_alert( _assessment() )
    assert "unknown persona" not in line
    assert "unknown session" not in line


# ---------------------------------------------------------------------------
# THE DISCRIMINATOR — the assertion the old code fails
# ---------------------------------------------------------------------------

def test_the_three_states_render_three_different_strings():
    """
    Pairwise difference, as a floor. The old renderer produced the SAME string for
    the last two — that is the defect.

    ⚠️ THIS ASSERTION IS NECESSARY AND NOT SUFFICIENT, AND I LEARNED THAT FROM MY OWN
    MUTATION ARM RATHER THAN BY READING IT. An arm that collapsed the two identityless
    branches into one f-string SURVIVED this test, because the surviving branch
    interpolates `tmux` — which is a name in one case and None in the other. The two
    renders still differed, so the assertion held while the branch it was written to
    protect had been deleted. The strings differed because the DATA differed, not
    because the code chose differently. `test_each_identityless_state_carries_its_own_
    branch_marker` below is what actually kills that arm; this one stays as the floor.
    """
    known        = render_alert( _assessment( persona="Rio", session_id="abc12345" ) )
    not_supplied = render_alert( _assessment( tmux_session="cc-reviewer-mrradio-1" ) )
    nothing      = render_alert( _assessment() )

    assert known        != not_supplied
    assert not_supplied != nothing
    assert known        != nothing


def test_each_identityless_state_carries_its_own_branch_marker():
    """
    THE ARM-KILLING ASSERTION. Difference between two renders can come from the data;
    a marker that belongs to ONE branch cannot. So assert what each branch says about
    ITSELF:

      · not-supplied  names a tmux session, because it HAS one
      · nothing-known must NOT name a tmux session, because there is none to name —
        and an f-string that interpolates a missing one prints "None", which is how
        the collapsed version gives itself away

    Merge the two branches in either direction and one of these fails, whatever the
    interpolated values happen to be.
    """
    not_supplied = render_alert( _assessment( tmux_session="cc-reviewer-mrradio-1" ) )
    nothing      = render_alert( _assessment() )

    assert "tmux session" in not_supplied
    assert "tmux session" not in nothing, (
        "the nothing-known branch is rendering the not-supplied text — it has no tmux "
        "session to name, so naming one means the two states collapsed"
    )
    assert "None" not in nothing, (
        "a missing identity is being interpolated into the message as the string "
        "'None' — the collapsed branch's signature"
    )


def test_the_old_constant_is_gone_from_the_two_identityless_states():
    """
    A negative control aimed at the exact bytes the defect emitted. Named separately
    from the pairwise test so a failing SET says WHICH property broke.
    """
    for assessment in ( _assessment( tmux_session="cc-reviewer-mrradio-1" ), _assessment() ):
        line = render_alert( assessment )
        assert "unknown persona / unknown session" not in line


# ---------------------------------------------------------------------------
# At the layer the incident entered at
# ---------------------------------------------------------------------------

def test_the_live_arm_shape_produces_an_alert_that_names_the_seat( tmp_path ):
    """
    Drives `check_respin_wake` with EXACTLY the kwargs the live arm supplies —
    tmux_session and base_dir, no persona, no session_id — past the deadline with
    no receipt on disk. This is the shape that produced the unreadable alert.
    """
    fired_at = dt.datetime.now().astimezone() - dt.timedelta( seconds=600 )

    assessment = check_respin_wake(
        fired_at         = fired_at,
        tmux_session     = "cc-reviewer-mrradio-1",
        base_dir         = str( tmp_path ),
        deadline_seconds = 1,
        sleep_fn         = lambda _s: None,
    )

    assert assessment.verdict is WakeVerdict.DEAD_NO_WAKE
    assert assessment.tmux_session == "cc-reviewer-mrradio-1", (
        "the watch knew the seat's tmux name and must carry it onto the assessment"
    )
    line = render_alert( assessment, fired_at=fired_at )
    assert "cc-reviewer-mrradio-1" in line
    assert "unknown persona / unknown session" not in line
