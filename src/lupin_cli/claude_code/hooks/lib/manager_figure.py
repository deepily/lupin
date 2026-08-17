"""
Manager-figure predicate for the task-store write gate (F4 managers-first).

Implements the ratified two-source predicate from planning-is-prompting ->
workflow/manager-autonomy.md §2.1 — a session is a manager-figure iff EITHER:

    1. EXPLICIT — the session was spawned INTO a manager role: its bridge
       file carries role == "manager".
    2. IMPLICIT — the session's allocated voice persona is one of the repo's
       NAMED standing personas: the `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>`
       env chain's named entries (the `*` wildcard is "anything free" — a
       randomly-allocated worker persona, NEVER a manager claim).

Resolution reuses the existing chain machinery
(`cosa.rest.voice_persona_helpers.pick_persona_chain_from_env` +
`parse_persona_chain`) and the one canonical identity normalizer
(`lupin_mcp.persona_normalization.canonical_persona_key`, so "Mr. Radio" ==
"mr radio") — no duplicated parser, one name at every layer. The declared
chain entries are display form ("Mr. Radio,Tiberius,*") so the keep-spaces
canonical key matches the persona's "mr radio" bridge name; the swap from the
space-dropping match-key is symmetric on both compare sides (equivalence
preserved) and now agrees with the store key.

**Degrade direction: fail-CLOSED (False).** F4 is managers-first WRITES — a
session whose manager-hood cannot be established does NOT write to the store.
This is the opposite degrade direction from the read-side oracle helpers
(which fail-open) because the guarded action here is a WRITE.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md §1.2.
"""

from cosa.rest.voice_persona_helpers import pick_persona_chain_from_env, parse_persona_chain, PERSONA_CHAIN_WILDCARD
from lupin_mcp.persona_normalization import canonical_persona_key
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    find_session_path_by_id, resolve_project_name, MANAGER_FIGURE_BRIDGE_FIELD
)


MANAGER_ROLE = "manager"


def _read_bridge_fields( session_id, _find_path=find_session_path_by_id ):
    """
    Read ( role, persona_name, implicit_flag ) from the session's bridge file.

    `implicit_flag` is the IMPLICIT manager-figure answer stamped at registration
    (MANAGER_FIGURE_BRIDGE_FIELD, bug e5d600bd) — a bool on post-fix bridges,
    None on legacy bridges written before the fix (or when the field is absent).

    Requires:
        - session_id is a string (full UUID or 8-char prefix)
        - _find_path is the bridge locator (injectable for tests)

    Ensures:
        - Returns ( role_or_None, persona_name_or_None, implicit_flag_or_None )
        - Missing bridge / parse error / missing fields → ( None, None, None ) or
          partial — DEGRADE-SAFE, never raises
    """
    import json

    try:
        path = _find_path( session_id )
        if not path:
            return None, None, None
        with open( path ) as f:
            data = json.load( f )
        role    = data.get( "role" )
        persona = data.get( "voice_persona" )
        name    = persona.get( "name" ) if isinstance( persona, dict ) else None
        flag    = data.get( MANAGER_FIGURE_BRIDGE_FIELD )
        return role, name, flag
    except Exception:
        return None, None, None


def resolve_implicit_manager_figure( persona_name, environ=None ) -> bool:
    """
    Compute the IMPLICIT source of the §2.1 predicate: is `persona_name` one of
    the repo's NAMED standing personas (a named entry of
    COSA_VOICE_PREFERRED_PERSONA__<PROJECT>, the `*` wildcard excluded)?

    🔴 THIS RUNS ONLY WHERE THE CALLER'S REAL ENV LIVES. register_session (the
    SessionStart hook) calls it with `os.environ` after persona allocation and
    STAMPS the result onto the bridge (bug e5d600bd, Rick's Option A). The
    server has no COSA_VOICE_PREFERRED_PERSONA__* vars, so it must NOT re-derive
    this — it reads the stamped bool via is_manager_figure() instead. This
    function is also the env-based fallback is_manager_figure() uses for legacy
    (un-stamped) bridges when a caller supplies its own environ.

    Requires:
        - persona_name is a string or None
        - environ is a Mapping or None (None → os.environ, via the resolvers)

    Ensures:
        - Returns True iff a NAMED chain entry canonically matches persona_name
        - Returns False for no persona, unset chain, `*`-only chain, or no match
        - Never raises
    """
    try:
        if not persona_name:
            return False
        chain_raw = pick_persona_chain_from_env( resolve_project_name( environ ), environ=environ )
        named     = [ e for e in parse_persona_chain( chain_raw ) if e != PERSONA_CHAIN_WILDCARD ]
        target    = canonical_persona_key( persona_name )
        return any( canonical_persona_key( e ) == target for e in named )
    except Exception:
        return False


