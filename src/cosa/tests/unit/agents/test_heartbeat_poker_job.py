#!/usr/bin/env python3
"""
Unit tests — HeartbeatPokerJob (tasks I1 + I2).

I1 surfaces (design doc §6 I1 row): cadence loop, recipient routing, poke_body
JSON construction, RecipientSpec + constructor config validation.

I2 surfaces (design doc §6 I2 row): the three layered exits — clean-signal
(+ clean-exit guard), dead-man's-switch (per-recipient streak, fire-once,
escalate-not-terminate, revival reset), hard-cap — and notify() integration.

The module's Clock + CommonsGateway + notify_fn injection seams make these
tests deterministic with zero real waiting and zero mocking magic.

Run: PYTHONPATH=src python -m pytest src/cosa/tests/unit/agents/test_heartbeat_poker_job.py -v
"""

import asyncio
import json
from dataclasses import FrozenInstanceError

import pytest

from cosa.agents.heartbeat_poker_job import (
    HeartbeatPokerJob, RecipientSpec, SystemClock,
    RECIPIENT_IDENTIFIER_TYPES, RECIPIENT_ROLES,
)
from cosa.rest.queue_protocol import is_queueable_job


# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------

class FakeCommonsGateway:
    """
    Configurable commons gateway.

    All-default construction reproduces a quiet gateway (last_post_ts → None,
    read_since → []) — so the I1 tests need no special setup.

    Args:
        last_post: dict identifier → ISO ts (or a zero-arg callable returning one)
        clean_after_reads: return a termination entry on the Nth read_since call
        clean_kind: the `kind` value of that entry
        bad_kind: if True, the entry's kind is a non-matching value
    """

    def __init__( self, last_post=None, clean_after_reads=None,
                  clean_kind="implementation_done", bad_kind=False ):
        self.sent            = []                 # (recipient_identifier, body_str)
        self._last_post      = last_post or {}
        self._clean_after    = clean_after_reads
        self._clean_kind     = clean_kind
        self._bad_kind       = bad_kind
        self.read_calls      = 0
        self.read_since_args = []                 # (topic, since_iso)

    def send_to( self, recipient, body ):
        self.sent.append( ( recipient.identifier, body ) )

    def last_post_ts( self, recipient ):
        v = self._last_post.get( recipient.identifier )
        return v() if callable( v ) else v

    def read_since( self, topic, since_iso ):
        self.read_calls += 1
        self.read_since_args.append( ( topic, since_iso ) )
        if self._clean_after is not None and self.read_calls >= self._clean_after:
            kind = "some_other_kind" if self._bad_kind else self._clean_kind
            return [ { "metadata": { "kind": kind } } ]
        return []


class FakeClock:
    """Deterministic clock — advances by `seconds` per sleep; cancels the bound
    job after `cancel_after` sleeps (set high to let an exit fire naturally)."""

    def __init__( self, cancel_after=1 ):
        self._t           = 0.0
        self._sleeps      = 0
        self.cancel_after = cancel_after
        self.job          = None

    def monotonic( self ):
        return self._t

    def now_iso( self ):
        return f"2026-05-22T00:00:{int( self._t ) % 60:02d}"

    async def sleep( self, seconds ):
        self._t      += seconds
        self._sleeps += 1
        if self.job is not None and self._sleeps >= self.cancel_after:
            self.job._cancel_requested = True


def _make_job( recipients=None, clock=None, commons=None, **overrides ):
    """Build a HeartbeatPokerJob with sensible test defaults."""
    if recipients is None:
        recipients = [ RecipientSpec( identifier="tiberius", identifier_type="persona", role="watcher" ) ]
    cfg = dict(
        recipients               = recipients,
        cadence_seconds          = 30,
        termination_topic        = "impl-done",
        termination_signal_kinds = [ "implementation_done" ],
        workstream_id            = "impl-42",
        commons                  = commons if commons is not None else FakeCommonsGateway(),
        clock                    = clock,
        user_id                  = "u",
        user_email               = "u@test.com",
        session_id               = "s",
        # Default the notify seam to a no-op so unit tests NEVER emit REAL
        # notifications to the live server. Without this, jobs built without an
        # explicit notify_fn fall through to AgenticJobBase.notify_progress(),
        # whose escalation / hard-cap alarms POST to /api/notify and flood the
        # user with poker pings on every baseline run (2026-06-03 poker-flood
        # incident). Tests asserting on notifications override this with a
        # capturing fn (e.g. notify_fn=lambda msg, prio: notes.append( ... )).
        notify_fn                = lambda msg, prio: None,
    )
    cfg.update( overrides )
    return HeartbeatPokerJob( **cfg )


def _run( job, clock ):
    """Wire the clock to the job and run it; return the do_all() summary."""
    clock.job = job
    return job.do_all()


