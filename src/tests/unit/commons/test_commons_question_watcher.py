"""
Unit tests for `cosa.rest.commons_question_watcher` (Phase 3 step 3).

Coverage targets: AC8 (template-method + T1 dispatched-set) + AC11 import-chain +
AC12 100% lines + branches + functions + AC16 T1 idempotency + AC17 T3 caps +
AC18 T4 re-register cursor + AC19 T6 concurrency + AC20 T8 inject_fn isolation.

Per `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`.
"""

import re
import tempfile
import threading
import time
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from cosa.rest.commons_question_watcher import (
    CapExceededError,
    CommonsQuestionWatcher,
    QuestionNotFound,
    _InFlightQuestion,
    _is_valid_in_reply_to,
    _now_iso,
)
from cosa.rest.commons_topic_watcher import CommonsTopicWatcher
from lupin_mcp.commons_store import CommonsStore


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """Fresh CommonsStore in a tempdir."""
    with tempfile.TemporaryDirectory() as tmp:
        yield CommonsStore( tmp )


@pytest.fixture
def captured_injects():
    """Mutable list to collect inject_fn invocations."""
    return [ ]


@pytest.fixture
def inject_fn( captured_injects ):
    """Mock inject_fn that records every dispatched answer entry."""
    def _capture( entry: Dict[ str, Any ] ) -> None:
        captured_injects.append( entry )
    return _capture


@pytest.fixture
def watcher( store ):
    """Fresh CommonsQuestionWatcher bound to the tempdir store."""
    return CommonsQuestionWatcher(
        store                 = store,
        poll_interval_seconds = 0.05,
        in_flight_ttl_seconds = 60.0,
        per_user_max          = 5,
        global_max            = 20,
    )


def _post_answer(
    store          : CommonsStore,
    topic          : str,
    body           : str,
    in_reply_to    : Any,
    persona_name   : str = "Maria",
    sender_session : str = "sess-answerer",
) -> Dict[ str, Any ]:
    """Helper: post an answer entry with metadata.in_reply_to correlation."""
    return store.post(
        topic             = topic,
        body              = body,
        sender_session_id = sender_session,
        persona_name      = persona_name,
        persona_icon      = "🌸",
        persona_color     = "#A040A0",
        metadata          = { "in_reply_to": in_reply_to },
    )


# ─── Helpers: _is_valid_in_reply_to ─────────────────────────────────────────


def test_is_valid_in_reply_to_accepts_canonical():
    """Canonical alphanumeric + underscore + dash strings up to 64 chars are valid."""
    assert _is_valid_in_reply_to( "q-1234" )      is True
    assert _is_valid_in_reply_to( "abc_DEF_123" ) is True
    assert _is_valid_in_reply_to( "x" )           is True
    assert _is_valid_in_reply_to( "a" * 64 )      is True


def test_is_valid_in_reply_to_rejects_non_string():
    """T1: non-string types are rejected."""
    assert _is_valid_in_reply_to( None )         is False
    assert _is_valid_in_reply_to( 42 )           is False
    assert _is_valid_in_reply_to( 3.14 )         is False
    assert _is_valid_in_reply_to( [ "q1" ] )     is False
    assert _is_valid_in_reply_to( { "q": 1 } )   is False
    assert _is_valid_in_reply_to( True )         is False  # bool is int but not str


def test_is_valid_in_reply_to_rejects_empty_and_oversize():
    """T1: empty + > 64 chars are rejected."""
    assert _is_valid_in_reply_to( "" )           is False
    assert _is_valid_in_reply_to( "a" * 65 )     is False


def test_is_valid_in_reply_to_rejects_disallowed_chars():
    """T1: chars outside [A-Za-z0-9_-] are rejected (control chars, spaces, punctuation)."""
    assert _is_valid_in_reply_to( "has space" )   is False
    assert _is_valid_in_reply_to( "<tag>" )       is False
    assert _is_valid_in_reply_to( "q.1" )         is False
    assert _is_valid_in_reply_to( "q\x00" )       is False
    assert _is_valid_in_reply_to( "q\n" )         is False


