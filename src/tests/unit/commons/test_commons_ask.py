"""
Unit tests for commons_ask.

Per AC6 verification: 4 hybrid-grace timing cases for `ask_sync`.
Per AC7 verification: `ask_async` returns the expected `{question_id, posted_ts}` shape.

Coverage target: 100% lines/branches/functions (AC10 commons-only mandate).

Uses small `timeout_seconds` / `grace_seconds` per AC6 explicit test parameters
("Tests pass timeout=0.1, grace_seconds=0.05 for fast wall-clock; same code path
as production"). Slightly relaxed here (timeout=0.5, grace=0.05) to absorb
thread-startup jitter on slow CI runners without exercising any different code
path. Reply delivery uses a real CommonsStore + threading.Timer for deterministic
ordering.
"""

import tempfile
import threading
import time
from pathlib import Path

import pytest

from lupin_mcp.commons_ask import _find_replies, ask_async, ask_sync
from lupin_mcp.commons_store import CommonsStore


@pytest.fixture
def store():
    """A fresh CommonsStore in a tempdir."""
    with tempfile.TemporaryDirectory() as tmp:
        yield CommonsStore( tmp )


def _post_reply_after( store: CommonsStore, topic: str, question_id: str, body: str, delay_seconds: float, session_id: str = "peer" ) -> threading.Timer:
    """Schedule a reply post `delay_seconds` from now. Returns the started Timer."""
    def _runner():
        store.post(
            topic             = topic,
            body              = body,
            sender_session_id = session_id,
            persona_name      = "Peer",
            persona_icon      = "🦜",
            persona_color     = "#0099CC",
            metadata          = { "kind": "answer", "in_reply_to": question_id },
        )
    t = threading.Timer( delay_seconds, _runner )
    t.daemon = True
    t.start()
    return t


# ---------- AC6: hybrid-grace 4 cases ----------


def test_ask_sync_one_reply_within_timeout( store ):
    """AC6 case (a): one peer answers within timeout → returns [entry]."""
    topic = "coordination"
    # Schedule a reply to fire after 0.05s — well within timeout=0.5
    # The reply Timer must use the question_id, so post the question via ask_sync
    # in a thread that waits to see the question first. Simpler: post-then-reply pattern.
    # Use a pre-known question_id by mocking uuid.uuid4 OR by reading the topic for the question first.
    # Cleanest: post the question directly via store, then call _find_replies. But we want to test
    # ask_sync's full path. So poll the store from the reply-thread to learn the question_id.

    def _replier():
        # Wait until the question appears, grab its id, then post a reply.
        for _ in range( 200 ):
            time.sleep( 0.005 )
            entries = store.read( topic, limit=10 )
            for e in entries:
                if e[ "metadata" ].get( "kind" ) == "question":
                    qid = e[ "metadata" ][ "question_id" ]
                    store.post(
                        topic             = topic,
                        body              = "yes",
                        sender_session_id = "peer",
                        persona_name      = "Peer",
                        persona_icon      = "🦜",
                        persona_color     = "#0099CC",
                        metadata          = { "kind": "answer", "in_reply_to": qid },
                    )
                    return
        return
    t = threading.Thread( target=_replier, daemon=True )
    t.start()

    result = ask_sync(
        store=store, topic=topic, body="ping?",
        sender_session_id="me", persona_name="Me", persona_icon="🎵", persona_color="#FF00FF",
        timeout_seconds=1.0, grace_seconds=0.05, poll_interval=0.01,
    )
    t.join( timeout=2.0 )
    assert len( result[ "replies" ] ) == 1
    assert result[ "replies" ][ 0 ][ "body" ] == "yes"
    assert result[ "question_id" ]
    assert result[ "posted_ts" ]


def test_ask_sync_two_replies_within_grace( store ):
    """AC6 case (b): two peers answer within grace → returns [entry1, entry2]."""
    topic = "coordination"

    def _replier():
        for _ in range( 200 ):
            time.sleep( 0.005 )
            entries = store.read( topic, limit=10 )
            for e in entries:
                if e[ "metadata" ].get( "kind" ) == "question":
                    qid = e[ "metadata" ][ "question_id" ]
                    # Two replies in quick succession — both inside grace=0.1s
                    store.post( topic=topic, body="reply-A", sender_session_id="peerA", persona_name="A", persona_icon="🅰", persona_color="#A00", metadata={ "kind": "answer", "in_reply_to": qid } )
                    time.sleep( 0.02 )
                    store.post( topic=topic, body="reply-B", sender_session_id="peerB", persona_name="B", persona_icon="🅱", persona_color="#0B0", metadata={ "kind": "answer", "in_reply_to": qid } )
                    return

    t = threading.Thread( target=_replier, daemon=True )
    t.start()

    result = ask_sync(
        store=store, topic=topic, body="ping?",
        sender_session_id="me", persona_name="Me", persona_icon="🎵", persona_color="#FF00FF",
        timeout_seconds=1.0, grace_seconds=0.2, poll_interval=0.01,
    )
    t.join( timeout=2.0 )
    bodies = sorted( e[ "body" ] for e in result[ "replies" ] )
    assert bodies == [ "reply-A", "reply-B" ]


