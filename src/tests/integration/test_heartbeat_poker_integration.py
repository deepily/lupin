#!/usr/bin/env python3
"""
Integration test — HeartbeatPokerJob over the REAL commons gateway (task I6).

WHAT THIS TIER ADDS, and why it is not a second unit suite. The unit tier
(`src/cosa/tests/unit/agents/test_heartbeat_poker_job.py`) drives the poker
against a `FakeCommonsGateway` that appends to an in-memory list. It therefore
proves the poker's LOOP logic and nothing about the seam the poker actually
ships on. Every one of these exercises the real `LupinCommonsGateway` over a
real `CommonsStore` writing real topic files:

  · `dm_topic_for` slug derivation, including the accent normalisation that once
    produced the split `dm-maría` / `dm-maria` pair;
  · the poke envelope surviving a write/parse round-trip through the store's
    on-disk entry format, metadata included;
  · `read( topic, since=... )` timestamp filtering, which is the entire clean-
    exit guard (F-Rio-C4) — a stale signal from a prior run must not stop a new
    job at tick 1;
  · `who()`-derived `last_post_ts`, which is how a recipient is scored silent or
    revived, and which the fake replaced with a counter.

VENUE — integration tier, scheduled on :8000 via `POST /api/test-suite/submit`.
NOTE FOR WHOEVER ROUTES THIS: as written these tests are hermetic. The store is
built on pytest's `tmp_path`, the clock and the HTTP push are injected, and no
assertion depends on a running server, so nothing here mutates shared state and
the file runs in well under a second. The venue is inherited from the row, not
required by the code — worth revisiting rather than assuming.

WHY THE `/api/dm/send` PUSH IS INJECTED RATHER THAN LIVE. The gateway's own
contract makes the disk post authoritative and the push best-effort: a recipient
that misses the push still sees the poke on its next commons poll. Binding these
assertions to a live push would make the tier flaky for a leg the product
deliberately does not guarantee. What IS asserted is the contract the gateway
states explicitly — that a failing push never loses the poke and is never
swallowed silently.

Design: `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d1d4-class-spec.md`
"""

import json

import pytest

from cosa.agents.heartbeat_poker_job import HeartbeatPokerJob, RecipientSpec
from cosa.agents.heartbeat_poker_commons_gateway import LupinCommonsGateway
from lupin_mcp.commons_store import CommonsStore


POKER_SESSION_ID = "poker-session-0001"
POKER_PERSONA    = "heartbeat-poker"


class StubResponse:
    """Minimal `requests.Response` stand-in — the gateway reads status_code + text."""

    def __init__( self, status_code=200, text="" ):
        self.status_code = status_code
        self.text        = text


class RecordingPost:
    """
    A `requests.post`-compatible callable that records calls instead of sending.

    `failure` is an exception to raise (transport failure) or a StubResponse with
    a >=400 status (refusal); None means a clean 200.
    """

    def __init__( self, failure=None ):
        self.calls   = []
        self.failure = failure

    def __call__( self, url, json=None, headers=None, timeout=None ):
        self.calls.append( { "url": url, "json": json, "headers": headers } )
        if isinstance( self.failure, Exception ):
            raise self.failure
        if isinstance( self.failure, StubResponse ):
            return self.failure
        return StubResponse( 200 )


class StepClock:
    """
    Deterministic `Clock` — skips the real waiting, keeps the real calendar.

    The two axes are deliberately decoupled, and getting that wrong is what a
    first run here catches:

      · `monotonic()` advances by the full cadence on every sleep, so the hard-cap
        branch can be driven in milliseconds.
      · `now_iso()` tracks ACTUAL wall-clock UTC, nudged forward a microsecond per
        read so two reads never collide and a strictly-after comparison is never
        ambiguous.

    `now_iso` must stay on the real calendar because the poker's timestamps are
    compared against timestamps the STORE generates — `read( since=... )` filtering
    and `who()`'s retention window both stamp entries with real `datetime.now`.
    A clock that jumped its wall time forward by a cadence per tick would leave
    the job's own `_job_start_iso` in the future relative to the store's posts,
    and every "was this posted after we started" question would answer wrongly.
    That is an instrument defect that reads exactly like a broken stale-signal
    guard, which is why the two axes are separated here rather than shared.
    """

    def __init__( self, job=None, cancel_after=3, cadence=60 ):
        self._mono         = 0.0
        self._nudge        = 0
        self.job           = job
        self.cancel_after  = cancel_after
        self.cadence       = cadence
        self.sleeps        = 0

    def monotonic( self ):
        return self._mono

    def now_iso( self ):
        from datetime import datetime, timezone, timedelta
        self._nudge += 1
        return ( datetime.now( timezone.utc ) + timedelta( microseconds=self._nudge ) ).isoformat()

    async def sleep( self, seconds ):
        self.sleeps += 1
        self._mono  += seconds
        if self.job is not None and self.sleeps >= self.cancel_after:
            self.job.request_cancel()