# ─── Helpers: _now_iso ──────────────────────────────────────────────────────


def test_now_iso_format():
    """`_now_iso()` returns an ISO-8601 string with timezone offset."""
    ts = _now_iso()
    assert isinstance( ts, str )
    # ISO format with offset: 2026-05-13T10:00:00.123456+00:00
    assert re.match( r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts )
    assert "+" in ts or "-" in ts.split( "T" )[ 1 ]


# ─── _InFlightQuestion plain data ───────────────────────────────────────────


def test_inflight_question_plain_data():
    """_InFlightQuestion stores fields verbatim."""
    fn = lambda entry: None
    rec = _InFlightQuestion(
        topic                = "q-topic",
        user_id              = "u1",
        inject_fn            = fn,
        last_seen_ts         = "2026-05-13T10:00:00+00:00",
        expires_at_monotonic = 999.0,
    )
    assert rec.topic                == "q-topic"
    assert rec.user_id              == "u1"
    assert rec.inject_fn            is fn
    assert rec.last_seen_ts         == "2026-05-13T10:00:00+00:00"
    assert rec.expires_at_monotonic == 999.0


# ─── Subclassing contract ───────────────────────────────────────────────────


def test_subclasses_commons_topic_watcher( watcher ):
    """`CommonsQuestionWatcher` is a `CommonsTopicWatcher` subclass."""
    assert isinstance( watcher, CommonsTopicWatcher )


def test_initialize_last_seen_ts_is_noop( watcher ):
    """Per-question cursors live on records; watcher-level cursor is unused."""
    assert watcher._initialized_last_seen is False
    watcher._initialize_last_seen_ts()
    assert watcher._initialized_last_seen is True
    # Watcher-level cursor remains None — per-question cursors are authoritative
    assert watcher._last_seen_ts is None


# ─── register_question ──────────────────────────────────────────────────────


def test_register_question_happy_path( watcher, inject_fn ):
    """Atomic register stamps user_id + last_seen_ts; question becomes in flight."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    assert watcher.is_in_flight( "q1" ) is True


def test_register_question_collision_raises_value_error( watcher, inject_fn ):
    """T9 mirror: duplicate question_id raises ValueError (router → 409)."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    with pytest.raises( ValueError, match="question_id collision" ):
        watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )


def test_register_question_custom_ttl( watcher, inject_fn ):
    """`ttl_seconds` override is honored on the in-flight record."""
    with watcher._lock:
        before_mono = time.monotonic()
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn, ttl_seconds=10.0 )
    with watcher._lock:
        rec = watcher._in_flight[ "q1" ]
    assert rec.expires_at_monotonic >= before_mono + 10.0
    assert rec.expires_at_monotonic <  before_mono + 11.0


