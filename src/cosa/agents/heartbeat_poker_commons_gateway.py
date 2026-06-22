"""
LupinCommonsGateway — production CommonsGateway for HeartbeatPokerJob.

Implements the `CommonsGateway` protocol (defined in `heartbeat_poker_job.py`)
over the server-side `CommonsStore` plus the `/api/commons/register-question`
Phase-3 push. Reference pattern: `fire_heartbeat()` in
`src/scripts/cascade_heartbeat_scheduler.py`.

ARCHITECTURE — every external dependency (the `CommonsStore`, the HTTP-post
callable, the API key, the base URL, the sender persona) is constructor-
injected. This module is therefore PURE ADAPTER LOGIC: no disk reads, no
network, no `lupin_mcp` import at module scope — and so it is 100%-unit-
testable with fakes, with zero `pragma: no cover`.

The production-wiring step that constructs the real `CommonsStore`, loads the
API key, and passes `requests.post` lives at the poker's call-site / the
agentic-job factory — see the `heartbeat_poker_job.py` module docstring.

Design: `src/rnd/v0.1.7/2026.05.22-heartbeat-poker-d1d4-class-spec.md` §2.3, §9
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

from cosa.agents.heartbeat_poker_job import RecipientSpec
from lupin_mcp.persona_normalization import canonical_persona_key, persona_slug


class LupinCommonsGateway:
    """
    Production `CommonsGateway` — server-side, in-process.

    Satisfies the `CommonsGateway` protocol: `send_to` / `last_post_ts` /
    `read_since`. All I/O dependencies are injected (see module docstring).
    """

    def __init__(
        self,
        sender_session_id : str,
        api_key           : str,
        api_base_url      : str,
        store             : Any,           # a CommonsStore instance
        http_post         : Callable,      # a requests.post-compatible callable
        persona_name      : Optional[ str ] = None,
        persona_icon      : Optional[ str ] = None,
        persona_color     : Optional[ str ] = None,
    ) -> None:
        """
        Requires:
            - sender_session_id, api_key, api_base_url are non-empty strings
            - store exposes post() / read() / who() (a CommonsStore)
            - http_post is a requests.post-compatible callable

        Ensures:
            - all dependencies stored for use by the three protocol methods
        """
        self._sender_session_id = sender_session_id
        self._api_key           = api_key
        self._api_base_url      = api_base_url
        self._store             = store
        self._http_post         = http_post
        self._persona_name      = persona_name
        self._persona_icon      = persona_icon
        self._persona_color     = persona_color

    @classmethod
    def from_environment( cls, sender_session_id: str, persona_name: str = "heartbeat-poker",
                          persona_icon: Optional[ str ] = None,
                          persona_color: Optional[ str ] = None ) -> "LupinCommonsGateway":  # pragma: no cover - production IO wiring (real CommonsStore + API-key file + requests); exercised by the :8000 integration tier, not unit-mockable in isolation
        """
        Build a production gateway wired to the real `CommonsStore` + `requests`.

        The IO-boundary constructor: builds the server-side `CommonsStore`, loads
        the notification API key from disk, and reads `LUPIN_API_URL` from the
        environment. The agentic-job factory calls this; unit tests construct
        `LupinCommonsGateway` directly with injected fakes instead — which is why
        this method (and only this method) is excluded from the coverage gate.
        """
        import os
        from pathlib import Path

        import requests

        import cosa.utils.util as cu
        from lupin_mcp.commons_store import CommonsStore

        project_root = cu.get_project_root()
        api_key      = Path( project_root + "/src/conf/keys/notification-api-claude-code-dev" ).read_text().strip()
        return cls(
            sender_session_id = sender_session_id,
            api_key           = api_key,
            api_base_url      = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ),
            store             = CommonsStore( root=project_root ),
            http_post         = requests.post,
            persona_name      = persona_name,
            persona_icon      = persona_icon,
            persona_color     = persona_color,
        )

    @staticmethod
    def dm_topic_for( identifier: str ) -> str:
        """
        Derive a server-pattern-safe DM topic from a recipient identifier.

        Routes through the shared `persona_slug` root (Phase 4 of the
        persona-name-normalization plan) so the topic ALWAYS equals
        `dm-{persona_slug( identifier, sep='_' )}` — byte-identical to the
        Arbiter gateway, the cascade scheduler, and the MCP DM layer
        (`_derive_dm_topic`). Accent-proof: `"Mr Radio"` → `"dm-mr_radio"`,
        `"María"` → `"dm-maria"`. The prior accent-leaky
        `re.sub( ..., re.UNICODE )` kept accents, regenerating the SPLIT topic
        `"dm-maría"` (the live bug: both `dm-maría.md` and `dm-maria.md`
        existed) — this seam now converges on the canonical `"dm-maria"`.
        """
        return f"dm-{persona_slug( identifier, sep='_' )}"

    def send_to( self, recipient: RecipientSpec, body: str ) -> None:
        """
        Deliver one poke: write the entry to the recipient's DM topic via the
        `CommonsStore`, then fire the `/api/commons/register-question` Phase-3
        push so the recipient's CC session sees a `COMMONS PEER MESSAGE`.

        The disk post is authoritative; the push is best-effort — a recipient
        that misses the push still sees the poke on its next commons poll, so
        a push failure is swallowed (the disk post has already succeeded).
        """
        qid   = str( uuid.uuid4() )
        topic = self.dm_topic_for( recipient.identifier )

        self._store.post(
            topic             = topic,
            body              = body,
            sender_session_id = self._sender_session_id,
            persona_name      = self._persona_name,
            persona_icon      = self._persona_icon,
            persona_color     = self._persona_color,
            metadata          = {
                "kind"              : "heartbeat",
                "question_id"       : qid,
                "recipient_persona" : recipient.identifier,
            },
        )

        try:
            self._http_post(
                f"{self._api_base_url}/api/commons/register-question",
                json    = {
                    "topic"             : topic,
                    "question_id"       : qid,
                    "asker_session_id"  : self._sender_session_id,
                    "recipient_persona" : recipient.identifier,
                    "expect_reply"      : False,
                    "ttl_seconds"       : 60,
                },
                headers = { "X-API-Key": self._api_key },
                timeout = 5,
            )
        except Exception:
            # Disk post already succeeded — the Phase-3 push is best-effort.
            pass

    def last_post_ts( self, recipient: RecipientSpec ) -> Optional[ str ]:
        """
        Most-recent commons-post timestamp for `recipient`, or `None`.

        `who()` rows carry `session_id` + `persona_name`; the recipient is
        matched on whichever its `identifier_type` names. `who()` is
        newest-first, so for a persona-addressed recipient with duplicate
        active sessions the first match is the most-recently-active session
        (d1d4 spec §9 item 2).
        """
        for row in self._store.who():
            if recipient.identifier_type == "session_id":
                if row.get( "session_id" ) == recipient.identifier:
                    return row.get( "last_post_ts" )
            else:
                # Identity parity (Phase 2): match a persona-addressed recipient
                # by the one canonical key so an accented/punctuated persona
                # ("María", "Mr. Radio") matches its who()-row persona_name. Both
                # compare sides moved in lockstep.
                if canonical_persona_key( row.get( "persona_name" ) ) == canonical_persona_key( recipient.identifier ):
                    return row.get( "last_post_ts" )
        return None

    def read_since( self, topic: str, since_iso: str ) -> List[ Dict[ str, Any ] ]:
        """Return commons entries on `topic` posted strictly after `since_iso`."""
        return self._store.read( topic, since=since_iso, limit=100_000 )
