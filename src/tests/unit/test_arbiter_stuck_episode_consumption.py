"""
Fix tests for bug 52b8ed6b (P3, lupin): a session that recovers by going IDLE must
CONSUME its prior cap_reached episodes. Split-off (B) from 3287ee1e.

DEFECT: `_count_stuck_episodes` consumed a prior `cap_reached` ONLY on a later `honored`
record (bug 5a1f17f8). A session that recovers via an `idle` beacon (`work_owed: false`)
consumed NOTHING — so its `stuck` flag stayed True until the events tail rolled off.
PERMANENT LIVE-STUCK: sam still rendered `LIVE STUCK` and tapped his manager at 21:49 EDT
while idle, owing nothing, bridge 0s fresh — from caps he had recovered from 8 hours earlier.

GOVERNING SAFETY PROPERTY (Mr. Radio: belongs verbatim in the record): broadening the
recovery class can only CONSUME MORE caps, so the flag can only flip True→False, NEVER
False→True. The change is MONOTONE — no consumer of `stuck` (roster, poke gate, snapshot,
render, UI) can ever see a NEW stuck session, only fewer.

RECOVERY CLASS = { honored, idle } (ratified). Membership rule, per Mr. Radio's ruling:
a recovery outcome is a beacon THE SESSION ITSELF EMITS. Excluded: `not_owed` (dead
vocabulary — never written; the writer emits `idle` instead) and
`suppressed_stale_declared_owed` (an ARBITER-side suppression marker, not a session beacon).

TRUE POSITIVE PRESERVED BY CONSTRUCTION: a genuinely wedged session emits repeated
cap_reached with `work_owed: True` and can NEVER emit `idle` (which requires
`work_owed: false`) — so its caps are never consumed, it stays stuck, and it is still
poked and still announced.

Run: pytest src/tests/unit/test_arbiter_stuck_episode_consumption.py -v   (:7999-eligible, pure)
"""
import datetime

from cosa.agents.heartbeat_arbiter.fleet_data_model import (
    _count_stuck_episodes, build_fleet_view, STUCK_REPEAT_THRESHOLD,
)
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


def _rec( outcome, ts, work_owed=True, poke_count=3, cap=3, persona="sam" ):
    """One heartbeat ACTIVITY record — `kind` is absent (None), which is what keeps it
    inside `activity_recs` (fleet_data_model.py:349 excludes idle_prompt/reaped/
    task_transition kinds). Verified against sam's real tape: his `idle` records carry
    kind=None, so the counter DOES see them — had they been idle_prompt-kind, this entire
    remedy would have been INERT."""
    return { "schema_version": 1, "session_id": "84daa020", "persona": persona, "ts": ts,
             "outcome": outcome, "poke_count": poke_count, "cap": cap,
             "work_owed": work_owed, "awaiting": None }


# ── sam's REAL tape (session 84daa020), the sequence that produced the live FP ──
SAM_TAPE = [
    _rec( "poked",       "2026-07-12T00:54:07+00:00", poke_count=2 ),
    _rec( "poked",       "2026-07-12T00:55:17+00:00", poke_count=3 ),
    _rec( "cap_reached", "2026-07-12T01:00:11+00:00" ),
    _rec( "cap_reached", "2026-07-12T01:08:13+00:00" ),
    _rec( "cap_reached", "2026-07-12T01:15:19+00:00" ),
    _rec( "idle",        "2026-07-12T01:27:32+00:00", work_owed=False ),   # ← his recovery
]


# ════════════════════════════════════════════════════════════════════════════
# Part 1 — _count_stuck_episodes: the consumption rule itself
# ════════════════════════════════════════════════════════════════════════════

def test_idle_consumes_prior_caps_sams_live_tape():
    """THE FIX, against sam's verbatim live record sequence: three caps followed by an
    `idle` recovery ⇒ ZERO live stuck episodes."""
    assert _count_stuck_episodes( SAM_TAPE ) == 0


def test_sams_tape_was_permanently_stuck_before_the_fix():
    """The defect, pinned: WITHOUT the idle recovery record, the same three caps stand —
    proving the tape's caps are genuine and it is the CONSUMPTION that was missing (not a
    miscount, and not replayed history)."""
    assert _count_stuck_episodes( SAM_TAPE[ :-1 ] ) == 3 >= STUCK_REPEAT_THRESHOLD


def test_honored_still_consumes_5a1f17f8_regression_pin():
    """5a1f17f8 REGRESSION PIN: the original `honored` recovery path is untouched."""
    tape = [ _rec( "cap_reached", "2026-07-12T01:00:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:05:00+00:00" ),
             _rec( "honored",     "2026-07-12T01:10:00+00:00" ) ]
    assert _count_stuck_episodes( tape ) == 0


def test_poked_does_NOT_consume():
    """`poked` is NOT a recovery — the session is owed + under cap, still working the
    wedge. Caps before it stand."""
    tape = [ _rec( "cap_reached", "2026-07-12T01:00:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:05:00+00:00" ),
             _rec( "poked",       "2026-07-12T01:10:00+00:00" ) ]
    assert _count_stuck_episodes( tape ) == 2


def test_re_wedge_after_idle_recovery_re_arms():
    """THE TRUE POSITIVE: a session that recovers (idle) and then wedges AGAIN counts only
    the NEW caps — recovery consumes the past, it does not grant immunity."""
    tape = SAM_TAPE + [
        _rec( "cap_reached", "2026-07-12T02:00:00+00:00" ),
        _rec( "cap_reached", "2026-07-12T02:10:00+00:00" ),
    ]
    assert _count_stuck_episodes( tape ) == 2 >= STUCK_REPEAT_THRESHOLD