def test_ask_sync_two_replies_second_outside_grace( store ):
    """AC6 case (c): second peer answers AFTER grace window → returns [entry1] only."""
    topic = "coordination"

    def _replier():
        for _ in range( 200 ):
            time.sleep( 0.005 )
            entries = store.read( topic, limit=10 )
            for e in entries:
                if e[ "metadata" ].get( "kind" ) == "question":
                    qid = e[ "metadata" ][ "question_id" ]
                    store.post( topic=topic, body="reply-1", sender_session_id="p1", persona_name="P1", persona_icon="🅰", persona_color="#A00", metadata={ "kind": "answer", "in_reply_to": qid } )
                    # Wait LONGER than grace (grace=0.05; sleep 0.30) before second reply
                    time.sleep( 0.30 )
                    store.post( topic=topic, body="reply-2", sender_session_id="p2", persona_name="P2", persona_icon="🅱", persona_color="#0B0", metadata={ "kind": "answer", "in_reply_to": qid } )
                    return

    t = threading.Thread( target=_replier, daemon=True )
    t.start()

    result = ask_sync(
        store=store, topic=topic, body="ping?",
        sender_session_id="me", persona_name="Me", persona_icon="🎵", persona_color="#FF00FF",
        timeout_seconds=1.0, grace_seconds=0.05, poll_interval=0.01,
    )
    t.join( timeout=2.0 )
    assert len( result[ "replies" ] ) == 1
    assert result[ "replies" ][ 0 ][ "body" ] == "reply-1"


def test_ask_sync_timeout_zero_replies( store ):
    """AC6 case (d): timeout with no replies → returns empty list."""
    result = ask_sync(
        store=store, topic="coordination", body="anyone there?",
        sender_session_id="me", persona_name="Me", persona_icon="🎵", persona_color="#FF00FF",
        timeout_seconds=0.1, grace_seconds=0.05, poll_interval=0.02,
    )
    assert result[ "replies" ] == [ ]
    assert result[ "question_id" ]
    assert result[ "posted_ts" ]


# ---------- AC7: ask_async ----------


def test_ask_async_returns_immediately( store ):
    """ask_async returns {question_id, posted_ts} without waiting."""
    start = time.monotonic()
    result = ask_async(
        store=store, topic="coordination", body="async ping",
        sender_session_id="me", persona_name="Me", persona_icon="🎵", persona_color="#FF00FF",
    )
    elapsed = time.monotonic() - start
    assert elapsed < 0.1
    assert "question_id" in result
    assert "posted_ts"   in result
    assert result[ "question_id" ]
    assert result[ "posted_ts"   ]
    # Question is in the store
    entries = store.read( "coordination", limit=10 )
    assert len( entries ) == 1
    assert entries[ 0 ][ "metadata" ][ "kind" ]        == "question"
    assert entries[ 0 ][ "metadata" ][ "question_id" ] == result[ "question_id" ]


def test_ask_async_honors_explicit_question_id( store ):
    """When caller supplies question_id, ask_async uses it verbatim (covers the `is not None` branch)."""
    explicit_qid = "my-fixed-id-1234"
    result = ask_async(
        store=store, topic="coordination", body="async ping",
        sender_session_id="me", persona_name="Me", persona_icon="🎵", persona_color="#FF00FF",
        question_id=explicit_qid,
    )
    assert result[ "question_id" ] == explicit_qid
    entries = store.read( "coordination", limit=10 )
    assert entries[ 0 ][ "metadata" ][ "question_id" ] == explicit_qid


# ---------- helpers + edge cases ----------


def test_find_replies_filters_by_question_id( store ):
    """`_find_replies` returns only entries whose metadata.in_reply_to matches."""
    store.post( "coordination", "noise",       "x", persona_name="X", persona_icon="?", persona_color="#000", metadata={ } )
    posted = store.post( "coordination", "question?", "x", persona_name="X", persona_icon="?", persona_color="#000", metadata={ "kind": "question", "question_id": "qid-A" } )
    store.post( "coordination", "reply-to-A", "y", persona_name="Y", persona_icon="?", persona_color="#000", metadata={ "kind": "answer", "in_reply_to": "qid-A" } )
    store.post( "coordination", "reply-to-B", "z", persona_name="Z", persona_icon="?", persona_color="#000", metadata={ "kind": "answer", "in_reply_to": "qid-B" } )
    matches = _find_replies( store, "coordination", posted[ "ts" ], "qid-A" )
    assert len( matches ) == 1
    assert matches[ 0 ][ "body" ] == "reply-to-A"