# ==========================================================================
# I1 — RecipientSpec
# ==========================================================================

def test_recipient_spec_valid():
    r = RecipientSpec( identifier="maria", identifier_type="session_id", role="observer" )
    assert ( r.identifier, r.identifier_type, r.role ) == ( "maria", "session_id", "observer" )


def test_recipient_spec_rejects_empty_identifier():
    with pytest.raises( ValueError ):
        RecipientSpec( identifier="", identifier_type="persona", role="watcher" )


def test_recipient_spec_rejects_bad_identifier_type():
    with pytest.raises( ValueError ):
        RecipientSpec( identifier="x", identifier_type="bogus", role="watcher" )


def test_recipient_spec_rejects_bad_role():
    with pytest.raises( ValueError ):
        RecipientSpec( identifier="x", identifier_type="persona", role="boss" )


def test_recipient_spec_is_frozen():
    r = RecipientSpec( identifier="x", identifier_type="persona", role="watcher" )
    with pytest.raises( FrozenInstanceError ):
        r.role = "manager"


def test_recipient_enum_constants():
    assert RECIPIENT_IDENTIFIER_TYPES == ( "persona", "session_id" )
    assert RECIPIENT_ROLES == ( "manager", "observer", "watcher" )


# ==========================================================================
# I1 — constructor config validation
# ==========================================================================

def test_config_rejects_empty_recipients():
    with pytest.raises( ValueError ):
        _make_job( recipients=[] )


def test_config_rejects_nonpositive_cadence():
    with pytest.raises( ValueError ):
        _make_job( cadence_seconds=0 )


def test_config_rejects_nonpositive_max_duration():
    with pytest.raises( ValueError ):
        _make_job( max_duration_seconds=0 )


def test_config_rejects_deadman_below_one():
    with pytest.raises( ValueError ):
        _make_job( deadman_consecutive_pokes=0 )


def test_config_rejects_empty_signal_kinds():
    with pytest.raises( ValueError ):
        _make_job( termination_signal_kinds=[] )


def test_config_rejects_empty_termination_topic():
    with pytest.raises( ValueError ):
        _make_job( termination_topic="" )


def test_config_accepts_valid_defaults():
    job = _make_job()
    assert job.deadman_consecutive_pokes == 3
    assert job.max_duration_seconds == 43_200


# ==========================================================================
# I1 — poke_body construction
# ==========================================================================

def test_build_poke_body_shape():
    job  = _make_job()
    body = job._build_poke_body( job.recipients[ 0 ] )
    assert body == { "kind": "heartbeat", "workstream": "impl-42", "role": "watcher" }


def test_build_poke_body_role_is_per_recipient():
    recips = [
        RecipientSpec( identifier="a", identifier_type="persona", role="manager" ),
        RecipientSpec( identifier="b", identifier_type="persona", role="observer" ),
    ]
    job = _make_job( recipients=recips )
    assert job._build_poke_body( recips[ 0 ] )[ "role" ] == "manager"
    assert job._build_poke_body( recips[ 1 ] )[ "role" ] == "observer"


# ==========================================================================
# I1 — cadence + recipient routing
# ==========================================================================

def test_cadence_delivers_one_poke_per_recipient_per_tick():
    clock  = FakeClock( cancel_after=3 )
    gw     = FakeCommonsGateway()
    recips = [
        RecipientSpec( identifier="tiberius", identifier_type="persona", role="watcher" ),
        RecipientSpec( identifier="maria",    identifier_type="persona", role="observer" ),
    ]
    job = _make_job( recipients=recips, clock=clock, commons=gw )
    _run( job, clock )
    assert job._tick_count == 3
    assert len( gw.sent ) == 6
    sent_ids = [ ident for ident, _ in gw.sent ]
    assert sent_ids.count( "tiberius" ) == 3
    assert sent_ids.count( "maria" ) == 3


def test_cadence_poke_body_is_valid_json_with_correct_role():
    clock = FakeClock( cancel_after=1 )
    gw    = FakeCommonsGateway()
    job   = _make_job( clock=clock, commons=gw )
    _run( job, clock )
    _, body = gw.sent[ 0 ]
    assert json.loads( body ) == { "kind": "heartbeat", "workstream": "impl-42", "role": "watcher" }


def test_clock_sleep_called_once_per_cadence():
    clock = FakeClock( cancel_after=2 )
    job   = _make_job( clock=clock, cadence_seconds=45 )
    _run( job, clock )
    assert clock.monotonic() == 90.0


def test_immediate_cancel_delivers_zero_ticks():
    clock = FakeClock( cancel_after=99 )
    gw    = FakeCommonsGateway()
    job   = _make_job( clock=clock, commons=gw )
    job._cancel_requested = True
    _run( job, clock )
    assert job._tick_count == 0
    assert gw.sent == []


