"""
Unit tests for `CommonsActivityWatcher` (Phase 2.5/3.5 Step 4).

Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC3 — WS
push delivery; AC2 — INI feature flag gate).

Coverage target: tick logic, dispatch shape, cursor advancement, excluded-topic
handling, exception isolation. The daemon-thread lifecycle (`start`/`stop`/
`_run_loop`) is exercised by the existing `CommonsTopicWatcher` base-class
tests and not re-tested here.
"""

import pytest

from cosa.rest.commons_activity_watcher import CommonsActivityWatcher


# ─── Fixtures ───────────────────────────────────────────────────────────────


class _FakeStore:
    """Mock CommonsStore — `_all_topic_names()` + `read()` surface only."""

    def __init__( self, topics_to_entries, raise_for_topics=None ):
        self._topics_to_entries = topics_to_entries
        self._raise_for_topics  = set( raise_for_topics or [ ] )

    def _all_topic_names( self ):
        return sorted( self._topics_to_entries.keys() )

    def read( self, topic, since=None, limit=50 ):
        if topic in self._raise_for_topics:
            raise FileNotFoundError( f"Synthetic: {topic}" )
        entries = self._topics_to_entries.get( topic, [ ] )
        if since is not None:
            entries = [ e for e in entries if e[ "ts" ] > since ]
        return entries[ :limit ]


class _CapturingPush:
    """Mock push_notification_fn — captures all kwargs for assertions."""

    def __init__( self ):
        self.calls         = [ ]
        self._call_counter = 0       # increments on EVERY invocation (incl. failures)
        self.fail_on_call  = None    # call index that should raise

    def __call__( self, **kwargs ):
        idx = self._call_counter
        self._call_counter += 1
        if self.fail_on_call is not None and idx == self.fail_on_call:
            raise RuntimeError( "synthetic push failure" )
        # Take a copy to avoid mutation surprises
        self.calls.append( dict( kwargs ) )


def _entry( ts, sender_sid="sess-x", sender_user_id=None, persona="Maria", body="hello" ):
    md = { }
    if sender_user_id is not None:
        md[ "sender_user_id" ] = sender_user_id
    return {
        "ts"                : ts,
        "sender_session_id" : sender_sid,
        "persona_name"      : persona,
        "persona_icon"      : "🌸",
        "persona_color"     : "#F06292",
        "body"              : body,
        "metadata"          : md,
    }


# ─── _initialize_last_seen_ts ───────────────────────────────────────────────


