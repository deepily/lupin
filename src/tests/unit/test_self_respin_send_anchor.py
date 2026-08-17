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


# ---------------------------------------------------------------------------
# The SIDECAR reader — the injector's send stamp, whose MTIME is the timestamp
# ---------------------------------------------------------------------------
def test_read_keys_sent_at_absent_blank_and_present( tmp_path ):
    """Absent ⇒ None (the ordinary case for every marker written before this
    existed). Blank session id ⇒ None. Present ⇒ an AWARE mtime.

    GUARD-PROOF: return a naive datetime instead and the tzinfo assertion goes red —
    a naive value would make effective_deadline's comparison raise.
    """
    assert obs.read_keys_sent_at( str( tmp_path ), "nope" ) is None
    assert obs.read_keys_sent_at( str( tmp_path ), "" )     is None

    ( tmp_path / f"{obs.KEYS_SENT_PREFIX}sid1.marker" ).write_text( "" )
    at = obs.read_keys_sent_at( str( tmp_path ), "sid1" )
    assert at is not None
    assert at.tzinfo is not None


def test_with_keys_sent_merges_absent_and_never_clobbers( tmp_path ):
    """The merge is what carries the sidecar into the pure classifier.

    GUARD-PROOF: let the merge overwrite an existing value and the third block goes
    red; drop the dict() copy and the caller's marker is mutated — the fourth block
    catches that.
    """
    base = str( tmp_path )

    # no sidecar ⇒ the marker comes back untouched, same object
    m = _marker()
    assert obs.with_keys_sent( m, base ) is m

    # sidecar present ⇒ the field is filled in and parses as aware
    ( tmp_path / f"{obs.KEYS_SENT_PREFIX}a2715c0f.marker" ).write_text( "" )
    merged = obs.with_keys_sent( m, base )
    assert obs._parse_iso( merged[ obs.KEYS_SENT_AT ] ) is not None

    # an EXPLICIT value always wins over the file — a stale sidecar never overrides it
    explicit = _marker( keys_sent_at=_iso( _dt( 21 ) ) )
    assert obs.with_keys_sent( explicit, base )[ obs.KEYS_SENT_AT ] == _iso( _dt( 21 ) )

    # the caller's dict is never mutated
    assert obs.KEYS_SENT_AT not in m


def test_sample_records_the_send_delay_and_the_anchor():
    """The instrument has to carry the number the whole row turned on.

    GUARD-PROOF: drop send_delay_s from the sample dict and the first block goes red;
    compute it without the at-or-before-fire guard and the second block reports a
    NEGATIVE delay instead of None.
    """
    sent   = FIRED + datetime.timedelta( seconds=90 )
    marker = _marker( keys_sent_at=_iso( sent ) )
    a      = obs.classify_marker( marker, _stuck_seat(), now=DUE )
    s      = obs.build_respin_sample( marker, None, a, DUE )
    assert s[ "send_delay_s" ] == 90.0
    assert s[ "anchor" ]       == obs.ANCHOR_KEYS_SENT

    # a nonsense pre-fire stamp is recorded as UNMEASURED, never as a negative delay
    bogus = _marker( keys_sent_at=_iso( FIRED - datetime.timedelta( seconds=30 ) ) )
    b     = obs.classify_marker( bogus, _stuck_seat(), now=DUE )
    s2    = obs.build_respin_sample( bogus, None, b, DUE )
    assert s2[ "send_delay_s" ] is None
    assert s2[ "anchor" ]       == obs.ANCHOR_FIRE

    # and a stampless marker likewise
    s3 = obs.build_respin_sample( _marker(), None,
                                  obs.classify_marker( _marker(), _stuck_seat(), now=DUE ), DUE )
    assert s3[ "send_delay_s" ] is None


# ---------------------------------------------------------------------------
# The INJECTOR chain — does it ACTUALLY create the stamp?
#
# WHY THESE RUN BASH. An argv assertion ("the stamp path is argument 9") passes
# whether or not the chain ever writes the file — proven: mutations that deleted
# the write from both chains left the argv tests green. The only assertion that
# can tell the difference is one that EXECUTES the chain and looks on disk. `tmux`
# is stubbed with a script that exits 0, so nothing touches a real pane.
# ---------------------------------------------------------------------------
import os
import subprocess

import lupin_mcp.self_respin_core as sr


