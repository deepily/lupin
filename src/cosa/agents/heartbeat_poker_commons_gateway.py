"""
LupinCommonsGateway: production CommonsGateway for HeartbeatPokerJob.

Implements the `CommonsGateway` protocol (defined in `heartbeat_poker_job.py`)
over the server-side `CommonsStore`. Each poke is also pushed through the
notification-native `/api/dm/send` route.

Every external dependency is constructor-injected: the `CommonsStore`, the
HTTP-post callable, the API key, the base URL and the sender persona. The
protocol methods are therefore pure adapter logic with no disk reads and no
network. The module is fully unit-testable with fakes and carries no
`pragma: no cover`.

`from_environment` is the one IO boundary here. It reads the API key from disk
and constructs the real `CommonsStore`. Its dependencies are imported inside
the function body, so unit tests monkeypatch them rather than exempting the
method.

The production wiring lives at the poker's call-site and the agentic-job
factory. See the `heartbeat_poker_job.py` module docstring.
"""

from __future__ import annotations

import sys
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
        Store the injected dependencies for the three protocol methods.

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
                          persona_color: Optional[ str ] = None ) -> "LupinCommonsGateway":
        """
        Build a production gateway wired to the real `CommonsStore` and `requests`.

        The agentic-job factory calls this. Its dependencies are imported inside
        the body, so a monkeypatch can replace all of them and the method needs
        no `no cover` pragma.

        Requires:
            - <project_root>/src/conf/keys/notification-api-claude-code-dev exists

        Ensures:
            - returns a gateway whose api_key is that file's contents, stripped
            - api_base_url is $LUPIN_API_URL, defaulting to http://localhost:7999
            - store is a CommonsStore rooted at the resolved project root
            - http_post is requests.post

        Raises:
            - FileNotFoundError if the API key file is absent — a gateway that
              cannot authenticate must not be constructed silently
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

        Routes through the shared `persona_slug` root, so the topic always equals
        `dm-{persona_slug( identifier, sep='_' )}`. That is byte-identical to the
        Arbiter gateway, the cascade scheduler and the MCP DM layer
        (`_derive_dm_topic`). It is accent-proof: `"Mr Radio"` gives
        `"dm-mr_radio"` and `"María"` gives `"dm-maria"`. A regex that kept
        accents would split one persona across two topics.
        """
        return f"dm-{persona_slug( identifier, sep='_' )}"

    def send_to( self, recipient: RecipientSpec, body: str ) -> None:
        """
        Deliver one poke: post it to the recipient's DM topic, then push it.

        The entry is written through the `CommonsStore`, then sent to
        `/api/dm/send` so the recipient's session receives the body inline as an
        'ai_to_ai' DM.

        The disk post is authoritative and the push is best-effort. A recipient
        that misses the push still sees the poke on its next commons poll, so a
        push failure never loses the poke. The failure is logged, not swallowed,
        because the pilot's stopping rule reads that evidence. A non-2xx response
        does not raise through requests.post, so the status is inspected
        explicitly.

        The body rides inline with no commons claim-check. `thread_id` carries
        the same `qid` as the disk post's metadata so board-polling receipts
        still correlate. The durable dm-<persona> board write is the
        receipt-polling substrate.
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
            response = self._http_post(
                f"{self._api_base_url}/api/dm/send",
                json    = {
                    "sender_session_id" : self._sender_session_id,
                    "recipient_persona" : recipient.identifier,
                    "body"              : body,
                    "thread_id"         : qid,
                    # The arbiter's project, stated rather than left to the server
                    # to guess (row 12b5a766). "lupin" is genuinely this poker's
                    # project — unlike the server-side fallback, which returns
                    # "lupin" for every caller regardless of whose DM it is, and
                    # so happens to be right here for the wrong reason.
                    "sender_project"    : "lupin",
                },
                headers = { "X-API-Key": self._api_key },
                timeout = 5,
            )
        except Exception as exception:
            # Transport-level failure (timeout, refused connection). The disk post
            # already succeeded, so the poke survives — but LOG the failure, never
            # swallow it: the stopping rule needs this evidence.
            self._log_push_failure( recipient, None, repr( exception ) )
            return

        # requests.post returns a Response on a 413 rather than raising, so the
        # refusal only surfaces if the status code is inspected here.
        if response.status_code >= 400:
            self._log_push_failure( recipient, response.status_code, response.text )

    def _log_push_failure( self, recipient: RecipientSpec, status_code: Optional[ int ], detail: str ) -> None:
        """
        Emit one greppable line recording a poke-push failure.

        Requires:
            - recipient is a RecipientSpec
            - status_code is the HTTP status int, or None for a transport-level failure
            - detail is a short string (exception repr or response body)

        Ensures:
            - writes one HEARTBEAT_POKE_SEND_FAILED line to stderr naming the
              recipient and status code — the evidence the stopping rule reads
        """
        print(
            f"[HEARTBEAT_POKE_SEND_FAILED] recipient={recipient.identifier} "
            f"status={status_code} detail={detail}",
            file = sys.stderr,
        )

    def last_post_ts( self, recipient: RecipientSpec ) -> Optional[ str ]:
        """
        Most-recent commons-post timestamp for `recipient`, or `None`.

        `who()` rows carry `session_id` and `persona_name`; the recipient is
        matched on whichever its `identifier_type` names. `who()` is
        newest-first, so for a persona-addressed recipient with duplicate
        active sessions the first match is the most-recently-active session.
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