def test_initialize_last_seen_ts_picks_max_across_topics():
    """Watcher seeds cursor to the max ts across all non-excluded topics."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _entry( "2026-05-14T19:00:00+00:00" ) ],
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00" ) ],
        "presence"   : [ _entry( "2026-05-14T21:00:00+00:00" ) ],   # EXCLUDED
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = _CapturingPush(),
        excluded_topics          = [ "presence", "system-events" ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w._initialize_last_seen_ts()
    # presence is excluded — max should be the 20:00 entry from free-topic
    assert w._last_seen_ts == "2026-05-14T20:00:00+00:00"
    assert w._initialized_last_seen is True


def test_initialize_last_seen_ts_no_topics_leaves_cursor_none():
    """Empty store → cursor stays None so first tick picks up everything."""
    w = CommonsActivityWatcher(
        store                    = _FakeStore( topics_to_entries={ } ),
        push_notification_fn     = _CapturingPush(),
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w._initialize_last_seen_ts()
    assert w._last_seen_ts is None
    assert w._initialized_last_seen is True


# ─── tick() ─────────────────────────────────────────────────────────────────


def test_tick_dispatches_new_entries_newest_first():
    """tick reads since cursor across all topics, sorts newest-first, pushes each."""
    push = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _entry( "2026-05-14T19:00:00+00:00", body="old"     , sender_user_id="alice" ) ],
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00", body="newest"  , sender_user_id="alice" ),
                         _entry( "2026-05-14T19:30:00+00:00", body="middle"  , sender_user_id="alice" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    # No cursor → all entries are "new"
    dispatched = w.tick()
    assert dispatched == 3
    bodies = [ c[ "payload" ][ "body" ] for c in push.calls ]
    assert bodies == [ "newest", "middle", "old" ]


def test_tick_advances_cursor_to_max_ts():
    """After tick, _last_seen_ts == max ts seen."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _entry( "2026-05-14T20:00:00+00:00", sender_user_id="alice" ) ],
        "free-topic" : [ _entry( "2026-05-14T19:00:00+00:00", sender_user_id="alice" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w.tick()
    assert w._last_seen_ts == "2026-05-14T20:00:00+00:00"


def test_tick_excludes_blacklisted_topics():
    """Entries from `presence` + `system-events` never dispatched."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "broadcasts"    : [ _entry( "2026-05-14T20:00:00+00:00", body="broadcasts", sender_user_id="alice" ) ],
        "presence"      : [ _entry( "2026-05-14T20:00:01+00:00", body="presence",   sender_user_id="alice" ) ],
        "system-events" : [ _entry( "2026-05-14T20:00:02+00:00", body="system",     sender_user_id="alice" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ "presence", "system-events" ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 1
    assert push.calls[ 0 ][ "payload" ][ "body" ] == "broadcasts"


def test_tick_dispatch_payload_shape():
    """Dispatched WS payload carries the right keys + topic_kind classification."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00", body="x", sender_user_id="alice" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w.tick()
    call = push.calls[ 0 ]
    assert call[ "type" ]               == "commons_activity"
    assert call[ "suppress_ding" ]      is True
    assert call[ "response_requested" ] is False
    assert call[ "user_id" ]            == "alice"   # resolved from metadata.sender_user_id
    p = call[ "payload" ]
    for k in ( "ts", "topic", "topic_kind", "sender_session_id", "persona_name",
               "persona_icon", "persona_color", "body", "metadata" ):
        assert k in p
    assert p[ "topic" ]      == "free-topic"
    assert p[ "topic_kind" ] == "free-form"


def test_tick_topic_kind_reserved_for_broadcasts():
    """`broadcasts` and `broadcast-acks` get topic_kind=reserved."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [ _entry( "2026-05-14T20:00:00+00:00", sender_user_id="alice" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w.tick()
    assert push.calls[ 0 ][ "payload" ][ "topic_kind" ] == "reserved"


def test_tick_resolves_user_id_via_bridge_when_no_metadata():
    """When entry lacks `metadata.sender_user_id`, fall back to bridge owner lookup."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00", sender_sid="sess-bob" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { "sess-bob": "bob" },
    )
    w.tick()
    assert push.calls[ 0 ][ "user_id" ] == "bob"


def test_tick_omits_user_id_when_unresolvable():
    """No metadata.sender_user_id AND no bridge entry → push without user_id (broadcast)."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00", sender_sid="unknown-sess" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },   # empty map
    )
    w.tick()
    assert "user_id" not in push.calls[ 0 ]


def test_tick_skips_missing_topic_file():
    """FileNotFoundError on one topic's read() is silently skipped."""
    push  = _CapturingPush()
    store = _FakeStore(
        topics_to_entries = {
            "broadcasts"      : [ _entry( "2026-05-14T20:00:00+00:00", sender_user_id="alice" ) ],
            "missing-on-disk" : [ ],
        },
        raise_for_topics = [ "missing-on-disk" ],
    )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 1


def test_tick_continues_after_push_failure():
    """Per-entry push failure is logged but doesn't abort the tick."""
    push = _CapturingPush()
    push.fail_on_call = 0   # first push raises
    store = _FakeStore( topics_to_entries={
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00", body="first",  sender_user_id="alice" ),
                         _entry( "2026-05-14T19:30:00+00:00", body="second", sender_user_id="alice" ) ],
    } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    # First call raised, second succeeded
    assert dispatched == 1
    # We tried to push the first entry but it failed; second entry made it through
    assert len( push.calls ) == 1
    assert push.calls[ 0 ][ "payload" ][ "body" ] == "second"


def test_tick_handles_topic_enumeration_failure_gracefully():
    """If store._all_topic_names() raises, tick returns 0 instead of crashing."""
    class _BrokenStore:
        def _all_topic_names( self ): raise RuntimeError( "synthetic" )
        def read( self, *a, **kw ): return [ ]

    w = CommonsActivityWatcher(
        store                    = _BrokenStore(),
        push_notification_fn     = _CapturingPush(),
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    assert w.tick() == 0


def test_tick_no_new_entries_returns_zero():
    """Empty topics or all entries older than cursor → 0 dispatched."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={ "broadcasts": [ ] } )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w._last_seen_ts = "2026-05-14T20:00:00+00:00"
    assert w.tick() == 0
    assert push.calls == [ ]


def test_tick_handles_bridge_resolver_failure_gracefully():
    """If bridge resolver raises, treat as empty map (no user_id resolution)."""
    push  = _CapturingPush()
    store = _FakeStore( topics_to_entries={
        "free-topic" : [ _entry( "2026-05-14T20:00:00+00:00", sender_sid="sess-x" ) ],
    } )
    def _broken_resolver(): raise RuntimeError( "synthetic resolver fail" )
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = _broken_resolver,
    )
    w.tick()
    # No user_id resolved → push without user_id; dispatch still succeeded
    assert "user_id" not in push.calls[ 0 ]
    assert push.calls[ 0 ][ "payload" ][ "body" ] == "hello"


def test_tick_handles_per_topic_read_failure_gracefully():
    """Non-FileNotFoundError exception from read() is caught and topic skipped."""
    class _PartiallyBrokenStore:
        def __init__( self, ok_topic_entries ):
            self._ok = ok_topic_entries

        def _all_topic_names( self ):
            return [ "broken-topic", "good-topic" ]

        def read( self, topic, since=None, limit=50 ):
            if topic == "broken-topic":
                raise RuntimeError( "synthetic non-FileNotFound" )
            return self._ok

    store = _PartiallyBrokenStore( ok_topic_entries=[
        _entry( "2026-05-14T20:00:00+00:00", body="good", sender_user_id="alice" ),
    ] )
    push  = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 1
    assert push.calls[ 0 ][ "payload" ][ "body" ] == "good"


# ─── Pre-dispatch dedupe (2026-05-16 bug fix) ───────────────────────────────


def _broadcast_entry( ts, broadcast_id, target_session_id, body="hello" ):
    """Helper: per-recipient broadcasts-topic row as written by perform_fanout."""
    return {
        "ts"                : ts,
        "sender_session_id" : "pseudo-sender",
        "persona_name"      : "System Broadcast",
        "persona_icon"      : "📢",
        "persona_color"     : "#FFC107",
        "body"              : body,
        "metadata"          : {
            "broadcast_id"     : broadcast_id,
            "target_session_id": target_session_id,
            "sender_user_id"   : "alice",
        },
    }


def _ack_entry( ts, broadcast_id, sender_sid, status ):
    """Helper: broadcast-acks-topic row as written by the listener's ack path."""
    return {
        "ts"                : ts,
        "sender_session_id" : sender_sid,
        "persona_name"      : "María",
        "persona_icon"      : "🌸",
        "persona_color"     : "#F06292",
        "body"              : "",
        "metadata"          : {
            "broadcast_id" : broadcast_id,
            "status"       : status,
        },
    }


def test_tick_dedupes_broadcasts_by_broadcast_id():
    """
    Regression for 2026-05-16 fan-out bug: a single system broadcast against
    N active sessions caused perform_fanout to write N per-recipient rows to
    the broadcasts topic. The watcher used to dispatch N commons_activity WS
    events → N rows in the Recent Activity panel. After fix: 1 dispatch.
    """
    bid = "broadcast-abc"
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            _broadcast_entry( "2026-05-16T15:00:00+00:00", bid, "sess-aaa", body="hi all" ),
            _broadcast_entry( "2026-05-16T15:00:00+00:00", bid, "sess-bbb", body="hi all" ),
            _broadcast_entry( "2026-05-16T15:00:00+00:00", bid, "sess-ccc", body="hi all" ),
            _broadcast_entry( "2026-05-16T15:00:00+00:00", bid, "sess-ddd", body="hi all" ),
            _broadcast_entry( "2026-05-16T15:00:00+00:00", bid, "sess-eee", body="hi all" ),
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 1, f"Expected 1 dispatched event for the broadcast, got {dispatched}"
    assert len( push.calls ) == 1
    # target_session_id MUST be stripped from the dispatched broadcast representation
    md = push.calls[ 0 ][ "payload" ][ "metadata" ]
    assert "target_session_id" not in md, f"target_session_id leaked through dedupe: {md}"
    assert md[ "broadcast_id" ] == bid


def test_tick_dedupes_broadcasts_keeps_distinct_broadcast_ids():
    """Two distinct broadcasts in the same tick → 2 dispatched (not collapsed)."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            _broadcast_entry( "2026-05-16T15:00:00+00:00", "bid-1", "sess-a" ),
            _broadcast_entry( "2026-05-16T15:00:01+00:00", "bid-2", "sess-a" ),
            _broadcast_entry( "2026-05-16T15:00:00+00:00", "bid-1", "sess-b" ),  # dup of bid-1
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 2, f"Expected 2 dispatched (one per distinct broadcast_id), got {dispatched}"
    bids = { c[ "payload" ][ "metadata" ][ "broadcast_id" ] for c in push.calls }
    assert bids == { "bid-1", "bid-2" }


def test_tick_dedupes_broadcast_acks_by_recipient_triple():
    """
    Regression for the write-side ack multiplicity bug (Arnold's investigation):
    one recipient writes the same ack 3-4× within milliseconds. The HTTP
    broadcast-history path already collapses these (_dedupe_broadcast_acks_by_recipient).
    The WS push path now matches.
    """
    bid = "broadcast-xyz"
    store = _FakeStore( topics_to_entries={
        "broadcast-acks" : [
            _ack_entry( "2026-05-16T15:16:43.852+00:00", bid, "sess-recv", "completed" ),
            _ack_entry( "2026-05-16T15:16:43.852+00:00", bid, "sess-recv", "completed" ),
            _ack_entry( "2026-05-16T15:16:43.854+00:00", bid, "sess-recv", "completed" ),
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 1, f"Expected 1 dispatched (same triple collapsed), got {dispatched}"


def test_tick_keeps_acks_with_distinct_sender_sessions():
    """Multiple recipients each writing one ack → kept distinct (different sender_session_ids)."""
    bid = "broadcast-multi"
    store = _FakeStore( topics_to_entries={
        "broadcast-acks" : [
            _ack_entry( "2026-05-16T15:00:00+00:00", bid, "sess-a", "completed" ),
            _ack_entry( "2026-05-16T15:00:00+00:00", bid, "sess-b", "completed" ),
            _ack_entry( "2026-05-16T15:00:00+00:00", bid, "sess-c", "completed" ),
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 3, f"Distinct senders must not collapse, got {dispatched}"


def test_tick_dedupe_defensive_passthrough_on_malformed_entries():
    """Entries missing required keys must pass through unchanged (no silent disappear)."""
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            # missing metadata.broadcast_id → passthrough
            { "ts": "2026-05-16T15:00:00+00:00", "sender_session_id": "x",
              "persona_name": "p", "persona_icon": "i", "persona_color": "#000", "body": "b",
              "metadata": { } },
        ],
        "broadcast-acks" : [
            # non-string sender_session_id → passthrough
            { "ts": "2026-05-16T15:00:01+00:00", "sender_session_id": 12345,
              "persona_name": "p", "persona_icon": "i", "persona_color": "#000", "body": "",
              "metadata": { "broadcast_id": "bid", "status": "completed" } },
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 2, f"Malformed entries must pass through, got {dispatched}"


def test_tick_dedupe_unaffected_topics_pass_through():
    """Non-broadcasts / non-broadcast-acks topics see no dedupe."""
    store = _FakeStore( topics_to_entries={
        "free-topic" : [
            _entry( "2026-05-16T15:00:00+00:00", body="one"   , sender_user_id="alice" ),
            _entry( "2026-05-16T15:00:01+00:00", body="two"   , sender_user_id="alice" ),
            _entry( "2026-05-16T15:00:02+00:00", body="three" , sender_user_id="alice" ),
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    dispatched = w.tick()
    assert dispatched == 3, f"Free-form topics must not be dedupe-touched, got {dispatched}"


def test_tick_cursor_advances_past_dropped_duplicates():
    """
    Cursor must advance to the max ts of the ORIGINAL entry set, not just the
    dispatched subset — otherwise dropped duplicates would re-surface on the
    next tick and trigger another (now-empty) dispatch loop.
    """
    bid = "broadcast-cursor"
    store = _FakeStore( topics_to_entries={
        "broadcasts" : [
            _broadcast_entry( "2026-05-16T15:00:00+00:00", bid, "sess-a" ),
            _broadcast_entry( "2026-05-16T15:00:01+00:00", bid, "sess-b" ),
            _broadcast_entry( "2026-05-16T15:00:02+00:00", bid, "sess-c" ),
        ],
    } )
    push = _CapturingPush()
    w = CommonsActivityWatcher(
        store                    = store,
        push_notification_fn     = push,
        excluded_topics          = [ ],
        bridge_owner_resolver_fn = lambda: { },
    )
    w.tick()
    # Cursor advanced past ALL three rows even though 2 were dropped as duplicates
    assert w._last_seen_ts == "2026-05-16T15:00:02+00:00", (
        f"Cursor must reach the original max ts; got {w._last_seen_ts}"
    )
    # Second tick must dispatch nothing (no new entries past the cursor)
    push.calls.clear()
    dispatched = w.tick()
    assert dispatched == 0
    assert push.calls == [ ]
