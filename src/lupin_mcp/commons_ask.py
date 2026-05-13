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

# Phase 3 push-mode (F1-fit + F2-fit + AC5):
# - `commons api base url` is the register endpoint's HTTP base
# - `commons ask async push mode enabled` toggles the register call
# - On register failure (any exception), we log + fall through silently to
#   the Phase 1 polling-mode contract (caller polls via store.read).
_REGISTER_QUESTION_PATH    = "/api/commons/register-question"
_REGISTER_DEFAULT_TIMEOUT  = 5.0
_DEFAULT_PUSH_MODE_TTL_S   = 3600


def _register_push_mode(
    api_base_url     : str,
    auth_header      : Dict[ str, str ],
    topic            : str,
    question_id      : str,
    asker_session_id : str,
    ttl_seconds      : int,
    timeout_seconds  : float,
    debug            : bool = False,
) -> bool:
    """
    Fire `POST {api_base_url}/api/commons/register-question` and return True on
    success (HTTP 2xx). Any failure (network, non-2xx, timeout, missing requests
    library) returns False — the caller falls back to Phase 1 polling-mode.

    Per F1-fit (Option A) — silent fallback on failure with a warning log.
    """
    try:
        import requests  # Lazy import; not all MCP environments have requests installed yet.
    except ImportError:
        if debug: print( "[commons_ask] push-mode skipped — `requests` not available, falling back to polling" )
        return False

    url = api_base_url.rstrip( "/" ) + _REGISTER_QUESTION_PATH
    payload = {
        "topic"            : topic,
        "question_id"      : question_id,
        "asker_session_id" : asker_session_id,
        "ttl_seconds"      : int( ttl_seconds ),
    }
    try:
        resp = requests.post( url, json=payload, headers=auth_header, timeout=timeout_seconds )
    except Exception as e:
        if debug: print( f"[commons_ask] push-mode register failed: {e!r} — falling back to polling" )
        return False
    if 200 <= resp.status_code < 300:
        return True
    if debug: print( f"[commons_ask] push-mode register returned HTTP {resp.status_code} — falling back to polling" )
    return False


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
    # Phase 3 push-mode (F1-fit + F2-fit + AC5) — all optional; absent → Phase 1 polling
    push_mode_enabled   : bool          = False,
    api_base_url        : Optional[ str ] = None,
    auth_header         : Optional[ Dict[ str, str ] ] = None,
    ttl_seconds         : int           = _DEFAULT_PUSH_MODE_TTL_S,
    register_timeout_s  : float         = _REGISTER_DEFAULT_TIMEOUT,
    debug               : bool          = False,
) -> Dict[ str, Any ]:
    """
    Post a question and return immediately.

    Phase 1 polling contract (preserved): caller polls
    `CommonsStore.read(topic, since=posted_ts)` and filters for entries whose
    `metadata.in_reply_to == question_id` to detect answers.

    Phase 3 push-mode wiring (additive, F1-fit Option A):
        When `push_mode_enabled=True` AND `api_base_url` is set AND
        `auth_header` is provided, fire `POST /api/commons/register-question`
        to register the question with the server-side `CommonsQuestionWatcher`.
        On register failure (any exception, non-2xx, missing `requests`
        library), log a debug warning and silently fall through to polling-
        mode — the polling contract still works, so the caller is unaffected.

    `ask_sync()` is intentionally UNTOUCHED (F10-fit).

    Requires:
        - `store` is a CommonsStore
        - If `push_mode_enabled=True`, both `api_base_url` and `auth_header`
          should be provided (otherwise push-mode is silently skipped).

    Ensures:
        - If `question_id` is None, generates a fresh UUIDv4
        - Posts the question to `topic` with metadata `{kind: "question", question_id}`
        - Returns `{question_id, posted_ts, push_mode_active: bool}`
          (`push_mode_active=True` iff the register call succeeded;
           callers can use this to decide whether to continue polling)
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

    # Phase 3 push-mode register (best-effort, silent fallback on failure per F1-fit)
    push_mode_active = False
    if push_mode_enabled and api_base_url and auth_header:
        push_mode_active = _register_push_mode(
            api_base_url     = api_base_url,
            auth_header      = auth_header,
            topic            = topic,
            question_id      = question_id,
            asker_session_id = sender_session_id,
            ttl_seconds      = int( ttl_seconds ),
            timeout_seconds  = register_timeout_s,
            debug            = debug,
        )

    return {
        "question_id"      : question_id,
        "posted_ts"        : posted[ "ts" ],
        "push_mode_active" : push_mode_active,
    }
