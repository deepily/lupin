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

The handler parses the broadcast body into default lines (everything that is not
a clean directive — incl. prose that merely starts with/contains an `@`) +
persona-directive lines (a leading PURE run of `@mention` tokens ending in a
colon, e.g. `@a @b: msg`; a directive matches if ANY mention is the local
persona). It computes the effective slice for the local persona, builds a
`<system-reminder>` wrapper, and posts a per-session acknowledgment to the
`broadcast-acks` reserved topic. Bias = fail toward delivery, not suppression.

**Roster-aware discrimination** (2026-06-11 hardening): when the caller supplies
`persona_roster` (names of live persona sessions), a clean `@token: msg` run only
counts as a persona directive if at least ONE mention resembles a roster persona
(case-insensitive + punctuation-tolerant; the local persona is implicitly part of
the roster). A sole bogus run like `@here goes: x` is prose → default line
(delivered), not a directive to a nonexistent persona (which would skip the whole
broadcast when it is the only line). `persona_roster=None` preserves the
roster-blind legacy contract for callers that cannot supply one.

DELIBERATE behavioral delta of the roster gate: a directive to a REAL but
OFFLINE persona (its bridge gone stale, so it is absent from the live roster —
e.g. `@Cheech: do X` after Cheech's session died) now fans out to EVERYONE as
prose, where the legacy parse silently ignored it. Chosen, not missed: under
bias-toward-delivery a directive nobody will ever receive is worse than one
the whole fleet sees — a live peer can relay or act, and the sender learns the
addressee is gone instead of getting silence.

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

# Persona-directive discrimination (see `_directive_mentions`). A real persona
# token is short and free of sentence punctuation; prose is not. Bias = FAIL
# TOWARD DELIVERY: anything that is not a clean leading @-mention run terminated
# by a colon DEFAULTS to inject-to-all. The pre-fix parser read the FIRST colon
# anywhere on an @-leading line as a directive terminator, so a prose line like
# "@maria @Tiberius ... a new directive: I want ..." became a single bogus
# recipient, matched nobody, and the whole broadcast was silently SKIPPED
# (2026-06-02 regression — Rick's AFK directive lost fleet-wide).
_MAX_PERSONA_TOKEN_LEN = 40
# NOTE: '.' is deliberately EXCLUDED — persona names carry it (e.g. "Mr. Radio"),
# and match_persona is punctuation-tolerant. The length cap catches long prose;
# these remaining marks flag short prose ("@ok, sounds good: ...") as non-directive.
_SENTENCE_PUNCT        = ( ",", "!", "?", ";" )


def _contains_reminder_framing( body: str ) -> bool:
    """True if body contains literal `<system-reminder>` or `</system-reminder>` (case-insensitive)."""
    lowered = body.lower()
    return _SYSTEM_REMINDER_OPEN in lowered or _SYSTEM_REMINDER_CLOSE in lowered


def _directive_mentions( stripped: str ) -> Optional[ List[ str ] ]:
    """
    Return the persona-mention tokens of a persona-directive line, or None.

    A persona-directive is a leading PURE run of @-mention tokens terminated by a
    colon: `@a @b @c: message`. Tokens are split on "@" (NOT whitespace) so
    multi-word personas like "mr radio" survive. Anything else → None, so the
    caller treats the line as a default (inject-to-all) — bias toward delivery.

    Requires:
        - `stripped` is a left/right-stripped line

    Ensures:
        - "@a @b: msg"                      → ["a", "b"]
        - "@mr radio: hi"                   → ["mr radio"]
        - "@maria ... a new directive: x"   → None  (a token is prose: too long / sentence punct)
        - "ping foo@bar.com: x"             → None  (does not start with "@")
        - "@x" (no colon)                   → None
        - "@@x:" / "@ @x:"                  → None  (empty mention segment ⇒ malformed)
        - returns None whenever ANY candidate exceeds `_MAX_PERSONA_TOKEN_LEN`
          or contains `_SENTENCE_PUNCT` (treat as prose → DEFAULT delivery)
    """
    if not stripped.startswith( "@" ):
        return None
    colon_idx = stripped.find( ":" )
    if colon_idx == -1:
        return None
    pre        = stripped[ 1:colon_idx ]                       # drop leading "@", take up to first colon
    candidates = [ seg.strip() for seg in pre.split( "@" ) ]   # split on "@" preserves multi-word names
    if any( not c for c in candidates ):                      # empty segment ⇒ malformed mention run
        return None
    for c in candidates:
        if len( c ) > _MAX_PERSONA_TOKEN_LEN:                 # prose, not a persona token
            return None
        if any( punct in c for punct in _SENTENCE_PUNCT ):
            return None
    return candidates


def _parse_body(
    body                : str,
    local_persona_name  : Optional[ str ],
    persona_roster      : Optional[ List[ str ] ] = None,
) -> Tuple[ List[ str ], List[ str ], int ]:
    """
    Split body into (default_lines, matched_directive_lines, non_matching_directive_count).

    A persona-directive is a leading PURE run of @-mention tokens terminated by a
    colon (`@a @b @c: message`) — see `_directive_mentions`. For such a line:
    - any mention is `@all` / `@everyone` (case-insensitive) → treated as default scope
    - when `persona_roster` is supplied and NO mention resembles a roster persona
      (local persona implicitly included), the run is prose, not a directive →
      default line (deliver-to-all)
    - ANY mention matches the local persona (case-insensitive + punctuation-tolerant) → matched_directives
    - none match → ignored silently (counted for skip-detection)

    Every OTHER line — plain text, or prose that merely starts with / contains an
    `@` (colon mid-sentence, an inline email, or no colon) — is a default line
    (inject-to-all). Bias = fail toward delivery, NOT suppression.

    Requires:
        - `persona_roster` is None (roster-blind legacy parse) OR a list of
          persona name strings; an EMPTY list means "the roster is known and
          empty" — the local persona (when present) is still appended, so a
          directive addressed to the local persona itself always matches;
          every OTHER directive run is prose (deliver-to-all)
    """
    default_lines: List[ str ]            = [ ]
    matched_directive_lines: List[ str ]  = [ ]
    non_matching_directive_count          = 0

    known_personas: Optional[ List[ str ] ] = None
    if persona_roster is not None:
        known_personas = list( persona_roster )
        if local_persona_name is not None and local_persona_name not in known_personas:
            known_personas.append( local_persona_name )

    for line in body.splitlines():
        stripped = line.strip()
        mentions = _directive_mentions( stripped )
        if mentions is None:
            # Plain text, OR prose that merely starts with / contains an "@" but is
            # not a clean leading @-mention run + colon → broadcast to everyone.
            # Fail toward delivery (the regression this fixes failed toward suppression).
            default_lines.append( line )
            continue
        # A persona-directive. `@all` / `@everyone` anywhere in the run → default scope.
        if any( m.lower() in _ALL_ALIASES for m in mentions ):
            default_lines.append( line )
            continue
        # Roster-aware discrimination: a run whose mentions resemble NOBODY on the
        # roster is prose (e.g. "@here goes: x"), not a directive to a nonexistent
        # persona — deliver to everyone instead of silently skipping.
        if known_personas is not None and not any( match_persona( m, known_personas ) for m in mentions ):
            default_lines.append( line )
            continue
        # Multi-addressee: the line is for us if ANY mention resolves to the local persona.
        matched = False
        if local_persona_name is not None:
            for m in mentions:
                if match_persona( m, [ local_persona_name ] ) == local_persona_name:
                    matched = True
                    break
        if matched:
            matched_directive_lines.append( line )
        else:
            non_matching_directive_count += 1

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
    persona_roster      : Optional[ List[ str ] ] = None,
) -> Dict[ str, Any ]:
    """
    Process a `action:broadcast_received` notification end-to-end.

    Requires:
        - `notification.payload` is a dict containing `body: str` + `broadcast_id: str`
        - `local_persona` is the bridge's `voice_persona` dict (or None if unallocated)
        - `inject_fn(text)` injects `text` into the local session's tmux (closes over the listener instance)
        - `store` is a `CommonsStore` rooted at `<LUPIN_ROOT>/io/commons`
        - `sender_session_id` is the local session's id
        - `persona_roster` is None OR a list of live persona names for
          roster-aware directive discrimination (see `_parse_body`)

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
    default_lines, matched_directive_lines, _ = _parse_body( body, local_persona_name, persona_roster )

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