# ==========================================================================
# I1 — lifecycle + integration constraints
# ==========================================================================

def test_do_all_sets_timestamps_and_summary():
    clock  = FakeClock( cancel_after=1 )
    job    = _make_job( clock=clock )
    result = _run( job, clock )
    assert job.started_at is not None
    assert job.completed_at is not None
    assert job.answer_conversational == result
    assert "exited (cancelled)" in result and "impl-42" in result


def test_last_question_asked():
    lqa = _make_job().last_question_asked
    assert "impl-42" in lqa and "1 recipient" in lqa and "30s" in lqa


def test_exit_summary_counts():
    job = _make_job()
    job._tick_count      = 5
    job._dms_escalations = 2
    s = job._exit_summary( "hard_cap" )
    assert "5 tick" in s and "2 dead-man" in s and "hard_cap" in s


def test_job_type_and_id_prefix():
    job = _make_job()
    assert job.job_type == "heartbeat_poker"
    assert job.id_hash.startswith( "hp-" )


def test_cost_summary_present_and_none():
    """
    The poker is a pure supervisor (no LLM calls) but MUST expose a
    cost_summary attribute = None — the get-queue/done serializer
    (queues.py: job.cost_summary) reads it on every completed agentic job.
    Regression for the AttributeError that 500'd /api/get-queue/done once a
    completed poker reached the done queue.
    """
    job = _make_job()
    assert hasattr( job, "cost_summary" )
    assert job.cost_summary is None


def test_satisfies_queueable_job_protocol():
    assert is_queueable_job( _make_job() )


def test_clock_defaults_to_systemclock():
    assert isinstance( _make_job( clock=None )._clock, SystemClock )


def test_systemclock_monotonic_and_now_iso():
    c = SystemClock()
    assert isinstance( c.monotonic(), float )
    assert isinstance( c.now_iso(), str ) and len( c.now_iso() ) > 0


def test_systemclock_sleep_zero_returns():
    asyncio.run( SystemClock().sleep( 0 ) )


# ==========================================================================
# I2 — hard-cap exit
# ==========================================================================

def test_hard_cap_exit():
    clock = FakeClock( cancel_after=999 )
    job   = _make_job( clock=clock, cadence_seconds=30, max_duration_seconds=60 )
    summary = _run( job, clock )
    assert "exited (hard_cap)" in summary
    assert job._tick_count == 2                          # ticks at t=0, t=30; hard-cap at t=60


def test_hard_cap_fires_notify_with_timeout_reason():
    notes = []
    clock = FakeClock( cancel_after=999 )
    job   = _make_job( clock=clock, cadence_seconds=30, max_duration_seconds=60,
                       notify_fn=lambda msg, prio: notes.append( ( msg, prio ) ) )
    _run( job, clock )
    assert len( notes ) == 1
    assert "hard cap" in notes[ 0 ][ 0 ]


def test_hard_cap_returns_normally_not_raises():
    # Clean / hard-cap / cancelled all RETURN → queue marks `done` (F-Rio-E4a).
    clock  = FakeClock( cancel_after=999 )
    job    = _make_job( clock=clock, cadence_seconds=30, max_duration_seconds=60 )
    result = _run( job, clock )                          # must not raise
    assert isinstance( result, str )


# ==========================================================================
# I2 — clean-signal exit + clean-exit guard
# ==========================================================================

def test_clean_exit_on_matching_signal():
    clock = FakeClock( cancel_after=999 )
    gw    = FakeCommonsGateway( clean_after_reads=2 )
    job   = _make_job( clock=clock, commons=gw )
    summary = _run( job, clock )
    assert "exited (clean)" in summary


def test_clean_exit_ignores_nonmatching_kind():
    clock = FakeClock( cancel_after=4 )
    gw    = FakeCommonsGateway( clean_after_reads=2, bad_kind=True )
    job   = _make_job( clock=clock, commons=gw )
    summary = _run( job, clock )
    assert "exited (cancelled)" in summary               # non-matching kind ⇒ no clean exit
    assert job._tick_count == 4


def test_clean_exit_guard_uses_job_start_ts():
    clock = FakeClock( cancel_after=999 )
    gw    = FakeCommonsGateway( clean_after_reads=2 )
    job   = _make_job( clock=clock, commons=gw )
    _run( job, clock )
    # every read_since since-arg is the captured job-start ts (the guard)
    assert job._job_start_iso is not None
    assert all( since == job._job_start_iso for _, since in gw.read_since_args )
    assert all( topic == "impl-done" for topic, _ in gw.read_since_args )


# ==========================================================================
# I2 — dead-man's-switch
# ==========================================================================