def _stub_tmux( tmp_path ):
    """A PATH containing a `tmux` that succeeds and does nothing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "tmux"
    stub.write_text( "#!/bin/sh\nexit 0\n" )
    stub.chmod( 0o755 )
    env = dict( os.environ )
    env[ "PATH" ] = f"{bin_dir}:{env['PATH']}"
    return env


def _run( argv, env ):
    return subprocess.run( argv, capture_output=True, text=True, timeout=30, env=env )


def test_plain_chain_actually_creates_the_send_stamp( tmp_path ):
    """GUARD-PROOF: delete the `: > "$5"` clause from the plain chain and this goes
    red. The argv-shape test does NOT — that mutation survived it.
    """
    env   = _stub_tmux( tmp_path )
    token = tmp_path / "fire.token"; token.write_text( "{}" )
    stamp = tmp_path / ".self-respin-keys-sent-sid1.marker"

    argv = sr.build_guarded_clear_argv( "sess", str( token ), 0, keys_sent_path=str( stamp ) )
    r    = _run( argv, env )

    assert r.returncode == 0, r.stderr
    assert stamp.exists()          # the stamp was written
    assert not token.exists()      # ...and the one-shot token was still consumed


def test_wake_chain_creates_the_send_stamp_before_the_readiness_poll( tmp_path ):
    """The wake chain stamps right after Enter, BEFORE it waits on the bridge mtime.
    Here the poll deliberately times out (exit 3, no wake typed) — the stamp must
    already exist anyway, because the send happened regardless of the wake.

    GUARD-PROOF: delete the `[ -n "$9" ] && : > "$9"` line and this goes red; move it
    below the poll loop and it goes red too, since the poll never succeeds here.
    """
    env    = _stub_tmux( tmp_path )
    token  = tmp_path / "fire.token"; token.write_text( "{}" )
    bridge = tmp_path / "cc-1.json";  bridge.write_text( "{}" )
    stamp  = tmp_path / ".self-respin-keys-sent-sid2.marker"

    argv = sr.build_guarded_clear_argv(
        "sess", str( token ), 0,
        wake_text="hello", bridge_path=str( bridge ), keys_sent_path=str( stamp ),
        ready_timeout_polls=1, poll_interval_seconds=0,
    )
    r = _run( argv, env )

    assert r.returncode == 3        # readiness never proven — the wake was NOT typed
    assert stamp.exists()           # ...but the send stamp is there regardless


def test_a_second_fire_after_rehydrate_writes_no_stamp( tmp_path ):
    """The one-shot guard must still short-circuit EVERYTHING, stamp included. A
    second detached fire finds the token gone and must not move the deadline by
    stamping a fresh send that never happened.

    GUARD-PROOF: change the plain chain's `&&` before the stamp to `;` and this goes
    red — the stamp would appear even though no keystrokes were sent.
    """
    env   = _stub_tmux( tmp_path )
    stamp = tmp_path / ".self-respin-keys-sent-sid3.marker"

    # no token on disk at all — this is the post-rehydrate second fire
    argv = sr.build_guarded_clear_argv( "sess", str( tmp_path / "gone.token" ), 0,
                                        keys_sent_path=str( stamp ) )
    r    = _run( argv, env )

    assert r.returncode != 0        # rm failed ⇒ the chain short-circuited
    assert not stamp.exists()       # ...and nothing was stamped


def test_chain_still_works_when_no_stamp_path_is_given( tmp_path ):
    """Back-compat: a caller that passes no keys_sent_path gets the old behaviour and
    no stray file. The bash must not choke on the empty argument.

    GUARD-PROOF: drop the `[ -n "$5" ]` emptiness check and bash tries to create a
    file named "" — the chain fails and this goes red on the returncode.
    """
    env   = _stub_tmux( tmp_path )
    token = tmp_path / "fire.token"; token.write_text( "{}" )

    r = _run( sr.build_guarded_clear_argv( "sess", str( token ), 0 ), env )

    assert r.returncode == 0, r.stderr
    assert not token.exists()
    assert not any( p.name.startswith( ".self-respin-keys-sent-" ) for p in tmp_path.iterdir() )


def test_scheduling_clears_a_stale_send_stamp_from_a_prior_cycle( tmp_path ):
    """A stamp left over from an EARLIER re-spin would anchor THIS cycle's window on
    a send that already happened — a deadline in the past, which is worse than no
    stamp at all: it would make a healthy seat look dead immediately, the exact
    failure this whole row exists to remove. The verb clears it at schedule time and
    the injector re-creates it at the fire point.

    GUARD-PROOF: delete the `_best_effort_remove( keys_sent_path )` line in
    perform_self_respin and this goes red — that mutation survived every other test
    in this file.
    """
    memento = tmp_path / ".claude-memento.md"
    nonce   = "stale-cycle-uuid"
    memento.write_text(
        "# memento\n" + sr.build_nonce_line( nonce, _dt( 20 ) ) + "\n"
    )

    stale = tmp_path / ".self-respin-keys-sent-sid9.marker"
    stale.write_text( "" )                      # the prior cycle's stamp
    assert stale.exists()

    scheduled = []
    r = sr.perform_self_respin(
        "sid9", persona="cheech", memento_path=str( memento ), memento_nonce=nonce,
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=lambda sid: "cheech-mgr", ask_fn=lambda: "yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ),
    )

    assert r.status == "scheduled"
    assert not stale.exists()                   # cleared before the new cycle armed
    # ...and the path the injector will re-create is the SAME one that was cleared
    assert str( stale ) in scheduled[ 0 ]
