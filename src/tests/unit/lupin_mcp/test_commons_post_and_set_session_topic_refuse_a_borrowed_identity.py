#!/usr/bin/env python3
"""
Two wired tools with no `<tool>_impl` symbol, driven under a guessed identity.

`commons_post` and `set_session_topic` write under the resolved session's name (a commons entry
signed as that seat; a topic written into that seat's bridge file). The guard file proves the
refusal is their first statement. This file drives the assembled tools and asserts the thing the
first-statement check cannot: that a refused call writes nothing.

Each tool has a refuse arm and a negative control. The control carries the file: without it a
tool that refused every call passes the refuse arm.

Venue: :7999-eligible. Module globals are monkeypatched; the bridge is a tmp file; no server, no network.
"""
import json

import pytest

from lupin_mcp import cosa_voice_mcp as m
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


class _Reached( Exception ):
    """Raised by a stubbed seam. Its arrival is the assertion that the guard let go."""


@pytest.fixture
def borrowed( monkeypatch ):
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", sb.SOURCE_CWD_FALLBACK )


@pytest.fixture
def owned( monkeypatch ):
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", sb.SOURCE_PPID )


@pytest.fixture
def bridge( tmp_path, monkeypatch ):
    path = tmp_path / "cc-bridge.json"
    path.write_text( json.dumps( { "session_id": "abcd1234", "session_topic": "colleague's topic" } ) )
    monkeypatch.setattr( m, "_get_cc_metadata", lambda: { "_bridge_path": str( path ) } )
    return path


@pytest.fixture
def store( monkeypatch ):
    """A commons store that records every post; commons is switched on."""
    posts = []

    class _Store:
        def post( self, **kwargs ):
            posts.append( kwargs )
            return { "status": "ok" }

    monkeypatch.setattr( m, "_commons_enabled", lambda: True )
    monkeypatch.setattr( m, "_get_commons_store", lambda: _Store() )
    return posts


def test_set_session_topic_REFUSES_and_leaves_the_bridge_and_the_ui_alone( borrowed, bridge, monkeypatch ):
    before = bridge.read_bytes()
    monkeypatch.setattr( m, "_notify_impl", lambda **k: ( _ for _ in () ).throw( _Reached( "notified" ) ) )

    result = m.set_session_topic.fn( "overwritten" )

    assert result[ "reason" ] == "borrowed_identity" and "set_session_topic" in result[ "detail" ]
    assert bridge.read_bytes() == before


def test_set_session_topic_NEGATIVE_CONTROL_a_definitive_identity_writes( owned, bridge, monkeypatch ):
    monkeypatch.setattr( m, "_notify_impl", lambda **k: "sent" )

    result = m.set_session_topic.fn( "mine" )

    assert result[ "status" ] == "ok"
    assert json.loads( bridge.read_text() )[ "session_topic" ] == "mine"


def test_set_session_topic_refuses_before_it_even_looks_for_the_bridge( borrowed, monkeypatch ):
    """A guessed identity never reaches `_get_cc_metadata`, which finds a colleague's bridge."""
    monkeypatch.setattr( m, "_get_cc_metadata", lambda: ( _ for _ in () ).throw( _Reached( "resolved a bridge" ) ) )

    assert m.set_session_topic.fn( "x" )[ "reason" ] == "borrowed_identity"


def test_commons_post_REFUSES_and_never_asks_for_the_store( borrowed, store, monkeypatch ):
    monkeypatch.setattr( m, "_get_commons_store", lambda: ( _ for _ in () ).throw( _Reached( "store asked" ) ) )

    result = m.commons_post.fn( topic = "presence", body = "hi" )

    assert result[ "reason" ] == "borrowed_identity" and "commons_post" in result[ "detail" ]
    assert store == []


def test_commons_post_REFUSES_even_when_commons_is_switched_off( borrowed, monkeypatch ):
    """The refusal comes first, so a guessed identity is told so rather than 'commons disabled'."""
    monkeypatch.setattr( m, "_commons_enabled", lambda: False )

    assert m.commons_post.fn( topic = "presence", body = "hi" )[ "reason" ] == "borrowed_identity"


def test_commons_post_NEGATIVE_CONTROL_a_definitive_identity_posts_once_under_its_own_id( owned, store ):
    result = m.commons_post.fn( topic = "presence", body = "hi" )

    assert result == { "status": "ok" }
    assert len( store ) == 1
    assert store[ 0 ][ "sender_session_id" ] == m.SESSION_ID and store[ 0 ][ "topic" ] == "presence"
