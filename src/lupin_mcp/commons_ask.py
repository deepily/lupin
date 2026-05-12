"""
Ask/answer primitives for inter-session commons.

Per AC6 + AC7 in src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md.

`ask_sync` posts a question to a topic, blocks until the first matching reply
arrives, then waits an additional `grace_seconds` to coalesce any fast follow-up
replies before returning the accumulated list. `ask_async` posts a question and
returns immediately with `{question_id, posted_ts}` — caller polls via
`CommonsStore.read(..., since=posted_ts)` filtering on
`metadata.in_reply_to == question_id` (Phase 1 deviation D1; Phase 3 wires
push-based `<system-reminder>` injection without changing the MCP tool signature).

Both helpers correlate question→answer via a UUIDv4 `question_id` recorded under
`metadata.question_id` on the question entry and `metadata.in_reply_to` on the
reply entry, mirroring the existing `cosa/rest/notification_fifo_queue.py:50-51`
UUID-correlation pattern (per F10 REUSE).
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from lupin_mcp.commons_store import CommonsStore

_DEFAULT_POLL_INTERVAL_SECONDS = 0.02


def _find_replies( store: CommonsStore, topic: str, since_ts: str, question_id: str ) -> List[ Dict[ str, Any ] ]:
    """Return entries in `topic` posted after `since_ts` whose metadata.in_reply_to matches `question_id`."""
    entries = store.read( topic, since=since_ts, limit=10000 )
    return [ e for e in entries if e[ "metadata" ].get( "in_reply_to" ) == question_id ]


def ask_sync(
    store               : CommonsStore,
    topic               : str,
    body                : str,
    sender_session_id   : str,
    persona_name        : Optional[ str ] = None,
    persona_icon        : Optional[ str ] = None,
    persona_color       : Optional[ str ] = None,
    timeout_seconds     : float = 120.0,
    grace_seconds       : float = 1.0,
    poll_interval       : float = _DEFAULT_POLL_INTERVAL_SECONDS,
) -> Dict[ str, Any ]:
    """
    Post a question and block until the first reply arrives + grace window expires.

    Requires:
        - `store` is a CommonsStore
        - `timeout_seconds` > 0
        - `grace_seconds` >= 0
        - `poll_interval` > 0

    Ensures:
        - Question is posted to `topic` with metadata `{kind: "question", question_id: <uuid4>}`
        - Polls every `poll_interval` until the first matching reply OR `timeout_seconds` expires
        - On first reply seen: waits `grace_seconds` more, then re-reads to coalesce any
          additional fast replies, returns `{question_id, posted_ts, replies: [...]}`
        - On timeout with zero replies: returns `{question_id, posted_ts, replies: []}`
    """
    question_id = str( uuid.uuid4() )
    posted = store.post(
        topic             = topic,
        body              = body,
        sender_session_id = sender_session_id,
        persona_name      = persona_name,
        persona_icon      = persona_icon,
        persona_color     = persona_color,
        metadata          = { "kind": "question", "question_id": question_id },
    )
    posted_ts = posted[ "ts" ]

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        replies = _find_replies( store, topic, posted_ts, question_id )
        if replies:
            grace_end = time.monotonic() + grace_seconds
            while time.monotonic() < grace_end:
                remaining = grace_end - time.monotonic()
                time.sleep( max( 0.0, min( poll_interval, remaining ) ) )
            replies = _find_replies( store, topic, posted_ts, question_id )
            return { "question_id": question_id, "posted_ts": posted_ts, "replies": replies }
        time.sleep( poll_interval )
    return { "question_id": question_id, "posted_ts": posted_ts, "replies": [ ] }


def ask_async(
    store               : CommonsStore,
    topic               : str,
    body                : str,
    sender_session_id   : str,
    persona_name        : Optional[ str ] = None,
    persona_icon        : Optional[ str ] = None,
    persona_color       : Optional[ str ] = None,
    question_id         : Optional[ str ] = None,
) -> Dict[ str, Any ]:
    """
    Post a question and return immediately. Phase 1 degraded contract (D1 deviation).

    Caller polls via `CommonsStore.read(topic, since=posted_ts)` and filters for
    entries whose `metadata.in_reply_to == question_id` to detect answers. Phase 3
    wires push-based `<system-reminder>` injection without changing this signature.

    Requires:
        - `store` is a CommonsStore

    Ensures:
        - If `question_id` is None, generates a fresh UUIDv4
        - Posts the question to `topic` with metadata `{kind: "question", question_id}`
        - Returns `{question_id, posted_ts}` immediately
    """
    if question_id is None:
        question_id = str( uuid.uuid4() )
    posted = store.post(
        topic             = topic,
        body              = body,
        sender_session_id = sender_session_id,
        persona_name      = persona_name,
        persona_icon      = persona_icon,
        persona_color     = persona_color,
        metadata          = { "kind": "question", "question_id": question_id },
    )
    return { "question_id": question_id, "posted_ts": posted[ "ts" ] }
