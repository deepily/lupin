#!/usr/bin/env python3
"""
Unit tests for the Heartbeat-Arbiter production gateway (arbiter_gateway.py).

Covers the gateway LOGIC (who/send_to/post delegation + persona/metadata
stamping + dm_topic_for slug) with an injected FakeStore. The from_environment
IO-boundary constructor is pragma:no-cover (integration tier).

Venue: :7999-eligible / local — pure delegation, no real store, sub-second.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway


class FakeStore:
    def __init__( self, who_rows=None ):
        self._who_rows  = who_rows if who_rows is not None else [ { "session_id": "s1" } ]
        self.posts      = [ ]
        self.who_calls  = [ ]

    def who( self, topic=None, retention_hours=24 ):
        self.who_calls.append( retention_hours )
        return list( self._who_rows )

    def post( self, topic, body, sender_session_id, persona_name=None, persona_icon=None,
              persona_color=None, metadata=None ):
        self.posts.append( {
            "topic": topic, "body": body, "sender": sender_session_id,
            "persona_name": persona_name, "metadata": metadata,
        } )

    def read( self, topic, since=None, limit=50 ):
        self.read_calls = getattr( self, "read_calls", [ ] )
        self.read_calls.append( ( topic, since, limit ) )
        return [ { "ts": "t1", "body": "decision?" } ]


def _gw( store=None ):
    return LupinArbiterGateway( "arb-1", store or FakeStore(), persona_name="Arbiter" )


@pytest.mark.parametrize( "ident,expected", [
    ( "Bob", "dm-bob" ),
    ( "Mr Radio", "dm-mr_radio" ),
    ( "Mr. Radio", "dm-mr_radio" ),          # period (punctuation) stripped → mr_radio
    ( "  María 🌸 ", "dm-maria" ),            # Phase 4: accent-stripped + emoji/space trimmed
] )
def test_dm_topic_for_slug( ident, expected ):
    assert LupinArbiterGateway.dm_topic_for( ident ) == expected


def test_dm_topic_for_accented_persona_FLIP():
    """Phase 4 CONTRACT CHANGE + FLIP guard: `dm_topic_for` now routes through
    the shared `persona_slug` root, so an accented persona keys to the CANONICAL
    "dm-maria" — NOT the split "dm-maría" the old accent-leaky
    `re.sub( r"[^\\w-]+", "_", name, flags=re.UNICODE )` produced. That split was
    the live bug: both io/commons/dm-maría.md AND dm-maria.md existed. Revert this
    seam to the re.UNICODE re.sub → it yields "dm-maría" → this assertion fails →
    the test genuinely guards the gateway-completeness fix that durables the cutover."""
    assert LupinArbiterGateway.dm_topic_for( "María" )     == "dm-maria"
    assert LupinArbiterGateway.dm_topic_for( "Mr. Radio" ) == "dm-mr_radio"


def test_who_delegates_with_retention():
    store = FakeStore( who_rows=[ { "session_id": "x" } ] )
    gw    = _gw( store )
    rows  = gw.who( retention_hours=6 )
    assert rows == [ { "session_id": "x" } ]
    assert store.who_calls == [ 6 ]


def test_send_to_posts_to_dm_topic_with_badge():
    store = FakeStore()
    gw    = _gw( store )
    gw.send_to( "Bob", "where are we?" )
    p = store.posts[ -1 ]
    assert p[ "topic" ] == "dm-bob"
    assert p[ "body" ] == "where are we?"
    assert p[ "sender" ] == "arb-1"
    assert p[ "persona_name" ] == "Arbiter"
    assert p[ "metadata" ] == { "kind": "arbiter-ping", "recipient_persona": "Bob" }


def test_post_stamps_surface_metadata():
    store = FakeStore()
    gw    = _gw( store )
    gw.post( "fleet-arbiter", "roster body" )
    p = store.posts[ -1 ]
    assert p[ "topic" ] == "fleet-arbiter"
    assert p[ "metadata" ] == { "kind": "arbiter-surface" }
    assert p[ "persona_name" ] == "Arbiter"


def test_read_delegates_to_store():
    """v2.2 B3: gateway.read tails a topic via the store — pure observation."""
    store = FakeStore()
    gw    = _gw( store )
    out   = gw.read( "fleet-decision-needed", since="t0", limit=10 )
    assert out == [ { "ts": "t1", "body": "decision?" } ]
    assert store.read_calls == [ ( "fleet-decision-needed", "t0", 10 ) ]


def test_quick_smoke_test_passes():
    from cosa.agents.heartbeat_arbiter import arbiter_gateway
    assert arbiter_gateway.quick_smoke_test() is True
