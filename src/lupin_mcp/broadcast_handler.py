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

**Prose-contaminated mentions** (2026-07-18 fix — bug ddd98ff2, parent 841b3d21).
`_directive_mentions` splits on "@" and terminates at the FIRST colon ANYWHERE on
the line, so prose following a second @-name is SWALLOWED INTO THAT NAME's token.
Measured twice on two nights: "@maria @mr radio it is Maria's contention that: ..."
yielded the token "mr radio it is Maria's contention that" (38 chars — UNDER
`_MAX_PERSONA_TOKEN_LEN`), which resolved to nobody, so the line reached `maria`
ALONE and was SILENTLY DROPPED for the man it names. `_prose_contaminated_mention`
demotes such a run to a default line (delivered to all), restoring this module's
stated bias toward delivery.

⚠️ THE DEFECT IS ORIGINAL, NOT A REGRESSION FROM MULTI-ADDRESSEE. The spec-era
parser (26898e1e, 2026-05-29) delivered the same lines to NOBODY (0/7); the @-split
and `_MAX_PERSONA_TOKEN_LEN` took it 0/7 -> 1/7. They MITIGATED, never fixed. The
40-char guard is a FILTER WITH AN UNTESTED BAND BENEATH IT: `_RICK_AFK_BROADCAST`
line 1 is the same defect in LONG form (>40 chars + commas) and has been pinned
since June, while the SHORT form went untested for six weeks.

⚠️⚠️ TWO KNOWN RESIDUALS — DISCLOSED, NOT FIXED. Both are ANNOUNCED rather than
silent, and that is the ONLY reason they are tolerable:

  1. PROSE PRECEDING A NAME still routes rather than broadcasts.
     "@Attention all hands @Maria: sync" is structurally IDENTICAL to
     "@bogus @Maria: sync" — an unresolvable segment beside a resolving one,
     differing only in word count. NO PREDICATE SEPARATES THEM (measured). This fix
     covers prose glued AFTER a resolving name; prose that PRECEDES one is
     indistinguishable from a typo'd or offline addressee and is treated as one.
     The sender IS told which token matched nobody (`unresolved_mention` diagnostic
     + the ack `body_summary`), so the mis-route is VISIBLE, never silent.

  2. `persona_roster=None` (roster-blind legacy path) IS UNFIXED AND UNMEASURED.
     Both roster gates are conditioned on `known_personas is not None`, so under
     `None` the contamination check is SKIPPED ENTIRELY and the original defect
     survives intact. Pinned as an assertion by
     `test_fix_scope_all_three_roster_states`. Whether the live roster scan ever
     returns empty in production HAS NOT BEEN MEASURED; ruled 2026-07-18 to disclose
     rather than fix blind. The same applies to the `@all` alias under `None`.

