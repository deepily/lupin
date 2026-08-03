"""
Caller-side tests for the DM `sender_project` wire field (row 12b5a766).

The server-side half is pinned in
`src/cosa/tests/unit/rest/test_dm_sender_project.py`; this half proves the three
IN-TREE PRODUCTION CALLERS actually put the field on the wire. A server that
prefers a caller-supplied project and callers that never send one would leave the
stamp exactly as broken as before — and every server-side test would still pass.

THE THREE CALLERS (enumerated repo-wide 2026-07-21; zero hits in sibling repos):
    1. cosa_voice_mcp.py `_dm_send_impl`    -> POST /api/dm/send
    2. cosa_voice_mcp.py `_dm_respond_impl` -> POST /api/dm/respond
    3. heartbeat_poker_commons_gateway.py   -> POST /api/dm/send  (the arbiter poker)

WHAT THIS SUITE CANNOT SEE: any consumer of the HTTP endpoint that is not in this
tree. The enumeration behind it was a grep, and a grep cannot find a caller on
another machine. The server's step-1 contract accepts an absent field for exactly
that reason.
"""

import pytest

from lupin_mcp.cosa_voice_mcp import _dm_send_impl, _dm_respond_impl


class _Resp:
    def __init__( self, status_code, payload ):
        self.status_code = status_code
        self._payload    = payload
        self.text        = str( payload )

    def json( self ):
        return self._payload


class _RecordingPost:
    def __init__( self ):
        self.calls = []

    def __call__( self, url, **kwargs ):
        self.calls.append( { "url": url, **kwargs } )
        return _Resp( 201, { "message_id": "m-1", "thread_id": "t-1" } )


def _send( post_fn, sender_project="plan" ):
    return _dm_send_impl(
        recipient            = "mr radio",
        body                 = "ready",
        reply_to             = None,
        thread_id            = None,
        recipient_session_id = None,
        session_id           = "asker-sess-1",
        sender_persona       = "Extra 1",
        sender_icon          = "🪨",
        sender_project       = sender_project,
        api_base_url         = "http://localhost:7999",
        api_key              = "k-123",
        post_fn              = post_fn,
    )


def _respond( post_fn, sender_project="plan" ):
    return _dm_respond_impl(
        recipient            = "mr radio",
        body                 = "threaded",
        reply_to             = "m-7",
        thread_id            = "th-7",
        recipient_session_id = None,
        session_id           = "asker-sess-1",
        sender_persona       = "Extra 1",
        sender_icon          = "🪨",
        sender_project       = sender_project,
        api_base_url         = "http://localhost:7999",
        api_key              = "k-123",
        post_fn              = post_fn,
    )


def test_send_puts_the_callers_project_on_the_wire():
    """The value the caller resolved host-side reaches the server."""
    post = _RecordingPost()
    _send( post )
    assert post.calls[ 0 ][ "json" ][ "sender_project" ] == "plan"


def test_respond_puts_the_callers_project_on_the_wire():
    """The reply path is a separate payload builder — it needs its own receipt."""
    post = _RecordingPost()
    _respond( post )
    assert post.calls[ 0 ][ "json" ][ "sender_project" ] == "plan"


def test_the_wire_field_tracks_the_argument_not_a_constant():
    """
    CONTROL — a payload builder that hardcoded "lupin" would satisfy every
    assertion above if this suite only ever passed one project. Two different
    projects must produce two different payloads, or these tests are checking a
    constant.
    """
    post = _RecordingPost()
    _send( post, sender_project="plan" )
    _send( post, sender_project="cosa-voice" )
    assert post.calls[ 0 ][ "json" ][ "sender_project" ] == "plan"
    assert post.calls[ 1 ][ "json" ][ "sender_project" ] == "cosa-voice"


@pytest.mark.parametrize( "impl", [ _dm_send_impl, _dm_respond_impl ] )
def test_sender_project_is_required_not_defaulted( impl ):
    """
    A defaulted `sender_project` would re-create the defect one layer up: a caller
    that forgets it would send nothing and be stamped @lupin, silently. Omission
    must be a TypeError at the call, not a quiet fallback.
    """
    with pytest.raises( TypeError ):
        impl(
            recipient            = "mr radio",
            body                 = "ready",
            reply_to             = "m-7",
            thread_id            = "th-7",
            recipient_session_id = None,
            session_id           = "asker-sess-1",
            sender_persona       = "Extra 1",
            sender_icon          = "🪨",
            api_base_url         = "http://localhost:7999",
            api_key              = "k-123",
            post_fn              = _RecordingPost(),
        )


def test_arbiter_poker_sends_its_own_project():
    """
    The third caller. Its project genuinely IS lupin — but it now SAYS so, rather
    than relying on a server-side resolver that answers "lupin" for everyone and
    would be right here for the wrong reason.
    """
    from cosa.agents.heartbeat_poker_commons_gateway import LupinCommonsGateway, RecipientSpec

    class _FakeStore:
        def __init__( self ): self.posts = []
        def post( self, **kwargs ): self.posts.append( kwargs )

    post    = _RecordingPost()
    gateway = LupinCommonsGateway(
        sender_session_id = "hp-sender",
        api_key           = "k-123",
        api_base_url      = "http://localhost:7999",
        store             = _FakeStore(),
        http_post         = post,
        persona_name      = "heartbeat-poker",
    )
    gateway.send_to(
        RecipientSpec( identifier="tiberius", identifier_type="persona", role="watcher" ),
        "poke-body"
    )

    assert post.calls[ 0 ][ "json" ][ "sender_project" ] == "lupin"
