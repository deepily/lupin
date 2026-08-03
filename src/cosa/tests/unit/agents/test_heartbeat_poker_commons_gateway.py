#!/usr/bin/env python3
"""
Unit tests — LupinCommonsGateway (heartbeat_poker_commons_gateway.py).

The gateway is pure adapter logic with all I/O injected, so these tests run
with zero disk / network — a FakeStore + a recording http_post callable.

Run: PYTHONPATH=src python -m pytest src/cosa/tests/unit/agents/test_heartbeat_poker_commons_gateway.py -v
"""

from cosa.agents.heartbeat_poker_job             import RecipientSpec
from cosa.agents.heartbeat_poker_commons_gateway import LupinCommonsGateway


# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------

class FakeStore:
    """Stand-in for CommonsStore — records post/read; returns scripted who/read."""

    def __init__( self, who_rows=None, read_entries=None ):
        self.post_calls    = []
        self.read_calls    = []
        self._who_rows     = who_rows if who_rows is not None else []
        self._read_entries = read_entries if read_entries is not None else []

    def post( self, **kwargs ):
        self.post_calls.append( kwargs )
        return { "ok": True }

    def who( self, *args, **kwargs ):
        return self._who_rows

    def read( self, topic, since=None, limit=50 ):
        self.read_calls.append( { "topic": topic, "since": since, "limit": limit } )
        return self._read_entries


class RecordingHttpPost:
    """Stand-in for requests.post — records calls; optionally raises."""

    def __init__( self, raise_exc=None ):
        self.calls  = []
        self._raise = raise_exc

    def __call__( self, url, json=None, headers=None, timeout=None ):
        self.calls.append( { "url": url, "json": json, "headers": headers, "timeout": timeout } )
        if self._raise is not None:
            raise self._raise
        return { "status": 200 }


def _make_gateway( store=None, http_post=None ):
    return LupinCommonsGateway(
        sender_session_id = "hp-sender",
        api_key           = "test-key",
        api_base_url      = "http://localhost:7999",
        store             = store if store is not None else FakeStore(),
        http_post         = http_post if http_post is not None else RecordingHttpPost(),
        persona_name      = "Rio",
        persona_icon      = "⚡",
        persona_color     = "#880E4F",
    )


_WATCHER = RecipientSpec( identifier="tiberius", identifier_type="persona", role="watcher" )


# --------------------------------------------------------------------------
# Constructor + dm_topic_for
# --------------------------------------------------------------------------

def test_constructor_stores_deps():
    gw = _make_gateway()
    assert gw._sender_session_id == "hp-sender"
    assert gw._api_key == "test-key"
    assert gw._api_base_url == "http://localhost:7999"
    assert gw._persona_name == "Rio"


def test_dm_topic_for_simple():
    assert LupinCommonsGateway.dm_topic_for( "tiberius" ) == "dm-tiberius"


def test_dm_topic_for_space_becomes_underscore():
    assert LupinCommonsGateway.dm_topic_for( "mr radio" ) == "dm-mr_radio"


def test_dm_topic_for_trims_and_lowercases():
    assert LupinCommonsGateway.dm_topic_for( "  Tiberius  " ) == "dm-tiberius"


def test_dm_topic_for_accent_stripped():
    # `dm_topic_for` routes through the shared `persona_slug` root (Phase 4),
    # which STRIPS accents — so "maría" → the canonical "dm-maria", byte-identical
    # to the sibling gateways + the MCP DM layer. (Previously this asserted the
    # accent-preserving "dm-maría", a stale expectation left over from the old
    # accent-leaky re.sub(re.UNICODE) seam — the live split-topic bug.)
    assert LupinCommonsGateway.dm_topic_for( "maría" ) == "dm-maria"


# --------------------------------------------------------------------------
# send_to
# --------------------------------------------------------------------------

def test_send_to_posts_to_store():
    store = FakeStore()
    _make_gateway( store=store ).send_to( _WATCHER, "poke-body" )
    assert len( store.post_calls ) == 1
    call = store.post_calls[ 0 ]
    assert call[ "topic" ] == "dm-tiberius"
    assert call[ "body" ] == "poke-body"
    assert call[ "sender_session_id" ] == "hp-sender"
    assert call[ "metadata" ][ "kind" ] == "heartbeat"
    assert call[ "metadata" ][ "recipient_persona" ] == "tiberius"