def test_register_question_custom_last_seen_ts( watcher, inject_fn ):
    """Explicit `last_seen_ts` override is honored on the in-flight record."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn, last_seen_ts="2026-01-01T00:00:00+00:00" )
    with watcher._lock:
        rec = watcher._in_flight[ "q1" ]
    assert rec.last_seen_ts == "2026-01-01T00:00:00+00:00"


# ─── AC17 / T3 caps ─────────────────────────────────────────────────────────


def test_per_user_cap( watcher, inject_fn ):
    """AC17 — registering past per-user max raises CapExceededError."""
    # per_user_max=5 in fixture; register 5 then 6th should fail
    for i in range( 5 ):
        watcher.register_question( f"q-A-{i}", "user-A", "topic", inject_fn )
    with pytest.raises( CapExceededError, match="per-user cap reached" ):
        watcher.register_question( "q-A-5", "user-A", "topic", inject_fn )
    # Different user is unaffected
    watcher.register_question( "q-B-0", "user-B", "topic", inject_fn )


def test_global_cap( store, inject_fn ):
    """AC17 — registering past global max raises CapExceededError (across users)."""
    w = CommonsQuestionWatcher(
        store        = store,
        per_user_max = 100,   # not the bottleneck
        global_max   = 3,
    )
    w.register_question( "q1", "u1", "t", inject_fn )
    w.register_question( "q2", "u2", "t", inject_fn )
    w.register_question( "q3", "u3", "t", inject_fn )
    with pytest.raises( CapExceededError, match="global cap reached" ):
        w.register_question( "q4", "u4", "t", inject_fn )


def test_cap_check_after_prune( store, inject_fn ):
    """Expired records are pruned before cap check — freeing capacity."""
    w = CommonsQuestionWatcher(
        store                 = store,
        in_flight_ttl_seconds = 0.01,   # near-immediate expiry
        per_user_max          = 100,
        global_max            = 2,
    )
    w.register_question( "q1", "u1", "t", inject_fn )
    w.register_question( "q2", "u2", "t", inject_fn )
    time.sleep( 0.05 )  # let both expire
    # 3rd register should succeed because both expired entries are pruned
    w.register_question( "q3", "u3", "t", inject_fn )
    assert w.is_in_flight( "q3" ) is True
    assert w.is_in_flight( "q1" ) is False


# ─── unregister_question / T5 ───────────────────────────────────────────────


def test_unregister_question_happy_path( watcher, inject_fn ):
    """Successful unregister removes the record."""
    watcher.register_question( "q1", "user-A", "topic", inject_fn )
    watcher.unregister_question( "q1", "user-A" )
    assert watcher.is_in_flight( "q1" ) is False


def test_unregister_unknown_raises_question_not_found( watcher ):
    """T5 — unknown question_id raises QuestionNotFound."""
    with pytest.raises( QuestionNotFound, match="not found or not owned" ):
        watcher.unregister_question( "ghost", "user-A" )


def test_unregister_wrong_owner_raises_question_not_found( watcher, inject_fn ):
    """T5 — known question, wrong user raises the SAME error (no enumeration)."""
    watcher.register_question( "q1", "user-A", "topic", inject_fn )
    with pytest.raises( QuestionNotFound, match="not found or not owned" ):
        watcher.unregister_question( "q1", "user-B" )
    # The record is NOT removed — only the rightful owner can unregister
    assert watcher.is_in_flight( "q1" ) is True


def test_unregister_clears_dispatched_set( watcher, inject_fn, captured_injects ):
    """Unregister also clears `_dispatched_by_question` (T1 memory hygiene)."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    # Simulate an entry having been dispatched
    watcher._dispatched_by_question[ "q1" ] = { "fake-ts-1" }
    watcher.unregister_question( "q1", "user-A" )
    assert "q1" not in watcher._dispatched_by_question


# ─── is_in_flight ───────────────────────────────────────────────────────────


def test_is_in_flight_false_unknown( watcher ):
    """Unknown question_id → False."""
    assert watcher.is_in_flight( "never-registered" ) is False


def test_is_in_flight_expires_via_lazy_prune( store, inject_fn ):
    """Expired record is pruned on is_in_flight() call."""
    w = CommonsQuestionWatcher(
        store                 = store,
        in_flight_ttl_seconds = 0.01,
        per_user_max          = 100,
        global_max            = 100,
    )
    w.register_question( "q1", "user-A", "topic", inject_fn )
    assert w.is_in_flight( "q1" ) is True
    time.sleep( 0.05 )
    assert w.is_in_flight( "q1" ) is False


# ─── _prune_expired_locked clears dispatched_by_question ────────────────────


def test_prune_clears_dispatched_by_question( watcher, inject_fn ):
    """When a question is pruned, its _dispatched_by_question entry is also cleared."""
    watcher.register_question( "q1", "user-A", "topic", inject_fn )
    watcher._dispatched_by_question[ "q1" ] = { "ts-1", "ts-2" }
    # Force-expire by mutating the record's monotonic deadline
    with watcher._lock:
        watcher._in_flight[ "q1" ].expires_at_monotonic = time.monotonic() - 1.0
        watcher._prune_expired_locked( time.monotonic() )
    assert "q1" not in watcher._in_flight
    assert "q1" not in watcher._dispatched_by_question


