#!/usr/bin/env python3
"""
Heartbeat Arbiter — production commons gateway (Rachel's wiring lane).

The server-side, in-process implementation of the `ArbiterGateway` protocol
(arbiter_job.ArbiterGateway). The arbiter runs inside the CJ Flow agentic pool,
so it talks to the commons via the `CommonsStore` directly — NOT the cosa-voice
MCP tool surface (that is for CC sessions). All I/O is behind the injected
`store`, so the gateway LOGIC is 100% unit-testable with a FakeStore; only the
`from_environment` IO-boundary constructor is `pragma: no cover` (exercised at
the :8000 integration tier, mirroring LupinCommonsGateway).

Three methods the consumer needs:
    - who()       → list active sessions (liveness SECONDARY + roster)
    - send_to()   → auto-ping a blocker via their DM topic
    - post()      → the manager-surface roster/recommendation
"""
import re
from typing import List, Optional


class LupinArbiterGateway:
    """
    Production ArbiterGateway over a CommonsStore.

    Requires:
        - sender_session_id is a non-empty string (the arbiter's own id)
        - store is a CommonsStore-like object exposing who(...) + post(...)

    Ensures:
        - who/send_to/post delegate to the store; persona fields are stamped
          on every post; never invents data
    """

    def __init__( self, sender_session_id, store, persona_name="heartbeat-arbiter",
                  persona_icon=None, persona_color=None ):
        self.sender_session_id = sender_session_id
        self._store            = store
        self.persona_name      = persona_name
        self.persona_icon      = persona_icon
        self.persona_color     = persona_color

    @staticmethod
    def dm_topic_for( identifier ):
        """
        Derive a server-pattern-safe DM topic from a recipient identifier.

        Ensures:
            - Mirrors the Poker gateway / cascade scheduler:
              "mr radio" → "dm-mr_radio" (re.UNICODE so non-ASCII personas
              survive); spaces/punctuation collapse to "_"
        """
        slug = re.sub( r"[^\w-]+", "_", identifier.strip().lower(), flags=re.UNICODE )
        return f"dm-{slug}"

    def who( self, retention_hours: int = 24 ) -> List[ dict ]:
        """
        Ensures:
            - Returns the CommonsStore.who() rows (active sessions in the
              retention window): {session_id, persona_name, ..., last_post_ts}
        """
        return self._store.who( retention_hours=retention_hours )

    def send_to( self, recipient: str, body: str ) -> None:
        """
        Auto-ping a blocker by posting to their DM topic.

        Ensures:
            - Appends `body` to dm-<recipient> via the store, stamped with the
              arbiter persona + a {kind: "arbiter-ping", recipient_persona}
              metadata envelope (so the recipient's UI renders a DM badge)
        """
        self._store.post(
            self.dm_topic_for( recipient ),
            body,
            self.sender_session_id,
            persona_name  = self.persona_name,
            persona_icon  = self.persona_icon,
            persona_color = self.persona_color,
            metadata      = { "kind": "arbiter-ping", "recipient_persona": recipient },
        )

    def post( self, topic: str, body: str ) -> None:
        """
        Post the manager-surface recommendation to a commons topic.

        Ensures:
            - Appends `body` to `topic` via the store, stamped with the arbiter
              persona + a {kind: "arbiter-surface"} metadata envelope
        """
        self._store.post(
            topic,
            body,
            self.sender_session_id,
            persona_name  = self.persona_name,
            persona_icon  = self.persona_icon,
            persona_color = self.persona_color,
            metadata      = { "kind": "arbiter-surface" },
        )

    @classmethod
    def from_environment( cls, sender_session_id,
                          persona_name="heartbeat-arbiter" ):   # pragma: no cover - production IO boundary
        """
        IO-boundary constructor: build a real CommonsStore + wire the gateway.

        Ensures:
            - Returns a fully-wired LupinArbiterGateway against the real
              file-backed CommonsStore. Marked no-cover — exercised at the
              :8000 integration tier, never in unit tests (mirrors
              LupinCommonsGateway.from_environment).
        """
        from lupin_mcp.commons_store import CommonsStore
        return cls( sender_session_id, CommonsStore(), persona_name=persona_name )


def quick_smoke_test():
    """
    Self-contained smoke test with an in-memory fake store.

    Ensures:
        - Returns True if who/send_to/post delegate + stamp correctly;
          raises AssertionError otherwise.
    """
    class _FakeStore:
        def __init__( self ):
            self.posts = [ ]
        def who( self, topic=None, retention_hours=24 ):
            return [ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": "t" } ]
        def post( self, topic, body, sender_session_id, **kw ):
            self.posts.append( ( topic, body, sender_session_id, kw.get( "metadata" ) ) )

    store = _FakeStore()
    gw    = LupinArbiterGateway( "arb-1", store, persona_name="Arbiter" )

    assert gw.dm_topic_for( "Mr Radio" ) == "dm-mr_radio"
    assert gw.who()[ 0 ][ "session_id" ] == "s1"

    gw.send_to( "Bob", "ping" )
    assert store.posts[ -1 ][ 0 ] == "dm-bob"
    assert store.posts[ -1 ][ 3 ][ "kind" ] == "arbiter-ping"

    gw.post( "fleet-arbiter", "roster" )
    assert store.posts[ -1 ][ 0 ] == "fleet-arbiter"
    assert store.posts[ -1 ][ 3 ][ "kind" ] == "arbiter-surface"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"arbiter_gateway smoke: {'PASS' if ok else 'FAIL'}" )
