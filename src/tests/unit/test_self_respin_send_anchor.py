"""
Unit tests for the send-anchored return window (row 855e4dd0).

WHAT IS UNDER TEST. `expected_return_by` is fired_at + delay + grace, measured
from the moment the clear was SCHEDULED. The detached job only types `/clear`
into the pane, and a pane that is mid-turn buffers those keystrokes until its
next turn boundary — so a busy seat blows through the schedule-time deadline
while being perfectly healthy, and DEAD_NO_RETURN was the observer's only
available verdict across that queued interval. When the marker carries
`keys_sent_at`, the seat gets the SAME total window measured from the send.

THE TWO PROPERTIES THAT MAKE IT SAFE, and they are what most of this file pins:
  · A MISSING STAMP NEVER BUYS SILENCE. Absent / junk / naive / not-after-fire all
    fall back to expected_return_by, which still alarms on time. The fallback
    costs certainty about which clock was right, never the alarm itself — and
    `anchor` records which clock produced the verdict.
  · MONOTONE. The send is at/after the fire, so the effective deadline is never
    EARLIER than expected_return_by. This can only retire false alarms; it can
    never manufacture a new one.

GUARD-PROOF DISCIPLINE (the rules of engagement for this row): every assertion
here was checked by reverting the thing it guards and watching it go red. The
per-test notes name the specific mutation that kills each one, so a successor can
re-run the falsification instead of trusting this sentence.
"""

import datetime

import pytest

import cosa.agents.heartbeat_arbiter.self_respin_observer as obs


UTC = datetime.timezone.utc


def _dt( minute, second=0 ):
    """A fixed aware datetime at 2026-08-14T02:{minute}:{second}Z."""
    return datetime.datetime( 2026, 8, 14, 2, minute, second, tzinfo=UTC )


def _iso( dt ):
    return dt.isoformat()


WAKE_NONCE = "wake-nonce-send-anchor"

# The window in every fixture below: fired 02:20, due back 02:22 — 120 seconds.
FIRED    = _dt( 20 )
DUE      = _dt( 22 )
WINDOW_S = 120


def _marker( *, keys_sent_at=None, fired_at=None, expected_return_by=None,
             session_id="a2715c0f", tmux_session="cheech-mgr",
             pre_clear_status="over_budget" ):
    """A synthetic marker. `keys_sent_at` is omitted entirely when None — that is
    the shape of every marker on disk today, since nothing writes the field yet."""
    marker = {
        "session_id"         : session_id,
        "persona"            : "cheech",
        "tmux_session"       : tmux_session,
        "fired_at"           : fired_at           if fired_at           is not None else _iso( FIRED ),
        "expected_return_by" : expected_return_by if expected_return_by is not None else _iso( DUE ),
        "pre_clear_status"   : pre_clear_status,
        "pre_clear_pct"      : 62.4,
        "memento_path"       : "/data/lupin/.claude-memento.md",
        "memento_verified"   : True,
        "wake_nonce"         : WAKE_NONCE,
    }
    if keys_sent_at is not None:
        marker[ obs.KEYS_SENT_AT ] = keys_sent_at
    return marker


def _stuck_seat( session_id="a2715c0f", tmux_session="cheech-mgr" ):
    """A pressure record for a seat that has NOT come back — still over budget."""
    return {
        "session_id"      : session_id,
        "tmux_session"    : tmux_session,
        "status"          : "over_budget",
        "last_turn_age_s" : 5.0,
    }


# ---------------------------------------------------------------------------
# effective_deadline — the pure resolver
# ---------------------------------------------------------------------------
def test_no_stamp_returns_the_original_deadline_on_the_fire_anchor():
    """The shape of every marker on disk today: no field at all.

    GUARD-PROOF: make the absent branch return anything but `deadline` — e.g. push
    it out by a grace period — and this goes red on the equality.
    """
    effective, anchor = obs.effective_deadline( _marker(), FIRED, DUE )
    assert effective == DUE
    assert anchor    == obs.ANCHOR_FIRE