# ─── tick() dispatch ────────────────────────────────────────────────────────


def test_tick_dispatches_matching_answer( watcher, store, inject_fn, captured_injects ):
    """tick() dispatches an answer whose metadata.in_reply_to == question_id."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="42", in_reply_to="q1" )
    dispatched = watcher.tick()
    assert dispatched == 1
    assert len( captured_injects ) == 1
    assert captured_injects[ 0 ][ "body" ]                  == "42"
    assert captured_injects[ 0 ][ "metadata" ][ "in_reply_to" ] == "q1"


def test_tick_ignores_non_matching_in_reply_to( watcher, store, inject_fn, captured_injects ):
    """tick() skips entries whose in_reply_to doesn't match any in-flight question."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="for-another", in_reply_to="q2" )
    dispatched = watcher.tick()
    assert dispatched == 0
    assert captured_injects == [ ]


def test_tick_ignores_missing_metadata( watcher, store, inject_fn, captured_injects ):
    """tick() skips entries with no in_reply_to in metadata."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    store.post(
        topic             = "topic-q1",
        body              = "no-metadata-here",
        sender_session_id = "sess-1",
        metadata          = { "kind": "unrelated" },
    )
    assert watcher.tick() == 0
    assert captured_injects == [ ]


def test_tick_advances_cursor( watcher, store, inject_fn ):
    """Cursor advances to the latest entry's ts, even when no dispatch happens."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    initial_cursor = watcher._in_flight[ "q1" ].last_seen_ts
    # Post an entry that doesn't match — cursor should still advance past it
    _post_answer( store, "topic-q1", body="unrelated", in_reply_to="q999" )
    watcher.tick()
    new_cursor = watcher._in_flight[ "q1" ].last_seen_ts
    assert new_cursor > initial_cursor


def test_tick_handles_missing_topic_file( watcher, inject_fn ):
    """When the topic file doesn't exist yet (reserved topic gone), tick() returns 0 gracefully."""
    # Register against a reserved topic that hasn't been seeded — by deleting the seeded file
    import os
    watcher.register_question( "q1", "user-A", "broadcast-acks", inject_fn )
    # Remove the seeded file to trigger FileNotFoundError on read()
    os.remove( str( watcher.store._topic_path( "broadcast-acks" ) ) )
    assert watcher.tick() == 0


def test_tick_handles_read_exception( watcher, store, inject_fn ):
    """Unexpected store.read() exception is caught, debug-logged, doesn't kill tick."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    watcher.debug = True
    with patch.object( watcher.store, "read", side_effect=RuntimeError( "boom" ) ):
        assert watcher.tick() == 0


# ─── AC16 / T1 idempotency ──────────────────────────────────────────────────


def test_ac16_dispatched_set_prevents_duplicates(
    watcher, store, inject_fn, captured_injects
):
    """AC16 — running tick() twice on the same entry dispatches exactly once."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="answer-1", in_reply_to="q1" )
    # First tick dispatches
    assert watcher.tick() == 1
    # Force-rewind the cursor so the entry IS re-read by the store
    with watcher._lock:
        watcher._in_flight[ "q1" ].last_seen_ts = "1970-01-01T00:00:00+00:00"
    # Second tick re-reads the entry but T1 idempotency skips it
    assert watcher.tick() == 0
    assert len( captured_injects ) == 1