def build_gateway( tmp_path, http_post=None ):
    """Real CommonsStore + real LupinCommonsGateway, rooted at an isolated tmp dir."""
    store   = CommonsStore( tmp_path )
    gateway = LupinCommonsGateway(
        sender_session_id = POKER_SESSION_ID,
        api_key           = "test-api-key",
        api_base_url      = "http://localhost:8000",
        store             = store,
        http_post         = http_post if http_post is not None else RecordingPost(),
        persona_name      = POKER_PERSONA,
        persona_icon      = "💓",
        persona_color     = "#0277BD",
    )
    return store, gateway


def build_poker( gateway, recipients, cancel_after=3, **kwargs ):
    """Construct a poker on the real gateway with a deterministic clock attached."""
    clock  = StepClock( cancel_after=cancel_after, cadence=kwargs.pop( "cadence_seconds", 60 ) )
    notes  = []
    poker  = HeartbeatPokerJob(
        recipients               = recipients,
        cadence_seconds          = clock.cadence,
        termination_topic        = kwargs.pop( "termination_topic", "coordination" ),
        termination_signal_kinds = kwargs.pop( "termination_signal_kinds", [ "implementation_done" ] ),
        workstream_id            = kwargs.pop( "workstream_id", "ws-i6" ),
        commons                  = gateway,
        clock                    = clock,
        notify_fn                = lambda message, priority: notes.append( ( message, priority ) ),
        **kwargs,
    )
    clock.job = poker
    return poker, clock, notes


# ---------------------------------------------------------------------------
# I6-1 — pokes reach the recipient's real dm-<persona> topic
# ---------------------------------------------------------------------------

def test_poker_pokes_recipient_end_to_end( tmp_path ):
    """
    A poker driving the REAL gateway lands one poke per recipient per tick on
    that recipient's real `dm-<persona>` commons topic, and each poke body
    survives the store's write/parse round-trip as the exact
    `{kind, workstream, role}` envelope.

    The accented recipient is deliberate: `"María"` must converge on the single
    canonical topic `dm-maria`, and the accented variant `dm-maría` must not be
    created at all. That split-topic pair was a live bug.
    """
    store, gateway = build_gateway( tmp_path )
    recipients = [
        RecipientSpec( identifier="María",     identifier_type="persona", role="manager" ),
        RecipientSpec( identifier="Mr. Radio", identifier_type="persona", role="observer" ),
    ]
    poker, clock, _notes = build_poker( gateway, recipients, cancel_after=3, workstream_id="ws-i6-alpha" )

    poker.do_all()

    # Three sleeps → cancellation is observed at the top of the 4th iteration,
    # so exactly three ticks were delivered.
    assert poker._tick_count == 3, f"expected exactly 3 ticks, got {poker._tick_count}"

    for recipient, expected_role in ( ( "maria", "manager" ), ( "mr_radio", "observer" ) ):
        topic   = f"dm-{recipient}"
        entries = store.read( topic, limit=100 )
        assert len( entries ) == 3, f"{topic}: expected exactly 3 pokes, got {len( entries )}"

        for entry in entries:
            assert json.loads( entry[ "body" ] ) == {
                "kind"       : "heartbeat",
                "workstream" : "ws-i6-alpha",
                "role"       : expected_role,
            }, f"{topic}: poke envelope did not round-trip intact"

        # The store stamps identity + correlation metadata the receipt-polling
        # substrate depends on; a poke that arrives anonymous is not a poke.
        assert entries[ 0 ][ "sender_session_id" ] == POKER_SESSION_ID
        assert entries[ 0 ][ "persona_name" ]      == POKER_PERSONA
        assert entries[ 0 ][ "metadata" ][ "kind" ] == "heartbeat"

    # The accent-leaky topic must not exist — one canonical file, not a split pair.
    assert not ( tmp_path / "io" / "commons" / "dm-maría.md" ).exists(), \
        "accented duplicate topic dm-maría.md was created — slug derivation regressed"

    # Correlation: each disk post's question_id is echoed as the push thread_id,
    # which is what lets board-polling receipts match a push after the fact.
    posted_qids = { e[ "metadata" ][ "question_id" ] for e in store.read( "dm-maria", limit=100 ) }
    pushed_tids = { c[ "json" ][ "thread_id" ] for c in gateway._http_post.calls
                    if c[ "json" ][ "recipient_persona" ] == "María" }
    assert posted_qids == pushed_tids, "disk question_id and push thread_id diverged"