def test_stamp_after_fire_shifts_the_window_by_the_send_delay():
    """The whole point: same window length, measured from the send.

    Sent 90s late ⇒ due 90s later, and the window is still exactly 120s.

    GUARD-PROOF: drop the re-anchor (return `deadline` unconditionally) and the
    first assertion goes red; keep the anchor but change the arithmetic to
    `sent + grace` and the window-length assertion goes red.
    """
    sent = FIRED + datetime.timedelta( seconds=90 )
    effective, anchor = obs.effective_deadline( _marker( keys_sent_at=_iso( sent ) ), FIRED, DUE )
    assert effective == sent + datetime.timedelta( seconds=WINDOW_S )
    assert effective == DUE + datetime.timedelta( seconds=90 )
    assert ( effective - sent ).total_seconds() == WINDOW_S
    assert anchor == obs.ANCHOR_KEYS_SENT


@pytest.mark.parametrize( "bad", [
    "garbage",                       # unparseable
    "2026-08-14T02:20:30",           # NAIVE — no offset
    12345,                           # not a string
    "",                              # blank
] )
def test_unusable_stamp_falls_back_to_the_fire_anchor_and_never_alarms_on_its_own( bad ):
    """A junk stamp is NOT a malformed marker. It degrades to today's behaviour.

    GUARD-PROOF: route the unparseable case to MALFORMED_MARKER (or let it raise)
    and this goes red — which is exactly the mistake the fallback exists to avoid.
    """
    effective, anchor = obs.effective_deadline( _marker( keys_sent_at=bad ), FIRED, DUE )
    assert effective == DUE
    assert anchor    == obs.ANCHOR_FIRE


@pytest.mark.parametrize( "offset_s", [ 0, -1, -600 ] )
def test_stamp_at_or_before_the_fire_cannot_shrink_the_window( offset_s ):
    """MONOTONICITY. A stamp that claims the keys were sent before they were
    scheduled is nonsense; it must never pull the deadline in and kill a seat early.

    GUARD-PROOF: relax the guard to `if sent is None` alone and the -600 case
    returns a deadline 10 minutes EARLIER than expected_return_by — red here.
    """
    sent = FIRED + datetime.timedelta( seconds=offset_s )
    effective, anchor = obs.effective_deadline( _marker( keys_sent_at=_iso( sent ) ), FIRED, DUE )
    assert effective == DUE
    assert effective >= DUE          # the property, stated directly
    assert anchor    == obs.ANCHOR_FIRE


# ---------------------------------------------------------------------------
# classify_marker — the verdict the fleet actually reads
# ---------------------------------------------------------------------------
def test_queued_clear_is_pending_not_dead_inside_the_send_anchored_window():
    """THE ROW'S HEADLINE CASE. The seat was busy, the keys were sent 90s after the
    fire, and `now` is past expected_return_by but inside the send-anchored window.

    Before this change that was DEAD_NO_RETURN on a healthy seat — a fleet-visible
    alarm about a clear that was merely queued.

    GUARD-PROOF: revert classify_marker to compare `now >= deadline` and this goes
    red with DEAD_NO_RETURN.
    """
    sent   = FIRED + datetime.timedelta( seconds=90 )
    marker = _marker( keys_sent_at=_iso( sent ) )
    now    = DUE + datetime.timedelta( seconds=30 )          # past the old deadline...
    assert now < sent + datetime.timedelta( seconds=WINDOW_S )  # ...inside the new one

    a = obs.classify_marker( marker, _stuck_seat(), now=now )
    assert a.verdict  == obs.SelfRespinVerdict.PENDING
    assert a.is_alarm is False
    assert a.anchor   == obs.ANCHOR_KEYS_SENT


def test_send_anchored_window_still_reaches_dead_no_return():
    """The re-anchor DELAYS the alarm; it must not remove it. Past the send-anchored
    deadline with no return, the seat is still declared dead.

    GUARD-PROOF: make the send-anchored branch return PENDING unconditionally and
    this goes red — that mutation is the one that would turn a real death silent.
    """
    sent = FIRED + datetime.timedelta( seconds=90 )
    now  = sent + datetime.timedelta( seconds=WINDOW_S + 1 )

    a = obs.classify_marker( _marker( keys_sent_at=_iso( sent ) ), _stuck_seat(), now=now )
    assert a.verdict  == obs.SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True
    assert a.anchor   == obs.ANCHOR_KEYS_SENT
    assert "sent" in a.reason