def test_send_to_fires_dm_send_push():
    # Migrated off the deleted /api/commons/register-question route onto the
    # notification-native /api/dm/send (body INLINE, no commons claim-check).
    http = RecordingHttpPost()
    _make_gateway( http_post=http ).send_to( _WATCHER, "poke-body" )
    assert len( http.calls ) == 1
    call = http.calls[ 0 ]
    assert call[ "url" ].endswith( "/api/dm/send" )
    assert call[ "json" ][ "sender_session_id" ] == "hp-sender"
    assert call[ "json" ][ "recipient_persona" ] == "tiberius"
    assert call[ "json" ][ "body" ] == "poke-body"
    # thread_id carries the qid so board-polling receipts still correlate
    assert "thread_id" in call[ "json" ]
    # the retired register-question fields are GONE
    assert "topic"        not in call[ "json" ]
    assert "expect_reply" not in call[ "json" ]
    assert "ttl_seconds"  not in call[ "json" ]
    assert call[ "headers" ][ "X-API-Key" ] == "test-key"


def test_send_to_swallows_push_failure():
    http  = RecordingHttpPost( raise_exc=RuntimeError( "network down" ) )
    store = FakeStore()
    _make_gateway( store=store, http_post=http ).send_to( _WATCHER, "poke-body" )  # must NOT raise
    assert len( store.post_calls ) == 1          # disk post still happened


def test_send_to_post_and_push_share_question_id():
    # The disk post's metadata.question_id and the dm/send push's thread_id are
    # the SAME qid — board-polling receipts correlate on it.
    store = FakeStore()
    http  = RecordingHttpPost()
    _make_gateway( store=store, http_post=http ).send_to( _WATCHER, "poke-body" )
    assert store.post_calls[ 0 ][ "metadata" ][ "question_id" ] == http.calls[ 0 ][ "json" ][ "thread_id" ]


# --------------------------------------------------------------------------
# last_post_ts
# --------------------------------------------------------------------------

def test_last_post_ts_session_id_match():
    store = FakeStore( who_rows=[
        { "session_id": "other",  "persona_name": "x", "last_post_ts": "2026-05-22T08:00:00" },
        { "session_id": "sess-1", "persona_name": "y", "last_post_ts": "2026-05-22T10:00:00" },
    ] )
    rec = RecipientSpec( identifier="sess-1", identifier_type="session_id", role="watcher" )
    assert _make_gateway( store=store ).last_post_ts( rec ) == "2026-05-22T10:00:00"


def test_last_post_ts_persona_match_case_insensitive():
    store = FakeStore( who_rows=[
        { "session_id": "s", "persona_name": "Tiberius", "last_post_ts": "2026-05-22T11:00:00" },
    ] )
    assert _make_gateway( store=store ).last_post_ts( _WATCHER ) == "2026-05-22T11:00:00"


def test_last_post_ts_no_match_returns_none():
    store = FakeStore( who_rows=[
        { "session_id": "other", "persona_name": None, "last_post_ts": "2026-05-22T09:00:00" },
    ] )
    assert _make_gateway( store=store ).last_post_ts( _WATCHER ) is None


def test_last_post_ts_empty_who_returns_none():
    assert _make_gateway( store=FakeStore( who_rows=[] ) ).last_post_ts( _WATCHER ) is None


# --------------------------------------------------------------------------
# read_since
# --------------------------------------------------------------------------

def test_read_since_delegates_to_store_read():
    entries = [ { "ts": "2026-05-22T12:00:00", "metadata": { "kind": "implementation_done" } } ]
    store   = FakeStore( read_entries=entries )
    result  = _make_gateway( store=store ).read_since( "impl-done", "2026-05-22T00:00:00" )
    assert result == entries
    assert store.read_calls[ 0 ][ "topic" ] == "impl-done"
    assert store.read_calls[ 0 ][ "since" ] == "2026-05-22T00:00:00"