def test_poke_survives_a_failing_push_and_is_logged( tmp_path, capsys ):
    """
    The gateway states the disk post is authoritative and the push best-effort,
    and that a non-2xx must be inspected explicitly "or it vanishes exactly as
    the swallowed exception once let it". Both failure arms are checked here:
    the poke still lands, and the failure is reported rather than silent.
    """
    refusing = RecordingPost( failure=StubResponse( 413, "payload too large" ) )
    store, gateway = build_gateway( tmp_path, http_post=refusing )
    recipients = [ RecipientSpec( identifier="Clayton", identifier_type="persona", role="watcher" ) ]
    poker, _clock, _notes = build_poker( gateway, recipients, cancel_after=2 )

    poker.do_all()

    entries = store.read( "dm-clayton", limit=100 )
    assert len( entries ) == 2, f"a refused push lost pokes: expected 2 on disk, got {len( entries )}"

    captured = capsys.readouterr().err
    assert captured.count( "[HEARTBEAT_POKE_SEND_FAILED]" ) == 2, \
        "a refused push was not logged once per poke"
    assert "status=413" in captured, "the refusal status code was not reported"


# ---------------------------------------------------------------------------
# I6-2 — clean exit, and the stale-signal guard
# ---------------------------------------------------------------------------

def test_stale_pre_start_signal_does_not_stop_the_poker( tmp_path ):
    """
    A termination signal posted BEFORE the job starts is a leftover from a prior
    run and must not stop this one at tick 1. This is the whole of F-Rio-C4, and
    it rests on the real store's `since=` filtering — the fake gateway could not
    express it.
    """
    store, gateway = build_gateway( tmp_path )
    store.post(
        topic             = "coordination",
        body              = "previous run finished",
        sender_session_id = "someone-else",
        metadata          = { "kind": "implementation_done" },
    )

    recipients = [ RecipientSpec( identifier="Clayton", identifier_type="persona", role="watcher" ) ]
    poker, _clock, _notes = build_poker( gateway, recipients, cancel_after=3 )

    poker.do_all()

    assert poker._tick_count == 3, \
        f"a stale pre-start signal stopped the poker early: {poker._tick_count} tick(s)"
    assert "(cancelled)" in poker.answer_conversational, \
        f"expected a cancelled exit, got: {poker.answer_conversational}"


def test_poker_clean_exit_on_termination_signal( tmp_path ):
    """
    A termination-signal kind posted to the termination topic AFTER job start
    drives a clean exit: the loop returns normally, the summary names `clean`,
    and no further pokes are delivered.
    """
    store, gateway = build_gateway( tmp_path )
    recipients = [ RecipientSpec( identifier="Clayton", identifier_type="persona", role="watcher" ) ]
    poker, clock, _notes = build_poker( gateway, recipients, cancel_after=99 )

    # Post the signal from inside the loop, after two completed ticks, so it is
    # unambiguously after `_job_start_iso`.
    original_sleep = clock.sleep

    async def sleep_then_signal( seconds ):
        await original_sleep( seconds )
        if clock.sleeps == 2:
            store.post(
                topic             = "coordination",
                body              = "work finished",
                sender_session_id = "manager-session",
                metadata          = { "kind": "implementation_done" },
            )

    clock.sleep = sleep_then_signal

    poker.do_all()

    assert poker._tick_count == 2, \
        f"expected exactly 2 ticks before the clean exit, got {poker._tick_count}"
    assert "(clean)" in poker.answer_conversational, \
        f"expected a clean exit, got: {poker.answer_conversational}"
    assert len( store.read( "dm-clayton", limit=100 ) ) == 2, \
        "poker kept poking after the termination signal"