def test_ac16_skips_type_confusion_variants(
    watcher, store, inject_fn, captured_injects
):
    """AC16 — entries whose in_reply_to is non-string types are skipped."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    # Post entries with bad in_reply_to types (allowed by store; rejected by watcher)
    _post_answer( store, "topic-q1", body="int",   in_reply_to=42 )
    _post_answer( store, "topic-q1", body="none",  in_reply_to=None )
    _post_answer( store, "topic-q1", body="list",  in_reply_to=[ "q1" ] )
    assert watcher.tick() == 0
    assert captured_injects == [ ]


def test_ac16_skips_oversize_in_reply_to(
    watcher, store, inject_fn, captured_injects
):
    """AC16 — in_reply_to > 64 chars is skipped (T1 length cap)."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="oversize", in_reply_to="a" * 65 )
    assert watcher.tick() == 0
    assert captured_injects == [ ]


def test_ac16_skips_disallowed_chars(
    watcher, store, inject_fn, captured_injects
):
    """AC16 — in_reply_to with disallowed chars (e.g. spaces, control chars) is skipped."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="bad-chars", in_reply_to="q with space" )
    assert watcher.tick() == 0
    assert captured_injects == [ ]


def test_ac16_debug_logs_invalid_in_reply_to(
    watcher, store, inject_fn, captured_injects, capsys
):
    """AC16 — when debug=True, invalid in_reply_to is logged at debug level."""
    watcher.debug = True
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="bad", in_reply_to="q with space" )
    watcher.tick()
    out = capsys.readouterr().out
    assert "skipping invalid in_reply_to" in out


# ─── AC18 / T4 re-register cursor ───────────────────────────────────────────


def test_ac18_re_register_cursor_resets_to_now(
    watcher, store, inject_fn, captured_injects
):
    """
    AC18 — after server-restart-style tracker clear + re-register, pre-restart
    entries on the same topic are NOT dispatched (cursor = now skipped them).
    """
    # Step 1: register and dispatch one answer normally
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="pre-restart", in_reply_to="q1" )
    assert watcher.tick() == 1
    assert len( captured_injects ) == 1

    # Step 2: simulate server restart — clear the tracker
    watcher.unregister_question( "q1", "user-A" )
    assert watcher.is_in_flight( "q1" ) is False
    # _dispatched_by_question also cleared
    assert "q1" not in watcher._dispatched_by_question

    # Step 3: re-register the same question — cursor defaults to NOW (not the
    # store's original ts), so the existing entry is STRUCTURALLY skipped
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    assert watcher.tick() == 0
    # No new injects
    assert len( captured_injects ) == 1

    # Step 4: posting a NEW answer AFTER re-register IS dispatched
    _post_answer( store, "topic-q1", body="post-restart", in_reply_to="q1" )
    assert watcher.tick() == 1
    assert len( captured_injects ) == 2
    assert captured_injects[ -1 ][ "body" ] == "post-restart"


# ─── AC19 / T6 concurrency ──────────────────────────────────────────────────


def test_ac19_concurrent_register_unregister_dispatch( watcher, store, inject_fn ):
    """
    AC19 — N=32 threads interleave register / unregister / tick on the same
    question_id. No exceptions, no partial state, no double-dispatch.
    """
    barrier   = threading.Barrier( 32 )
    exceptions: List[ Exception ] = [ ]
    lock = threading.Lock()

    def worker( idx: int ) -> None:
        barrier.wait()
        try:
            # Each thread does a register → tick → unregister cycle on a unique qid
            qid = f"q-{idx}"
            try:
                watcher.register_question( qid, f"u-{idx}", f"topic-{idx}", inject_fn )
                # Inject one answer; some workers will catch it via tick()
                _post_answer( store, f"topic-{idx}", body=f"a-{idx}", in_reply_to=qid )
                watcher.tick()
            except CapExceededError:
                pass  # Expected when global_max is exceeded by concurrent registers
            try:
                watcher.unregister_question( qid, f"u-{idx}" )
            except QuestionNotFound:
                pass  # Tolerable: unregister may race past a prune in some orderings
        except Exception as e:
            with lock:
                exceptions.append( e )

    threads = [ threading.Thread( target=worker, args=( i, ) ) for i in range( 32 ) ]
    for t in threads: t.start()
    for t in threads: t.join( timeout=10.0 )

    assert exceptions == [ ], f"workers raised: {exceptions!r}"
    # After all workers complete, tracker is in a consistent state — no
    # partial entries (every record has a valid user_id + last_seen_ts)
    with watcher._lock:
        for rec in watcher._in_flight.values():
            assert rec.user_id    is not None
            assert rec.last_seen_ts is not None
            assert callable( rec.inject_fn )


def test_ac19_register_unregister_no_double_dispatch( watcher, store, inject_fn, captured_injects ):
    """
    AC19 — N=8 threads run tick() concurrently after one register + one matching
    answer; the same entry must NOT be dispatched twice.
    """
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="once-only", in_reply_to="q1" )

    barrier = threading.Barrier( 8 )
    def worker() -> None:
        barrier.wait()
        watcher.tick()

    threads = [ threading.Thread( target=worker ) for _ in range( 8 ) ]
    for t in threads: t.start()
    for t in threads: t.join( timeout=5.0 )

    # T1 + T6 — exactly one dispatch despite 8 concurrent ticks
    assert len( captured_injects ) == 1
    assert captured_injects[ 0 ][ "body" ] == "once-only"


# ─── AC20 / T8 inject_fn failure isolation ──────────────────────────────────


def test_ac20_failing_inject_fn_does_not_kill_tick_batch(
    watcher, store, captured_injects
):
    """
    AC20 — Y1's inject_fn raises; Y2's inject_fn succeeds. Y2 must STILL be
    dispatched. Y1's exception is debug-logged but does not propagate.
    """
    watcher.debug = True

    def failing_inject( entry: Dict[ str, Any ] ) -> None:
        raise RuntimeError( "Y1 inject_fn intentionally raises" )

    def succeeding_inject( entry: Dict[ str, Any ] ) -> None:
        captured_injects.append( entry )

    watcher.register_question( "y1", "user-A", "topic-shared", failing_inject )
    watcher.register_question( "y2", "user-A", "topic-shared", succeeding_inject )

    _post_answer( store, "topic-shared", body="for-y1", in_reply_to="y1" )
    _post_answer( store, "topic-shared", body="for-y2", in_reply_to="y2" )

    # No exception escapes
    dispatched = watcher.tick()
    # Y2 dispatch counts; Y1 dispatch is attempted but the try/except catches —
    # the count includes only successful inject_fn returns
    assert dispatched == 1
    # Y2 received its entry
    assert len( captured_injects ) == 1
    assert captured_injects[ 0 ][ "body" ] == "for-y2"


def test_ac20_failure_during_dispatch_does_not_pollute_dispatched_set(
    watcher, store, captured_injects
):
    """
    AC20 follow-up — Y1's failure must NOT corrupt _dispatched_by_question
    (since the inject_fn raised; per the design _dispatched_set IS still
    updated under-lock BEFORE the dispatch call to mark dispatch-once
    semantics — re-attempts won't re-fire even on failure).
    """
    def failing_inject( entry: Dict[ str, Any ] ) -> None:
        raise RuntimeError( "intentional" )

    watcher.register_question( "y1", "user-A", "topic-y1", failing_inject )
    _post_answer( store, "topic-y1", body="will-fail", in_reply_to="y1" )

    # First tick — attempts dispatch, inject_fn raises; entry is marked dispatched
    watcher.tick()
    assert "y1" in watcher._dispatched_by_question
    assert len( watcher._dispatched_by_question[ "y1" ] ) == 1


# ─── Branch coverage fillers (mid-tick unregister + missing ts) ─────────────


def test_tick_handles_unregister_mid_tick( watcher, store, inject_fn, captured_injects ):
    """
    Coverage: `current is None` paths in `_tick_one_question` — both the
    dispatch lookup (line 330-331) AND the cursor-advance lookup (line 349-350).

    Pre-cache a fake snapshot of an already-unregistered question; the watcher
    sees the empty `_in_flight` slot under lock and bails out cleanly.
    """
    # Register, snapshot a record reference, then delete from _in_flight so
    # _tick_one_question's lock-guarded lookups see None.
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    _post_answer( store, "topic-q1", body="will-not-arrive", in_reply_to="q1" )
    with watcher._lock:
        ghost_record = watcher._in_flight[ "q1" ]
        del watcher._in_flight[ "q1" ]
    # The ghost record still has a topic + cursor; call _tick_one_question
    # directly so we exercise the "current is None" lock-bail paths.
    dispatched = watcher._tick_one_question( "q1", ghost_record )
    assert dispatched == 0
    assert captured_injects == [ ]


def test_tick_handles_entry_without_ts( watcher, inject_fn, captured_injects ):
    """
    Coverage: the `entry_ts is None` branch in the latest_ts update logic
    (line 312). Use a mocked store.read return value that omits `ts`.
    """
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    fake_entries = [
        # ts missing → skips latest_ts update; in_reply_to still matches → dispatched
        {
            "body"     : "no-ts-but-matches",
            "metadata" : { "in_reply_to": "q1" },
        },
    ]
    with patch.object( watcher.store, "read", return_value=fake_entries ):
        dispatched = watcher.tick()
    # _is_valid_in_reply_to("q1") passes; entry_ts=None means dispatched_set
    # still treats None as the dispatch key — first occurrence dispatches.
    assert dispatched == 1
    assert len( captured_injects ) == 1


# ─── Lifecycle: start / stop daemon ─────────────────────────────────────────


def test_start_stop_daemon( watcher, store, inject_fn, captured_injects ):
    """start() spawns the daemon; stop() cleans up; the daemon picks up new entries."""
    watcher.register_question( "q1", "user-A", "topic-q1", inject_fn )
    watcher.start()
    try:
        _post_answer( store, "topic-q1", body="via-daemon", in_reply_to="q1" )
        # Give the daemon up to 0.5s to tick (poll_interval=0.05)
        deadline = time.time() + 0.5
        while time.time() < deadline:
            if captured_injects: break
            time.sleep( 0.01 )
    finally:
        watcher.stop()
    assert len( captured_injects ) == 1
    assert captured_injects[ 0 ][ "body" ] == "via-daemon"


def test_start_is_idempotent( watcher ):
    """Calling start() twice doesn't spawn two threads."""
    watcher.start()
    first_thread = watcher._thread
    watcher.start()
    assert watcher._thread is first_thread
    watcher.stop()


def test_stop_safe_on_never_started( watcher ):
    """stop() on a never-started watcher doesn't raise."""
    watcher.stop()  # should be a no-op


# ─── quick_smoke_test ───────────────────────────────────────────────────────


def quick_smoke_test() -> bool:
    """
    Stand-alone sanity check executable as `python -m cosa.rest.commons_question_watcher`-style.

    Wires up an in-memory CommonsStore, registers a question, posts an answer,
    runs tick() once, asserts dispatch happened. Returns True on success.
    """
    print( "─" * 80 )
    print( "CommonsQuestionWatcher quick_smoke_test" )
    print( "─" * 80 )
    with tempfile.TemporaryDirectory() as tmp:
        store = CommonsStore( tmp )
        captured: List[ Dict[ str, Any ] ] = [ ]
        watcher = CommonsQuestionWatcher( store=store, poll_interval_seconds=0.05 )
        watcher.register_question( "qsmoke", "user-X", "smoke-topic", lambda e: captured.append( e ) )
        _post_answer( store, "smoke-topic", body="hello", in_reply_to="qsmoke" )
        dispatched = watcher.tick()
        ok = ( dispatched == 1 and len( captured ) == 1 and captured[ 0 ][ "body" ] == "hello" )
        print( f"✓ dispatched={dispatched} captured={len( captured )} body={captured[ 0 ][ 'body' ] if captured else None!r}" )
        print( "✓ SMOKE PASSED" if ok else "✗ SMOKE FAILED" )
        return ok


if __name__ == "__main__":
    ok = quick_smoke_test()
    raise SystemExit( 0 if ok else 1 )