def test_genuinely_wedged_session_never_consumes():
    """BY CONSTRUCTION: a wedged session OWES work (work_owed=True) and therefore can never
    emit the `idle` beacon (which requires work_owed=false). Repeated caps with no recovery
    beacon ⇒ still stuck. The detector's whole reason for existing is preserved."""
    tape = [ _rec( "poked",       "2026-07-12T01:00:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:05:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:10:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:15:00+00:00" ) ]
    assert _count_stuck_episodes( tape ) == 3


def test_cap_without_work_owed_never_counts():
    """Unchanged: only cap_reached + work_owed=True is stuck evidence."""
    tape = [ _rec( "cap_reached", "2026-07-12T01:00:00+00:00", work_owed=False ),
             _rec( "cap_reached", "2026-07-12T01:05:00+00:00", work_owed=False ) ]
    assert _count_stuck_episodes( tape ) == 0


def test_malformed_records_are_skipped():
    """Never raises on junk in the tail."""
    tape = [ "garbage", None, 42,
             _rec( "cap_reached", "2026-07-12T01:00:00+00:00" ),
             _rec( "idle",        "2026-07-12T01:20:00+00:00", work_owed=False ) ]
    assert _count_stuck_episodes( tape ) == 0


def test_empty_tail():
    assert _count_stuck_episodes( [ ] ) == 0


# ════════════════════════════════════════════════════════════════════════════
# Part 2 — build_fleet_view: the `stuck` flag the whole fleet consumes
# ════════════════════════════════════════════════════════════════════════════

NOW = datetime.datetime( 2026, 7, 12, 1, 49, 0, tzinfo=datetime.timezone.utc )   # the 21:49 EDT FP poll


def _view_for( tape ):
    return build_fleet_view( { "84daa020": list( tape ) }, [ ], NOW, 300 )


def test_fleet_view_stuck_is_FALSE_after_idle_recovery():
    """THE VISIBLE BUG, at source: at the 21:49 poll sam's view must NOT be stuck. This is
    the flag every consumer reads — roster, poke gate, snapshot, render, UI."""
    view = _view_for( SAM_TAPE )
    assert view[ "84daa020" ][ "stuck" ] is False
    assert view[ "84daa020" ][ "state" ] == "idle"


def test_fleet_view_stuck_stays_TRUE_for_a_real_wedge():
    """FAIL-SAFE: a genuinely wedged session (caps, no recovery beacon) is STILL flagged."""
    tape = [ _rec( "cap_reached", "2026-07-12T01:00:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:08:00+00:00" ) ]
    assert _view_for( tape )[ "84daa020" ][ "stuck" ] is True


# ════════════════════════════════════════════════════════════════════════════
# Part 3 — BLAST-RADIUS pins, one per ACTUATING consumer (Mr. Radio's mandate)
# ════════════════════════════════════════════════════════════════════════════

class _GW:
    def __init__( self ): self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job():
    return ArbiterConsumerJob( commons=_GW(), poll_seconds=5, manager_recipient="DeclaredMgr",
                               notify_fn=lambda *a, **k: None )


def test_blast_radius_pokeable_sessions_does_not_poke_an_idle_recovered_session():
    """CONSUMER 5 (`_pokeable_sessions` — the ACTUATING one): an idle-recovered session is
    no longer stuck ⇒ never selected for a poke. Safe by construction: it owes nothing."""
    view = _view_for( SAM_TAPE )
    assert _job()._pokeable_sessions( view ) == { }


def test_blast_radius_attention_roster_silent_even_with_a_STALE_bridge():
    """CONSUMER 1 (`_attention_workers`) — THE GAP (A) CANNOT REACH, and the whole
    justification for doing (B) at all.

    3287ee1e's bridge-fresh veto only fires when the session is demonstrably TAKING TURNS.
    A session that recovered via `idle` and then went QUIET has a STALE bridge, so the veto
    is blind to it and it would STILL be announced 'Stuck: sam'. Fixing the flag at source
    silences it — with NO bridge map threaded at all."""
    view  = _view_for( SAM_TAPE )
    view[ "84daa020" ][ "alive" ] = True                       # alive, but bridge unknown/stale
    graph = { "edges": { }, "cycles": [ ] }
    out   = _job()._attention_workers( view, graph, now=NOW, bridge_mtimes=None )
    assert out == [ ]


def test_blast_radius_real_wedge_still_rosters_and_pokes():
    """The counter-pin for BOTH actuating consumers: a genuine wedge (no recovery beacon)
    is still rostered AND still pokeable. The monotone property cuts one way only — it can
    never silence a real stall."""
    tape = [ _rec( "cap_reached", "2026-07-12T01:00:00+00:00" ),
             _rec( "cap_reached", "2026-07-12T01:08:00+00:00" ) ]
    view = _view_for( tape )
    view[ "84daa020" ][ "alive" ] = True
    job  = _job()
    out  = job._attention_workers( view, { "edges": { }, "cycles": [ ] }, now=NOW, bridge_mtimes=None )
    assert [ v[ "persona" ] for v in out ] == [ "sam" ]
    assert list( job._pokeable_sessions( view ).keys() ) == [ "84daa020" ]
