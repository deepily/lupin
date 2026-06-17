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
`parse_persona_chain`) and the existing punctuation-tolerant normalizer
(`lupin_mcp.commons_persona_matcher._normalize_for_match`, so "Mr. Radio" ==
"mr radio") — no duplicated parser, one name at every layer.

**Degrade direction: fail-CLOSED (False).** F4 is managers-first WRITES — a
session whose manager-hood cannot be established does NOT write to the store.
This is the opposite degrade direction from the read-side oracle helpers
(which fail-open) because the guarded action here is a WRITE.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md §1.2.
"""

from cosa.rest.voice_persona_helpers import pick_persona_chain_from_env, parse_persona_chain, PERSONA_CHAIN_WILDCARD
from lupin_mcp.commons_persona_matcher import _normalize_for_match
from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_path_by_id, resolve_project_name


MANAGER_ROLE = "manager"


def _read_bridge_fields( session_id, _find_path=find_session_path_by_id ):
    """
    Read ( role, persona_name ) from the session's bridge file.

    Requires:
        - session_id is a string (full UUID or 8-char prefix)
        - _find_path is the bridge locator (injectable for tests)

    Ensures:
        - Returns ( role_or_None, persona_name_or_None )
        - Missing bridge / parse error / missing fields → ( None, None ) or
          partial — DEGRADE-SAFE, never raises
    """
    import json

    try:
        path = _find_path( session_id )
        if not path:
            return None, None
        with open( path ) as f:
            data = json.load( f )
        role    = data.get( "role" )
        persona = data.get( "voice_persona" )
        name    = persona.get( "name" ) if isinstance( persona, dict ) else None
        return role, name
    except Exception:
        return None, None


def is_manager_figure( session_id, environ=None, _find_path=find_session_path_by_id ) -> bool:
    """
    Is this session a manager-figure (the §2.1 two-source predicate)?

    Requires:
        - session_id is a string (full UUID or 8-char prefix)
        - environ is a Mapping or None (None → os.environ)
        - _find_path is the bridge locator (injectable for tests)

    Ensures:
        - Returns True iff bridge role == "manager" (explicit source), OR the
          bridge voice_persona.name matches (punctuation-/case-insensitively)
          a NAMED entry of COSA_VOICE_PREFERRED_PERSONA__<PROJECT> (implicit
          source; the `*` wildcard entry is excluded)
        - Returns False on ANY doubt: missing bridge, no persona, unset env
          chain, no match — fail-CLOSED, this gates WRITES (F4)
        - Never raises
    """
    try:
        role, persona_name = _read_bridge_fields( session_id, _find_path=_find_path )

        if role == MANAGER_ROLE:
            return True

        if not persona_name:
            return False

        chain_raw = pick_persona_chain_from_env( resolve_project_name( environ ), environ=environ )
        named     = [ e for e in parse_persona_chain( chain_raw ) if e != PERSONA_CHAIN_WILDCARD ]
        target    = _normalize_for_match( persona_name )
        return any( _normalize_for_match( e ) == target for e in named )
    except Exception:
        return False