ACK STATUS IS PART OF A DEDUPE KEY — property recorded, not a known bug.
`_dedupe_broadcast_acks_by_recipient` (`cosa/rest/routers/commons.py:640`) keys on
`(broadcast_id, sender_session_id, status)`. It does NOT compare status to a literal,
so the `completed-with-withheld` value added 2026-07-18 is safe. CONSEQUENCE: because
status is IN the key, a recipient that emitted BOTH `completed` and
`completed-with-withheld` for one broadcast would yield TWO rows rather than one
collapsed row. Not reachable as far as two reviewers could determine — the count and
the status derive from the same parse of the same body — but recorded because an
unrecorded property is how the next reader gets surprised. (Found by Rachel 48b59a71;
Rio's original consumer check was scoped to one file when the risk was repo-wide.)

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


def _prose_contaminated_mention(
    candidate       : str,
    known_personas  : List[ str ],
) -> Optional[ str ]:
    """
    Return the roster persona a candidate STARTS WITH when prose is glued to it, else None.

    THE MEASURED DEFECT (bug ddd98ff2, parent 841b3d21, 2026-07-18). `_directive_mentions`
    splits on "@" and terminates at the FIRST colon anywhere on the line, so prose that
    follows a second @-name is SWALLOWED INTO THAT NAME's token:

        "@maria @mr radio it is Maria's contention that: ..."
            -> [ "maria", "mr radio it is Maria's contention that" ]

    The swallowed token is 38 chars — under `_MAX_PERSONA_TOKEN_LEN` — so it is accepted as
    a persona name, resolves to NOBODY, and the line is delivered to `maria` alone and
    SILENTLY DROPPED for everyone else INCLUDING THE MAN IT NAMES. Witnessed twice on two
    nights (broadcast 2159408c; and "@Tiberius @mr radio Attention: ..." which reached
    Tiberius only). The threshold polarity is INVERTED: a LONGER prose tail exceeds the cap,
    is read as prose, and delivers correctly.

    This predicate is DELIBERATELY NARROW. It distinguishes the measured defect from an
    UNKNOWN-ADDRESSEE run, which is existing intended behavior and must not change:

        "bogus"                                   -> None  (no roster prefix; typo/offline
                                                     addressee — stays a directive, per
                                                     test_parse_body_roster_mixed_bogus_and_
                                                     real_mention_stays_directive)
        "mr radio it is Maria's contention that"  -> "Mr. Radio"  (real persona + prose)
        "mr radio Attention"                      -> "Mr. Radio"  (real persona + prose)

    A token that resolves WHOLE is a clean mention and is never contaminated.

    Requires:
        - `candidate` is a stripped @-split mention segment
        - `known_personas` is a non-empty list of roster persona names

    Ensures:
        - returns None when `candidate` resolves whole (clean mention)
        - returns None when NO word-boundary prefix of `candidate` resolves (unknown addressee)
        - otherwise returns the canonical roster name of the LONGEST resolving prefix
    """
    if not candidate or not known_personas:
        return None
    if match_persona( candidate, known_personas ):
        return None                                        # clean whole-token mention
    words = candidate.split()
    # Longest prefix first: "mr radio it" before "mr radio" before "mr", so a two-word
    # persona is preferred over a one-word roster entry that merely shares its first word.
    for cut in range( len( words ) - 1, 0, -1 ):
        resolved = match_persona( " ".join( words[ :cut ] ), known_personas )
        if resolved:
            return resolved
    return None


def _parse_body(
    body                : str,
    local_persona_name  : Optional[ str ],
    persona_roster      : Optional[ List[ str ] ] = None,
    diagnostics         : Optional[ List[ Dict[ str, Any ] ] ] = None,
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
        # PROSE-CONTAMINATION GATE (bug ddd98ff2 / parent 841b3d21, 2026-07-18).
        # A mention token that STARTS WITH a real roster persona and then continues
        # into prose was never a directive — `find(":")` grabbed a colon further down
        # the line and the span in between was ASSUMED to be a name without ever being
        # checked. That assumption is the defect, and it is ORIGINAL: the spec-era
        # parser (26898e1e, 2026-05-29) had it too and delivered these lines to NOBODY
        # (0/7); the @-split and `_MAX_PERSONA_TOKEN_LEN` are later MITIGATIONS of it
        # (0/7 -> 1/7), not its cause. Restores this module's own stated contract:
        # "Bias = fail toward delivery, NOT suppression."
        #
        # DELIBERATELY NARROW — it does NOT touch an UNKNOWN-ADDRESSEE run. "@bogus
        # @Maria: sync" keeps routing to Maria alone (a typo'd or offline addressee is
        # a different animal from prose glued to a live name), per the existing
        # deliberate test `test_parse_body_roster_mixed_bogus_and_real_mention_stays_
        # directive`. Whether THAT case should also fan out is an OPEN DECISION for the
        # Steward — collapsing the two is a one-line change here, not a rewrite.
        if known_personas is not None:
            contaminated = [
                ( m, _prose_contaminated_mention( m, known_personas ) ) for m in mentions
            ]
            contaminated = [ ( m, p ) for m, p in contaminated if p is not None ]
            if contaminated:
                default_lines.append( line )
                if diagnostics is not None:
                    diagnostics.append( {
                        "kind"      : "prose_contaminated_mention",
                        "line"      : line,
                        "mentions"  : [ m for m, _ in contaminated ],
                        "personas"  : [ p for _, p in contaminated ],
                    } )
                continue

        # Roster-aware discrimination: a run whose mentions resemble NOBODY on the
        # roster is prose (e.g. "@here goes: x"), not a directive to a nonexistent
        # persona — deliver to everyone instead of silently skipping.
        if known_personas is not None and not any( match_persona( m, known_personas ) for m in mentions ):
            default_lines.append( line )
            continue
        # RESIDUAL DISCLOSURE, ANNOUNCED (2026-07-18). This run IS being treated as a
        # directive, but one or more of its @-tokens resolve to NOBODY live. Two shapes
        # reach here and NO PREDICATE SEPARATES THEM (Rachel, measured; ruled a
        # disclosure rather than a blocker by the Steward):
        #   "@bogus @Maria: sync"                -> a typo'd or OFFLINE addressee
        #   "@Attention all hands @Maria: sync"  -> PROSE PRECEDING a real name
        # Prose glued AFTER a resolving name is caught by the contamination gate above;
        # prose PRECEDING one is indistinguishable from a typo and is treated as one.
        # The tolerance is only defensible because it is ANNOUNCED — the sender is told
        # which token matched nobody, so a mis-route is visible in seconds rather than
        # inferred after two nights. Announced beats deleted; UNDISCLOSED beats nothing.
        if known_personas is not None and diagnostics is not None:
            unresolved_here = [ m for m in mentions if not match_persona( m, known_personas ) ]
            if unresolved_here:
                diagnostics.append( {
                    "kind"     : "unresolved_mention",
                    "line"     : line,
                    "mentions" : unresolved_here,
                } )

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
            # WITHHELD: addressed to a live persona that is not us. This is CORRECT
            # targeting, but until 2026-07-18 it was also SILENT — the drop was counted
            # here and surfaced to nobody, which is what let a two-name directive reach
            # one name for two nights while reporting success. Record it so the ack and
            # the recipient footer can say so.
            non_matching_directive_count += 1
            if diagnostics is not None:
                diagnostics.append( {
                    "kind"     : "withheld_directive",
                    "line"     : line,
                    "mentions" : mentions,
                } )

    return ( default_lines, matched_directive_lines, non_matching_directive_count )


def _build_reminder(
    broadcast_id    : str,
    effective_body  : str,
    withheld_count  : int = 0,
) -> str:
    """
    Wrap `effective_body` in a `<system-reminder>` block with broadcast_id header.

    When `withheld_count` > 0 the wrapper carries an EXPLICIT divergence notice. The
    recipient is told that what they are reading is NOT the whole broadcast — the
    single fact that was unavailable to every seat before 2026-07-18, and the reason
    a gate could be built on "I would have seen it." A recipient who knows a line was
    withheld can ask; one who believes they received the whole thing cannot.

    Requires:
        - `withheld_count` is a non-negative int

    Ensures:
        - withheld_count == 0 → byte-identical to the pre-2026-07-18 wrapper
        - withheld_count  > 0 → a divergence notice precedes the closing tag
    """
    notice = ""
    if withheld_count > 0:
        plural = "line" if withheld_count == 1 else "lines"
        notice = (
            f"\n\n[DIVERGENCE NOTICE: {withheld_count} {plural} of this broadcast "
            f"{'was' if withheld_count == 1 else 'were'} addressed to other personas and "
            f"{'is' if withheld_count == 1 else 'are'} NOT shown above. YOU DID NOT RECEIVE "
            f"THE WHOLE BROADCAST. Other recipients received text you did not.]"
        )
    return (
        f"{_SYSTEM_REMINDER_OPEN}\n"
        f"USER BROADCAST (broadcast_id {broadcast_id}):\n\n"
        f"{effective_body}{notice}\n"
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
    diagnostics: List[ Dict[ str, Any ] ] = [ ]
    default_lines, matched_directive_lines, withheld_count = _parse_body(
        body, local_persona_name, persona_roster, diagnostics
    )

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
    reminder = _build_reminder( broadcast_id, effective_body, withheld_count )
    inject_fn( reminder )

    # LOUD-BY-DEFAULT (2026-07-18). Previously this ack said "completed" whether the
    # session received the whole broadcast or a slice of it, so a send that reached one
    # of two recipients was INDISTINGUISHABLE from one that reached both. The sender had
    # no signal at all. Now the ack carries what was withheld and what failed to resolve,
    # and the status itself changes so a reader scanning `broadcast-acks` cannot skim past
    # it. A drop that reports success is the defect; a drop that announces itself is a
    # nuisance. The unresolved-mention entry is the high-value one: it names the exact
    # @-token that did not correspond to any live persona, which is the signature of the
    # original bug and would have surfaced it in seconds rather than two nights.
    unresolved = [
        d for d in diagnostics
        if d[ "kind" ] in ( "prose_contaminated_mention", "unresolved_mention" )
    ]
    status     = "completed-with-withheld" if ( withheld_count or unresolved ) else "completed"

    summary = effective_body if len( effective_body ) <= 200 else effective_body[ :197 ] + "..."
    if withheld_count:
        summary = f"[{withheld_count} line(s) withheld from this persona] {summary}"
    if unresolved:
        tokens  = "; ".join( f"@{m}" for d in unresolved for m in d[ "mentions" ] )
        summary = (
            f"[UNRESOLVED @-MENTION(S) — delivered to ALL as prose: {tokens}] {summary}"
        )

    ack = _post_ack(
        store             = store,
        broadcast_id      = broadcast_id,
        status            = status,
        body_summary      = summary,
        sender_session_id = sender_session_id,
        local_persona     = local_persona,
    )
    return {
        "status"          : status,
        "broadcast_id"    : broadcast_id,
        "ack_entry"       : ack,
        "withheld_count"  : withheld_count,
        "diagnostics"     : diagnostics,
    }