def test_non_matching_signal_kind_does_not_stop_the_poker( tmp_path ):
    """
    Only the configured `termination_signal_kinds` end the job. A different kind
    on the same topic, posted after start, is ignored — otherwise any traffic on
    a shared coordination topic would silently kill a poker.
    """
    store, gateway = build_gateway( tmp_path )
    recipients = [ RecipientSpec( identifier="Clayton", identifier_type="persona", role="watcher" ) ]
    poker, clock, _notes = build_poker( gateway, recipients, cancel_after=3 )

    original_sleep = clock.sleep

    async def sleep_then_signal( seconds ):
        await original_sleep( seconds )
        if clock.sleeps == 1:
            store.post(
                topic             = "coordination",
                body              = "status update, not a termination",
                sender_session_id = "manager-session",
                metadata          = { "kind": "status_update" },
            )

    clock.sleep = sleep_then_signal

    poker.do_all()

    assert poker._tick_count == 3, \
        f"a non-matching signal kind stopped the poker: {poker._tick_count} tick(s)"
    assert "(cancelled)" in poker.answer_conversational


# ---------------------------------------------------------------------------
# I6-3 — dead-man's switch escalates and KEEPS poking
# ---------------------------------------------------------------------------

def test_poker_dead_mans_switch_escalates_on_silent_recipient( tmp_path ):
    """
    A recipient that never posts is scored silent through the real `who()` /
    `last_post_ts` path. After `deadman_consecutive_pokes` silent ticks the
    escalation fires EXACTLY ONCE, and — the property most worth protecting —
    the poker KEEPS POKING afterwards. The dead-man's switch escalates; it is
    never a loop exit.
    """
    store, gateway = build_gateway( tmp_path )
    recipients = [ RecipientSpec( identifier="Clayton", identifier_type="persona", role="watcher" ) ]
    poker, _clock, notes = build_poker(
        gateway, recipients, cancel_after=6, deadman_consecutive_pokes=2
    )

    poker.do_all()

    assert len( notes ) == 1, f"expected exactly one escalation, got {len( notes )}: {notes}"
    message, priority = notes[ 0 ]
    assert "Clayton" in message,  f"escalation did not name the recipient: {message}"
    assert "watcher" in message,  f"escalation did not carry the recipient role: {message}"
    assert priority == "high",    f"escalation priority was {priority!r}, expected 'high'"
    assert poker._dms_escalations == 1

    # Pin WHEN it fired, not just that it fired once. Without this the threshold
    # could drift by one — firing on the third silent tick instead of the second —
    # and every other assertion here would still pass.
    assert "silent for 2 consecutive pokes" in message, \
        f"escalation fired at the wrong streak length: {message}"

    # Escalation happened at tick 3 (streak reaches 2 there); the job ran 6 ticks.
    # The gap is the proof that escalating did not terminate the loop.
    assert poker._tick_count == 6, \
        f"the poker stopped poking after escalating: {poker._tick_count} tick(s)"
    assert len( store.read( "dm-clayton", limit=100 ) ) == 6, \
        "pokes stopped landing after the dead-man's switch fired"


def test_dead_mans_switch_resets_when_recipient_revives( tmp_path ):
    """
    A recipient that posts after falling silent resets its streak and re-arms the
    switch, so a later silence escalates again rather than staying latched. This
    drives the real `who()` presence scan: the recipient becomes visible only by
    genuinely writing to commons under its own persona name.
    """
    store, gateway = build_gateway( tmp_path )
    recipients = [ RecipientSpec( identifier="Clayton", identifier_type="persona", role="watcher" ) ]
    poker, clock, notes = build_poker(
        gateway, recipients, cancel_after=4, deadman_consecutive_pokes=2
    )

    original_sleep = clock.sleep

    async def sleep_then_revive( seconds ):
        await original_sleep( seconds )
        if clock.sleeps == 3:
            store.post(
                topic             = "presence",
                body              = "still here",
                sender_session_id = "clayton-session",
                persona_name      = "Clayton",
            )

    clock.sleep = sleep_then_revive

    poker.do_all()

    assert len( notes ) == 1, f"expected one escalation before the revival, got {len( notes )}"
    assert poker._silent_streak[ "Clayton" ] == 0, \
        f"a recipient that posted was still scored silent (streak={poker._silent_streak[ 'Clayton' ]})"
    assert poker._dms_fired[ "Clayton" ] is False, \
        "the dead-man's switch stayed latched after the recipient revived"