def is_manager_figure( session_id, environ=None, _find_path=find_session_path_by_id ) -> bool:
    """
    Is this session a manager-figure (the §2.1 two-source predicate)?

    Requires:
        - session_id is a string (full UUID or 8-char prefix)
        - environ is a Mapping or None (None → os.environ)
        - _find_path is the bridge locator (injectable for tests)

    Ensures:
        - Returns True iff bridge role == "manager" (EXPLICIT source, checked
          live), OR the IMPLICIT source is satisfied. The implicit source is
          read from the STATIC bridge field stamped at registration
          (MANAGER_FIGURE_BRIDGE_FIELD, bug e5d600bd) — this is what makes the
          predicate correct SERVER-SIDE, where the persona-chain env is empty and
          re-deriving the implicit source would fail closed for every caller
          (the 403 write gate AND any v2-experiment stratum classifier alike).
        - Legacy fallback: on a bridge written before this fix (field absent), the
          implicit source is computed from `environ` via
          resolve_implicit_manager_figure — correct when a hook-side caller
          passes its own env, fail-CLOSED server-side (unchanged pre-fix
          behavior). A legacy bridge self-heals on its next SessionStart.
        - Returns False on ANY doubt — fail-CLOSED, this gates WRITES (F4)
        - Never raises (both helpers below are no-raise, so no outer belt is
          needed here; adding one would be an uncoverable dead branch)
    """
    role, persona_name, implicit_flag = _read_bridge_fields( session_id, _find_path=_find_path )

    if role == MANAGER_ROLE:
        return True

    # Post-fix bridges carry the stamped implicit answer — trust it. This is
    # the load-bearing branch server-side (no caller env to re-derive from).
    if implicit_flag is not None:
        return bool( implicit_flag )

    # Legacy (un-stamped) bridge: fall back to the env-based compute.
    return resolve_implicit_manager_figure( persona_name, environ )


# Denial reasons for the blocked-mint 403 message (bug dd3b3666). These let the
# caller-facing message distinguish "resolved and NOT a manager" (working as
# designed) from "nothing resolved — the stamp field the predicate reads is
# ABSENT" (a schema-vintage fact, self-healed by a session restart). The old
# single message asserted the first for BOTH, misdiagnosing every session alive
# across a future bridge-schema addition.
DENIAL_NO_SESSION_ID = "no_session_id"
DENIAL_STALE_BRIDGE  = "stale_bridge"
DENIAL_DENIED        = "denied"


def classify_manager_figure_denial( session_id, environ=None, _find_path=find_session_path_by_id ) -> str:
    """
    Classify WHY manager-hood was NOT established, for a caller-facing message.

    Call ONLY on the reject path — i.e. after is_manager_figure() returned False
    or session_id resolved to None. This is a message-shaping helper, NOT a second
    permission predicate: is_manager_figure remains the single gate.

    The absent-vs-false distinction (the whole point of dd3b3666): the implicit
    stamp is a bool on post-fix bridges and ABSENT (→ None via data.get) on
    bridges written before the field existed. `flag is None` is therefore the
    reliable "stale bridge" signal, distinct from `flag is False` ("denied").

    Requires:
        - session_id is a string (full UUID or 8-char prefix) or None
        - _find_path is the bridge locator (injectable for tests)

    Ensures:
        - Returns DENIAL_NO_SESSION_ID when session_id is None (no parseable id).
        - Returns DENIAL_STALE_BRIDGE when the implicit stamp field is ABSENT on
          the bridge (field never written) — remedy is a session RESTART, which
          re-stamps it at SessionStart. Also covers a missing/unreadable bridge.
        - Returns DENIAL_DENIED when the stamp resolved present-and-False (the
          caller is genuinely not a manager figure).
        - Never raises (_read_bridge_fields is no-raise).
    """
    if session_id is None:
        return DENIAL_NO_SESSION_ID
    role, _persona_name, implicit_flag = _read_bridge_fields( session_id, _find_path=_find_path )
    # Defensive: a live role=="manager" would have returned True upstream; if we
    # are on the reject path anyway, treat it as denied rather than stale.
    if role == MANAGER_ROLE:
        return DENIAL_DENIED
    # ABSENT stamp (None) → stale/legacy bridge; PRESENT-and-False → genuine deny.
    if implicit_flag is None:
        return DENIAL_STALE_BRIDGE
    return DENIAL_DENIED
