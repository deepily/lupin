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
    api_base_url         : str,
    auth_header          : Dict[ str, str ],
    topic                : str,
    question_id          : str,
    asker_session_id     : str,
    ttl_seconds          : int,
    timeout_seconds      : float,
    debug                : bool = False,
    recipient_session_id : Optional[ str ] = None,
    recipient_persona    : Optional[ str ] = None,
    expect_reply         : bool = True,
) -> Dict[ str, Any ]:
    """
    Fire `POST {api_base_url}/api/commons/register-question`.

    Returns a result dict:
      {"success": True,  "dm_dispatched": Optional[bool]}                — 2xx
      {"success": False, "http_status": int, "detail": Any}              — non-2xx (422 carries RecipientResolutionError body)
      {"success": False, "http_status": None, "detail": "<error string>"} — network/library failure

    Per F1-fit (Option A) — silent fallback to polling mode on any non-2xx OR
    error. The result dict surfaces the failure shape so the caller can decide
    whether to surface a RecipientResolutionError to the AI agent (Phase 0
    Q3-rev amendment 2026-05-15) vs treat as a transient register glitch.

    Inter-Session DM extension (2026-05-15):
    - `recipient_session_id` / `recipient_persona` / `expect_reply` passed through
      to the endpoint, which resolves recipient + dispatches `commons_question_received`
      to the recipient's listener fire-and-forget per Phase 0 Q2-rev.
    """
    try:
        import requests  # Lazy import; not all MCP environments have requests installed yet.
    except ImportError:
        if debug: print( "[commons_ask] push-mode skipped — `requests` not available, falling back to polling" )
        return { "success": False, "http_status": None, "detail": "requests library unavailable" }

    url = api_base_url.rstrip( "/" ) + _REGISTER_QUESTION_PATH
    payload : Dict[ str, Any ] = {
        "topic"            : topic,
        "question_id"      : question_id,
        "asker_session_id" : asker_session_id,
        "ttl_seconds"      : int( ttl_seconds ),
    }
    if recipient_session_id is not None:
        payload[ "recipient_session_id" ] = recipient_session_id
    if recipient_persona is not None:
        payload[ "recipient_persona" ] = recipient_persona
    if not expect_reply:
        payload[ "expect_reply" ] = False

    try:
        resp = requests.post( url, json=payload, headers=auth_header, timeout=timeout_seconds )
    except Exception as e:
        if debug: print( f"[commons_ask] push-mode register failed: {e!r} — falling back to polling" )
        return { "success": False, "http_status": None, "detail": repr( e ) }

    if 200 <= resp.status_code < 300:
        try:
            body = resp.json()
        except Exception:
            body = { }
        return { "success": True, "dm_dispatched": body.get( "dm_dispatched" ) }

    if debug: print( f"[commons_ask] push-mode register returned HTTP {resp.status_code} — falling back to polling" )
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text
    return { "success": False, "http_status": resp.status_code, "detail": detail }


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
    # Inter-Session DM extension (Phase 0 §14 2026-05-15) — all optional; absent → non-DM ask_async
    recipient_session_id : Optional[ str ] = None,
    recipient_persona    : Optional[ str ] = None,
    expect_reply         : bool            = True,
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

    # Stamp recipient metadata on the question entry so render path can show
    # the "→ @recipient" badge in Recent Activity (AC8 / Phase 0 Q4-rev "same
    # broadcasts topic + DM badge"). The asker's persona is already stamped
    # by store.post; recipient is the new dimension.
    metadata : Dict[ str, Any ] = { "kind": "question", "question_id": question_id }
    if recipient_persona is not None:
        metadata[ "recipient_persona" ] = recipient_persona
    if recipient_session_id is not None:
        metadata[ "recipient_session_id" ] = recipient_session_id
    if not expect_reply:
        metadata[ "expect_reply" ] = False

    posted = store.post(
        topic             = topic,
        body              = body,
        sender_session_id = sender_session_id,
        persona_name      = persona_name,
        persona_icon      = persona_icon,
        persona_color     = persona_color,
        metadata          = metadata,
    )

    # Phase 3 push-mode register (best-effort, silent fallback on failure per F1-fit)
    # 2026-05-16 observability fix: surface `register_skip_reason` whenever push-mode
    # was REQUESTED but the dispatch was skipped or failed. Previously the caller
    # got `push_mode_active=False` with no signal distinguishing "missing auth header"
    # from "I didn't request push-mode" from "register returned non-2xx". The 422
    # RecipientResolutionError was the only error path that surfaced anything.
    push_mode_active     : bool                          = False
    dm_dispatched        : Optional[ bool ]              = None
    register_error       : Optional[ Dict[ str, Any ] ]  = None
    register_skip_reason : Optional[ str ]               = None

    if push_mode_enabled:
        if not api_base_url:
            register_skip_reason = "missing_api_base_url"
            if debug: print( "[commons_ask] push-mode skipped — api_base_url is empty" )
        elif not auth_header:
            register_skip_reason = "missing_auth_header"
            if debug: print( "[commons_ask] push-mode skipped — auth_header is None (LUPIN_MCP_API_KEY or notification-api-claude-code-dev key unavailable)" )
        else:
            register_result = _register_push_mode(
                api_base_url         = api_base_url,
                auth_header          = auth_header,
                topic                = topic,
                question_id          = question_id,
                asker_session_id     = sender_session_id,
                ttl_seconds          = int( ttl_seconds ),
                timeout_seconds      = register_timeout_s,
                debug                = debug,
                recipient_session_id = recipient_session_id,
                recipient_persona    = recipient_persona,
                expect_reply         = expect_reply,
            )
            if register_result.get( "success" ):
                push_mode_active = True
                dm_dispatched    = register_result.get( "dm_dispatched" )
            else:
                # Surface 422 RecipientResolutionError to caller so the AI agent
                # can self-correct (Phase 0 Q3-rev amendment). All other failures
                # surface a `register_skip_reason` so the caller has a debugging signal
                # without parsing the detail body.
                http_status = register_result.get( "http_status" )
                if http_status == 422:
                    register_error       = register_result.get( "detail" )
                    register_skip_reason = "register_failed_422"
                elif http_status is None:
                    # Network / library failure (see _register_push_mode contract)
                    register_skip_reason = "register_network_error"
                else:
                    register_skip_reason = f"register_failed_status_{http_status}"

    result : Dict[ str, Any ] = {
        "question_id"      : question_id,
        "posted_ts"        : posted[ "ts" ],
        "push_mode_active" : push_mode_active,
    }
    if dm_dispatched is not None:
        result[ "dm_dispatched" ] = dm_dispatched
    if register_error is not None:
        result[ "recipient_resolution_error" ] = register_error
    if register_skip_reason is not None:
        result[ "register_skip_reason" ] = register_skip_reason
    return result