def test_stampless_marker_still_alarms_exactly_as_before():
    """MARÍA'S GATE: a missing stamp must NEVER go quiet. Same marker shape as every
    marker on disk today, same `now`, same alarm — only now it says which anchor it
    rested on.

    GUARD-PROOF: make the absent-stamp path skip the deadline check (treat "no
    stamp" as "cannot judge, stay PENDING") and this goes red. That mutation is the
    exact failure mode the ruling was written against.
    """
    a = obs.classify_marker( _marker(), _stuck_seat(), now=_dt( 40 ) )
    assert a.verdict  == obs.SelfRespinVerdict.DEAD_NO_RETURN
    assert a.is_alarm is True
    assert a.anchor   == obs.ANCHOR_FIRE
    assert "keys_sent_at" in a.reason      # the verdict names WHY it is the weak anchor


def test_the_anchor_is_readable_on_both_alarm_paths():
    """The two DEAD_NO_RETURN verdicts must be distinguishable by a reader, not just
    by a code path. Same verdict, same alarm flag, different anchor and reason.

    GUARD-PROOF: drop the `anchor` argument from either return and the two
    assessments become indistinguishable — red on the inequality below.
    """
    sent    = FIRED + datetime.timedelta( seconds=90 )
    strong  = obs.classify_marker( _marker( keys_sent_at=_iso( sent ) ), _stuck_seat(),
                                   now=sent + datetime.timedelta( seconds=WINDOW_S + 1 ) )
    weak    = obs.classify_marker( _marker(), _stuck_seat(), now=_dt( 40 ) )

    assert strong.verdict == weak.verdict == obs.SelfRespinVerdict.DEAD_NO_RETURN
    assert strong.is_alarm is weak.is_alarm is True
    assert strong.anchor != weak.anchor
    assert strong.reason != weak.reason


def test_lateness_stamp_stays_on_the_fire_anchor():
    """Row 491d5db8's signal must survive this change. `late` is END-TO-END: how long
    the whole cycle took from when it was asked for. A wake that returns past
    expected_return_by is still late even though the keys were sent late — that is
    precisely the degradation 491d5db8 exists to expose.

    GUARD-PROOF: re-anchor `late` on the send too and this goes red — the return
    below lands inside the send-anchored window, so it would report late=False and
    silently forgive a slow wake.
    """
    sent     = FIRED + datetime.timedelta( seconds=90 )
    returned = DUE + datetime.timedelta( seconds=30 )        # past DUE, inside the send window
    assert returned < sent + datetime.timedelta( seconds=WINDOW_S )

    rec = { "session_id"      : "a2715c0f",
            "tmux_session"    : "cheech-mgr",
            "status"          : "within_budget",
            "last_turn_age_s" : 5.0 }

    a = obs.classify_marker( _marker( keys_sent_at=_iso( sent ) ), rec,
                             now=returned, wake_proof_nonce=WAKE_NONCE, wake_proof_at=returned )
    assert a.verdict == obs.SelfRespinVerdict.RETURNED
    assert a.late is True
    assert a.return_latency_s == ( returned - FIRED ).total_seconds()
    assert a.anchor == obs.ANCHOR_FIRE


def test_malformed_marker_still_wins_over_the_send_anchor():
    """A usable keys_sent_at must not rescue a marker whose OWN timestamps cannot be
    judged — the loud-malformed gate stays in front.

    GUARD-PROOF: move the effective_deadline call above the malformed check and this
    goes red (it would classify on a window it cannot actually place in time).
    """
    sent   = FIRED + datetime.timedelta( seconds=90 )
    marker = _marker( keys_sent_at=_iso( sent ), fired_at="garbage" )

    a = obs.classify_marker( marker, _stuck_seat(), now=_dt( 40 ) )
    assert a.verdict  == obs.SelfRespinVerdict.MALFORMED_MARKER
    assert a.is_alarm is True