def test_deadman_fires_after_streak():
    clock = FakeClock( cancel_after=6 )
    gw    = FakeCommonsGateway()                         # last_post_ts → None ⇒ always silent
    job   = _make_job( clock=clock, commons=gw, deadman_consecutive_pokes=3 )
    _run( job, clock )
    assert job._dms_escalations == 1


def test_deadman_fires_once_per_streak():
    clock = FakeClock( cancel_after=8 )
    gw    = FakeCommonsGateway()
    job   = _make_job( clock=clock, commons=gw, deadman_consecutive_pokes=3 )
    _run( job, clock )
    assert job._dms_escalations == 1                     # once, not once-per-tick-past-threshold


def test_deadman_notify_message_names_recipient():
    notes = []
    clock = FakeClock( cancel_after=6 )
    gw    = FakeCommonsGateway()
    job   = _make_job( clock=clock, commons=gw, deadman_consecutive_pokes=3,
                       notify_fn=lambda msg, prio: notes.append( ( msg, prio ) ) )
    _run( job, clock )
    assert len( notes ) == 1
    assert "tiberius" in notes[ 0 ][ 0 ] and "silent" in notes[ 0 ][ 0 ]


def test_deadman_does_not_terminate_the_loop():
    clock = FakeClock( cancel_after=6 )
    gw    = FakeCommonsGateway()
    job   = _make_job( clock=clock, commons=gw, deadman_consecutive_pokes=3 )
    _run( job, clock )
    # escalation fires at tick 4; the loop keeps poking — 6 ticks total
    assert job._tick_count == 6


def test_deadman_per_recipient_only_silent_one_escalates():
    clock  = FakeClock( cancel_after=6 )
    gw     = FakeCommonsGateway( last_post={ "alpha": lambda: "2099-01-01T00:00:00" } )
    recips = [
        RecipientSpec( identifier="alpha", identifier_type="persona", role="manager" ),
        RecipientSpec( identifier="bravo", identifier_type="persona", role="watcher" ),
    ]
    job = _make_job( recipients=recips, clock=clock, commons=gw, deadman_consecutive_pokes=3 )
    _run( job, clock )
    assert job._dms_escalations == 1                     # only bravo (silent) escalates
    assert job._silent_streak[ "alpha" ] == 0
    assert job._dms_fired[ "bravo" ] is True


def test_responsive_recipient_never_escalates():
    clock = FakeClock( cancel_after=6 )
    gw    = FakeCommonsGateway( last_post={ "tiberius": lambda: "2099-01-01T00:00:00" } )
    job   = _make_job( clock=clock, commons=gw, deadman_consecutive_pokes=3 )
    _run( job, clock )
    assert job._dms_escalations == 0


def test_deadman_revival_resets_streak():
    # bravo: silent for 3 detections (fires at streak 3), then revives.
    calls = { "n": 0 }
    def bravo_last_post():
        calls[ "n" ] += 1
        return "2099-01-01T00:00:00" if calls[ "n" ] >= 4 else None

    clock  = FakeClock( cancel_after=7 )
    gw     = FakeCommonsGateway( last_post={ "bravo": bravo_last_post } )
    recips = [ RecipientSpec( identifier="bravo", identifier_type="persona", role="watcher" ) ]
    job    = _make_job( recipients=recips, clock=clock, commons=gw, deadman_consecutive_pokes=3 )
    _run( job, clock )
    assert job._dms_escalations == 1                     # fired once before revival
    assert job._silent_streak[ "bravo" ] == 0            # streak reset on revival
    assert job._dms_fired[ "bravo" ] is False            # fired-flag re-armed


# ==========================================================================
# I2 — _iso_is_after helper
# ==========================================================================

def test_iso_is_after_basic():
    assert HeartbeatPokerJob._iso_is_after( "2026-05-22T00:01:00", "2026-05-22T00:00:00" ) is True
    assert HeartbeatPokerJob._iso_is_after( "2026-05-22T00:00:00", "2026-05-22T00:01:00" ) is False


def test_iso_is_after_equal_is_false():
    assert HeartbeatPokerJob._iso_is_after( "2026-05-22T00:00:00", "2026-05-22T00:00:00" ) is False


def test_iso_is_after_none_args():
    assert HeartbeatPokerJob._iso_is_after( None, "2026-05-22T00:00:00" ) is False
    assert HeartbeatPokerJob._iso_is_after( "2026-05-22T00:00:00", None ) is False


def test_iso_is_after_bad_format_falls_back_lexically():
    # non-ISO strings must not raise — lexical fallback
    assert HeartbeatPokerJob._iso_is_after( "zzz", "aaa" ) is True
    assert HeartbeatPokerJob._iso_is_after( "aaa", "zzz" ) is False
