"""
Listener-side broadcast orchestrator.

Per AC6 + F2 (REUSE) + T1 + T3 (Pass 2 Adversarial) of
src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md.

Pure orchestrator — callable from BOTH `cc_notification_listener._handle_action`
AND directly from unit tests with mocked dependencies. All sub-pieces are
reuse-as-is (per F2 REUSE):

- `commons_persona_matcher.match_persona()` — Phase 1, 100% covered
- listener's `_inject_via_tmux(text, wrap=False)` — injected as `inject_fn` callable
- `commons_store.CommonsStore.post(topic="broadcast-acks", ...)` — injected as `store`

The handler parses the broadcast body into default lines (no leading `@`) +
persona-directive lines (`@PersonaName:`), computes the effective slice for the
local persona, builds a `<system-reminder>` wrapper, and posts a per-session
acknowledgment to the `broadcast-acks` reserved topic.

**Sanitization** (T1 + T3): body containing `<system-reminder>` or
`</system-reminder>` substrings (case-insensitive) is rejected at the
listener boundary as defense-in-depth — endpoint already rejects at AC1, but
the listener does NOT trust the endpoint. Match → ack with
`status="rejected-malformed"` + no injection.

**Skip-with-ack** (A6 / AC6): body containing ONLY persona-directive lines
where none match the local persona → ack with `status="skipped"` + no injection.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from lupin_mcp.commons_persona_matcher import match_persona
from lupin_mcp.commons_store import (
    DEFAULT_PERSONA_COLOR,
    DEFAULT_PERSONA_ICON,
    DEFAULT_PERSONA_NAME,
    CommonsStore,
)

_SYSTEM_REMINDER_OPEN  = "<system-reminder>"
_SYSTEM_REMINDER_CLOSE = "</system-reminder>"

_ALL_ALIASES = ( "all", "everyone" )


def _contains_reminder_framing( body: str ) -> bool:
    """True if body contains literal `<system-reminder>` or `</system-reminder>` (case-insensitive)."""
    lowered = body.lower()
    return _SYSTEM_REMINDER_OPEN in lowered or _SYSTEM_REMINDER_CLOSE in lowered


def _parse_body(
    body                : str,
    local_persona_name  : Optional[ str ],
) -> Tuple[ List[ str ], List[ str ], int ]:
    """
    Split body into (default_lines, matched_directive_lines, non_matching_directive_count).

    A line starting with `@PersonaName:` is a persona-directive:
    - `@all:` / `@everyone:` (case-insensitive) → treated as default scope
    - matches local persona (via case-insensitive + punctuation-tolerant match) → goes into matched_directives
    - other personas → ignored silently (counted for skip-detection)

    Lines starting with `@` but lacking a colon are treated as default lines (malformed directive).
    """
    default_lines: List[ str ]            = [ ]
    matched_directive_lines: List[ str ]  = [ ]
    non_matching_directive_count          = 0

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith( "@" ):
            colon_idx = stripped.find( ":" )
            if colon_idx == -1:
                # malformed directive — treat as default
                default_lines.append( line )
                continue
            persona_ref = stripped[ 1:colon_idx ].strip()
            if persona_ref.lower() in _ALL_ALIASES:
                default_lines.append( line )
                continue
            if local_persona_name is not None:
                matched = match_persona( persona_ref, [ local_persona_name ] )
                if matched == local_persona_name:
                    matched_directive_lines.append( line )
                    continue
            non_matching_directive_count += 1
        else:
            default_lines.append( line )

    return ( default_lines, matched_directive_lines, non_matching_directive_count )


def _build_reminder( broadcast_id: str, effective_body: str ) -> str:
    """Wrap `effective_body` in a `<system-reminder>` block with broadcast_id header."""
    return (
        f"{_SYSTEM_REMINDER_OPEN}\n"
        f"USER BROADCAST (broadcast_id {broadcast_id}):\n\n"
        f"{effective_body}\n"
        f"{_SYSTEM_REMINDER_CLOSE}"
    )


def _post_ack(
    store               : CommonsStore,
    broadcast_id        : str,
    status              : str,
    body_summary        : str,
    sender_session_id   : str,
    local_persona       : Optional[ Dict[ str, Any ] ],
) -> Dict[ str, Any ]:
    """Post a single ack entry to the `broadcast-acks` reserved topic."""
    persona = local_persona or { }
    return store.post(
        topic             = "broadcast-acks",
        body              = status,
        sender_session_id = sender_session_id,
        persona_name      = persona.get( "name" )  or DEFAULT_PERSONA_NAME,
        persona_icon      = persona.get( "icon" )  or DEFAULT_PERSONA_ICON,
        persona_color     = persona.get( "color" ) or DEFAULT_PERSONA_COLOR,
        metadata          = {
            "kind"         : "ack",
            "broadcast_id" : broadcast_id,
            "status"       : status,
            "body_summary" : body_summary,
        },
    )


def handle_broadcast(
    notification        : Dict[ str, Any ],
    local_persona       : Optional[ Dict[ str, Any ] ],
    inject_fn           : Callable[ [ str ], None ],
    store               : CommonsStore,
    sender_session_id   : str,
) -> Dict[ str, Any ]:
    """
    Process a `action:broadcast_received` notification end-to-end.

    Requires:
        - `notification.payload` is a dict containing `body: str` + `broadcast_id: str`
        - `local_persona` is the bridge's `voice_persona` dict (or None if unallocated)
        - `inject_fn(text)` injects `text` into the local session's tmux (closes over the listener instance)
        - `store` is a `CommonsStore` rooted at `<LUPIN_ROOT>/io/commons`
        - `sender_session_id` is the local session's id

    Ensures:
        - On reminder-framing detection: posts ack with `status="rejected-malformed"` + does NOT call inject_fn
        - On skip-detection (body has no default lines AND no matched directives): posts ack with `status="skipped"` + does NOT call inject_fn
        - On normal path: composes effective body (default + matched directives), builds `<system-reminder>` wrapper, calls inject_fn(wrapper), posts ack with `status="completed"`
        - Returns a dict `{status, broadcast_id, ack_entry}` for callers that need to introspect the outcome (tests, future MCP path)

    Notes:
        - Malformed notifications (missing payload / body / broadcast_id) → returns `{status="error", reason=...}` without calling inject_fn or posting ack (cannot ack without a broadcast_id correlation)
    """
    payload = notification.get( "payload" ) or { }
    body         = payload.get( "body" )
    broadcast_id = payload.get( "broadcast_id" )

    if not isinstance( body, str ) or not isinstance( broadcast_id, str ) or not broadcast_id:
        return { "status": "error", "reason": "missing or malformed payload (need body + broadcast_id)" }

    # Pass 2 T1 + T3: defense-in-depth sanitization
    if _contains_reminder_framing( body ):
        ack = _post_ack(
            store             = store,
            broadcast_id      = broadcast_id,
            status            = "rejected-malformed",
            body_summary      = "body contained system-reminder framing tags",
            sender_session_id = sender_session_id,
            local_persona     = local_persona,
        )
        return { "status": "rejected-malformed", "broadcast_id": broadcast_id, "ack_entry": ack }

    local_persona_name = ( local_persona or { } ).get( "name" )
    default_lines, matched_directive_lines, _ = _parse_body( body, local_persona_name )

    if not default_lines and not matched_directive_lines:
        # Empty body or all-non-matching directives → A6 skip-with-ack
        ack = _post_ack(
            store             = store,
            broadcast_id      = broadcast_id,
            status            = "skipped",
            body_summary      = "no applicable directive for this persona",
            sender_session_id = sender_session_id,
            local_persona     = local_persona,
        )
        return { "status": "skipped", "broadcast_id": broadcast_id, "ack_entry": ack }

    effective_body = "\n".join( default_lines + matched_directive_lines )
    reminder = _build_reminder( broadcast_id, effective_body )
    inject_fn( reminder )

    summary = effective_body if len( effective_body ) <= 200 else effective_body[ :197 ] + "..."
    ack = _post_ack(
        store             = store,
        broadcast_id      = broadcast_id,
        status            = "completed",
        body_summary      = summary,
        sender_session_id = sender_session_id,
        local_persona     = local_persona,
    )
    return { "status": "completed", "broadcast_id": broadcast_id, "ack_entry": ack }
