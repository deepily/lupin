"""
Pure-function helpers for per-session voice persona allocation.

This module composes (a) ConfigurationManager reads of the [Voice Personas]
INI block and (b) bridge-file scans from session_bridge.find_active_voice_persona_sessions
into the higher-level allocation primitives used by the voice_persona router:

    - load_persona_pool_from_config()  → list of persona dicts (Sam excluded)
    - pick_unallocated_persona()       → uniform random draw, falls back to borrow
    - borrowed_persona_for_sid()       → deterministic hash-modulo fallback
    - allocate_persona_for_session()   → end-to-end composition (config → scan → pick → return)

The router holds the asyncio.Lock; this module is purely functional and
synchronous. The bridge file is the single source of truth — no in-memory
registry, no separate sweeper. Pool occupancy is freshly computed per call by
scanning live-PID bridge files.

Sam is intentionally NOT in the pool. He is the system-wide TTS default
voice (see `elevenlabs tts default voice id` in lupin-app.ini), used by the
speech router for any request lacking a voice_id. Treat him as permanently
allocated to the server itself.

See: src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md
"""

import hashlib
import json
import os
import random
from datetime  import datetime, timezone
from typing    import List, Optional, Set, Dict, Any

# Shared persona-name normalizer ("Mr. Radio"/"mr radio"/"MR.RADIO" → "mrradio").
# Travelled here WITH pick_declared_managers_from_env (relocated from
# manager_resolver 2026-06-11); import-time-safe — commons_persona_matcher
# pulls only re+typing, and cosa→lupin_mcp imports are precedented
# (e.g. cosa/rest/routers/commons.py).
from lupin_mcp.persona_normalization import canonical_persona_key


PoolPersona = Dict[ str, Any ]


# Title tokens that take a trailing period in display form ("mr" → "Mr.").
# Per project key convention, pool names are stored lowercase with no
# punctuation; this set maps the lowercase honorific tokens back to their
# display form when the persona name is rendered in the UI badge, tooltip,
# or any other user-facing surface.
_HONORIFIC_TOKENS = { "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st" }

# Display-form overrides keyed by the lowercase pool key. Used for personas
# whose display name carries diacritics or punctuation that the INI key
# convention strips ("maria" → "María"). Looked up BEFORE the generic
# title-case path so a single override entry is enough to override the
# whole-string rendering.
_DISPLAY_OVERRIDES = {
    "maria" : "María",
    "chloe" : "Chloé",
}


def display_name_for( pool_name: str ) -> str:
    """
    Convert pool key form (lowercase, no punctuation) to display form.

    Pool names are stored lowercase with no punctuation per project convention
    so that they double as ConfigParser-safe key fragments. Anywhere the name
    is shown to the user — badge label, tooltip, debug print — call this
    helper to produce the proper-noun display string.

    Requires:
        - pool_name is a string (may be empty, may already be capitalized)

    Ensures:
        - Returns "" when pool_name is empty or None
        - Whole-string overrides in _DISPLAY_OVERRIDES (matched on lowercase)
          win over the per-token rendering — used for diacritics/punctuation
          the INI key form cannot carry ("maria" → "María")
        - Honorific tokens (mr, mrs, ms, dr, prof, sr, jr, st) become
          "Mr.", "Dr.", etc. with a trailing period
        - Non-honorific tokens are .capitalize()-d (first letter upper, rest
          lower); already-capitalized inputs round-trip unchanged
        - Whitespace between tokens is collapsed to a single space

    Examples:
        "mr radio" → "Mr. Radio"
        "maria"    → "María"
        "rachel"   → "Rachel"
        "dr who"   → "Dr. Who"
    """
    if not pool_name:
        return ""
    override = _DISPLAY_OVERRIDES.get( pool_name.lower() )
    if override is not None:
        return override
    out = []
    for tok in pool_name.split():
        low = tok.lower()
        if low in _HONORIFIC_TOKENS:
            out.append( low.capitalize() + "." )
        else:
            out.append( tok.capitalize() )
    return " ".join( out )


def load_persona_pool_from_config( config_mgr ) -> List[ PoolPersona ]:
    """
    Read the [Voice Personas] INI block and return the allocatable pool.

    Reads `cc session voice persona pool` (comma-separated names) and for each
    name reads the four required keys: voice id, icon, color, profile.

    Requires:
        - config_mgr is an initialized ConfigurationManager instance

    Ensures:
        - Returns a list of persona dicts in the order specified by the pool key
        - Each dict has keys: name, display_name, voice_id, icon, color, profile
        - `name` is the lowercase no-punctuation key form; `display_name` is
          the proper-noun rendering for UI surfaces (see display_name_for)
        - Personas with missing or empty voice_id are skipped (logged via
          ConfigurationManager's silent=False default)
        - Returns an empty list if the pool key is missing or empty
        - Never raises on a single bad entry — skips it and continues

    Args:
        config_mgr: ConfigurationManager (already constructed by caller)

    Returns:
        list[dict]: Allocatable pool, ordered as in INI
    """
    pool_csv = config_mgr.get( "cc session voice persona pool", default="", silent=True )
    if not pool_csv:
        return []

    names = [ n.strip() for n in pool_csv.split( "," ) if n.strip() ]
    pool  = []

    for name in names:
        prefix   = f"cc session voice persona {name}"
        voice_id = config_mgr.get( f"{prefix} voice id", default="", silent=True )
        icon     = config_mgr.get( f"{prefix} icon",     default="🎙️", silent=True )
        color    = config_mgr.get( f"{prefix} color",    default="#888888", silent=True )
        profile  = config_mgr.get( f"{prefix} profile",  default="", silent=True )

        if not voice_id:
            # Pool entry has no voice_id — skip silently rather than poison allocation
            continue

        pool.append( {
            "name"         : name,
            "display_name" : display_name_for( name ),
            "voice_id"     : voice_id,
            "icon"         : icon,
            "color"        : color,
            "profile"      : profile
        } )

    return pool


def load_overflow_persona_from_config( config_mgr ) -> Optional[ PoolPersona ]:
    """
    Read the pool-exhaustion overflow persona from config.

    The overflow persona is allocated when every member of the main pool is
    occupied, so a new session doesn't have to hash-borrow another live
    session's voice. Multiple sessions may legitimately receive the overflow
    persona (multi-overflow is permitted; multi-pool-member is not).

    Generalized 2026-05-19 from the prior Sam-hardcoded loader: reads a new
    `cc session voice persona overflow name` INI key (default "sam" for
    backward compat) and looks up that persona's pool-style INI keys. Any
    persona with `cc session voice persona <name> {voice id, icon, color,
    profile}` keys can act as the overflow — config-driven, no code change
    required to rotate which persona occupies the overflow slot.

    Backward compat: when overflow_name resolves to "sam" AND no explicit
    `cc session voice persona sam voice id` key is present, falls back to
    sourcing voice_id from `elevenlabs tts default voice id` (the legacy
    non-explicit path that predated 2026-05-19 — Sam historically had no
    pool-style voice_id key because his identity was conflated with the
    system TTS default).

    Requires:
        - config_mgr is an initialized ConfigurationManager instance

    Ensures:
        - Returns a persona dict with keys: name (lowercase form of the
          configured overflow_name), display_name, voice_id, icon, color,
          profile, overflow=True
        - Returns None when the configured overflow persona has no resolvable
          voice_id (in which case pick_unallocated_persona falls back to the
          legacy hash-borrow path)
        - Returns None when `cc session voice persona overflow name` is
          explicitly set to empty/whitespace (disabling the overflow slot)
        - Never raises — missing icon/color/profile/display_name keys fall
          back to documented defaults

    Args:
        config_mgr: ConfigurationManager (already constructed by caller)

    Returns:
        dict or None: Overflow persona dict, or None if unresolvable

    See: src/rnd/v0.1.7/2026.05.16-voice-persona-stale-bridge-and-sam-overflow.md
         (original Sam-as-overflow design) and the 2026-05-19 generalization.
    """
    overflow_name = config_mgr.get( "cc session voice persona overflow name", default="sam", silent=True )
    if not overflow_name or not overflow_name.strip():
        return None
    name_for_lookup = overflow_name.strip()
    name_lower      = name_for_lookup.lower()

    voice_id = config_mgr.get(
        f"cc session voice persona {name_for_lookup} voice id",
        default="", silent=True
    )
    if not voice_id and name_lower == "sam":
        # Backward compat: Sam's voice_id historically read from the system
        # TTS default rather than an explicit per-persona key. Preserved so
        # legacy configs without `cc session voice persona sam voice id`
        # continue to load Sam-as-overflow byte-clean.
        voice_id = config_mgr.get( "elevenlabs tts default voice id", default="", silent=True )
    if not voice_id:
        return None

    return {
        "name"         : name_lower,
        "display_name" : config_mgr.get(
            f"cc session voice persona {name_for_lookup} display name",
            default=display_name_for( name_lower ),
            silent=True
        ),
        "voice_id"     : voice_id,
        "icon"         : config_mgr.get( f"cc session voice persona {name_for_lookup} icon",    default="🎙️",                              silent=True ),
        "color"        : config_mgr.get( f"cc session voice persona {name_for_lookup} color",   default="#00BCD4",                          silent=True ),
        "profile"      : config_mgr.get( f"cc session voice persona {name_for_lookup} profile", default="System default voice (overflow)", silent=True ),
        "overflow"     : True
    }


def _lowest_free_extra_n( occupied_names: Set[ str ] ) -> int:
    """
    Smallest N ≥ 1 such that "extra N" is not in occupied_names.

    Used by the Arnold-first→Extra-N overflow path: once the configured
    overflow persona ("arnold") is itself occupied, additional concurrent
    overflow sessions get a numbered "Extra N" identity. The number is derived
    statelessly from the live occupancy set (which is freshly computed from
    bridge files per allocation), so a dead Extra session frees its number for
    re-use on the next allocation — gaps are reused rather than skipped.

    Requires:
        - occupied_names is a set of name strings (may be empty)

    Ensures:
        - Returns the smallest integer N ≥ 1 for which f"extra {N}" is absent
          from occupied_names
        - Returns 1 when no "extra K" names are occupied
        - Reuses gaps: occupied={"extra 2"} → returns 1 (not 3)
        - Never raises

    Args:
        occupied_names: Names currently allocated to live sessions (pool members,
            "arnold", and any "extra K" already in use)

    Returns:
        int: Lowest free Extra index ≥ 1
    """
    n = 1
    while f"extra {n}" in occupied_names:
        n += 1
    return n


def _make_extra_persona(
    base_overflow: PoolPersona,
    n            : int,
    extra_colors : Optional[ List[ str ] ] = None
) -> PoolPersona:
    """
    Build a uniquified "Extra N" overflow persona from the base overflow persona.

    Extras share the base overflow persona's voice_id and icon (so they all
    speak in Arnold's voice and carry his 🪨 badge) but carry a distinct name,
    display_name, and color so they are visually distinguishable in the chorus
    UI. The number lives in the display_name ("Extra 1"); the icon is reused.

    Honest limitation: Extras disambiguate the EYE, not the EAR — every Extra
    speaks in the base overflow voice. Distinct voices require widening the
    named pool with real ElevenLabs voices, which is tracked separately.

    Requires:
        - base_overflow is a persona dict with at least voice_id, icon, color
        - n is an integer ≥ 1
        - extra_colors is a list of CSS hex strings or None/empty

    Ensures:
        - Returns a fresh dict with keys: name ("extra {n}"), display_name
          ("Extra {n}"), voice_id, icon, color, overflow=True, borrowed=False
        - color is extra_colors[ (n-1) % len(extra_colors) ] when the palette is
          non-empty, else falls back to base_overflow["color"]
        - Never aliases base_overflow (returns an independent dict)
        - Never raises on valid inputs

    Args:
        base_overflow: The configured overflow persona (Arnold) — voice/icon source
        n: The Extra index (1-based)
        extra_colors: Green-rule-compliant palette, cycled by (n-1) % len

    Returns:
        dict: The Extra-N persona
    """
    name = f"extra {n}"

    if extra_colors:
        color = extra_colors[ ( n - 1 ) % len( extra_colors ) ]
    else:
        color = base_overflow[ "color" ]

    return {
        "name"         : name,
        "display_name" : display_name_for( name ),
        "voice_id"     : base_overflow[ "voice_id" ],
        "icon"         : base_overflow[ "icon" ],
        "color"        : color,
        "overflow"     : True,
        "borrowed"     : False
    }


def borrowed_persona_for_sid(
    pool             : List[ PoolPersona ],
    stable_session_id: str
) -> Optional[ PoolPersona ]:
    """
    Deterministic hash-modulo persona pick for the pool-exhausted case.

    When all personas are allocated to live sessions, fall back to a
    deterministic borrowed slot keyed on stable_session_id. Determinism
    means the same session always borrows the same voice across server
    restarts and across pool-exhaustion events.

    Uses sha256 (not Python's built-in hash()) because the latter is
    non-deterministic across processes by default (PYTHONHASHSEED).

    Requires:
        - pool is a non-empty list
        - stable_session_id is a non-empty string

    Ensures:
        - Returns a NEW dict with keys: name, voice_id, icon, color, profile, borrowed=True
        - Never raises on valid inputs
        - Returns None when pool is empty or stable_session_id is empty

    Args:
        pool: The full pool (NOT pool minus occupied — borrowing intentionally
            reuses an in-use voice)
        stable_session_id: Session id used as deterministic seed

    Returns:
        dict or None: Borrowed persona with borrowed=True, or None if invalid input
    """
    if not pool or not stable_session_id:
        return None

    digest_bytes = hashlib.sha256( stable_session_id.encode( "utf-8" ) ).digest()
    idx          = int.from_bytes( digest_bytes[:8], "big" ) % len( pool )
    base         = pool[ idx ]

    return {
        "name"         : base[ "name" ],
        "display_name" : base.get( "display_name" ) or display_name_for( base[ "name" ] ),
        "voice_id"     : base[ "voice_id" ],
        "icon"         : base[ "icon" ],
        "color"        : base[ "color" ],
        "profile"      : base[ "profile" ],
        "borrowed"     : True
    }


def pick_unallocated_persona(
    pool                   : List[ PoolPersona ],
    occupied_names         : Set[ str ],
    stable_session_id      : str,
    overflow_persona       : Optional[ PoolPersona ]  = None,
    extra_colors           : Optional[ List[ str ] ]  = None,
    declared_manager_names : Optional[ Set[ str ] ]   = None
) -> Optional[ PoolPersona ]:
    """
    Uniform random draw from (pool − occupied − declared managers), falling
    back to Arnold-first→Extra-N overflow (preferred) or hash-borrow (legacy)
    on exhaustion.

    Reserve-from-random (Rick, 2026-06-11): names in `declared_manager_names`
    (the COSA_VOICE_MANAGERS__<PROJECT> roster, already resolved to POOL-KEY
    form) are excluded from the random draw — a random allocation must never
    squat a declared manager's identity. They remain claimable through the
    strict requested-persona path, which never calls this function. A free
    set emptied BY this exclusion lands in the existing exhaustion branch
    (overflow → Extra-N → legacy borrow) byte-unchanged.

    Overflow identity model (Option A, 2026-05-28): when the named pool is
    exhausted, the FIRST overflow session gets the configured overflow persona
    verbatim (Arnold). Once Arnold is itself occupied, additional concurrent
    overflow sessions get numbered "Extra N" identities — distinct names +
    distinct colors, all sharing Arnold's voice_id and icon. This fixes the
    prior collision where 2+ overflow sessions received the identical Arnold
    dict and were indistinguishable in the chorus UI.

    Requires:
        - pool is a list (may be empty)
        - occupied_names is a set of name strings (case-sensitive match against pool entries)
        - stable_session_id is a non-empty string
        - overflow_persona is a persona dict (with overflow=True) or None
        - extra_colors is a list of CSS hex strings or None/empty
        - declared_manager_names is a set of POOL-KEY name strings or None
          (caller resolves user-typed roster forms via _find_persona_in_pool)

    Ensures:
        - Returns a fresh dict with borrowed=False when
          (pool − occupied − declared_manager_names) is non-empty, chosen
          uniformly at random
        - declared_manager_names constrains ONLY the random draw — the
          exhaustion fallbacks (overflow/Extra-N/borrow) evaluate against
          occupied_names exactly as before
        - When the pool is fully occupied AND overflow_persona is non-None:
          * if overflow_persona's name is NOT occupied → returns a copy of
            overflow_persona with borrowed=False (preserving overflow=True) — the
            common single-overflow case, unchanged from prior behavior
          * if overflow_persona's name IS occupied → returns an "Extra N" persona
            (lowest free N), sharing the overflow voice_id/icon with a distinct
            name/display_name/color (see _make_extra_persona)
        - When the pool is fully occupied AND overflow_persona is None: falls back
          to borrowed_persona_for_sid (legacy deterministic hash-borrow); kept as
          defensive fallback for the case where the overflow is unconfigured
        - Returns None only when pool itself is empty (misconfiguration)
        - Never raises

    Args:
        pool: Full allocatable pool (overflow persona excluded — it's the overflow, not a peer)
        occupied_names: Names currently allocated to live sessions (pool members,
            the overflow name, and any "extra K" already in use)
        stable_session_id: Used both as anti-collision seed and for legacy borrow determinism
        overflow_persona: Arnold (or any other dict marked overflow=True) returned when
            the main pool is exhausted; None falls through to the legacy borrow path
        extra_colors: Green-rule-compliant palette for Extra-N personas, cycled by
            (n-1) % len; None/empty → Extras inherit the overflow persona's color
        declared_manager_names: Pool-key names reserved out of the random draw
            (declared-manager roster); None/empty → no reservation

    Returns:
        dict or None: Allocated persona, or None if pool is empty
    """
    if not pool:
        return None

    reserved = declared_manager_names or set()
    free     = [ p for p in pool if p[ "name" ] not in occupied_names and p[ "name" ] not in reserved ]

    if not free:
        if overflow_persona is not None:
            if overflow_persona[ "name" ] not in occupied_names:
                # First overflow — hand out Arnold verbatim. Copy so callers can
                # mutate without aliasing; set borrowed=False explicitly
                # (overflow=True is preserved from the source dict).
                return dict( overflow_persona, borrowed=False )
            # Arnold is already taken — spill to a numbered Extra-N identity so
            # concurrent overflows stay visually distinct (shared voice/icon,
            # distinct name/color).
            n = _lowest_free_extra_n( occupied_names )
            return _make_extra_persona( overflow_persona, n, extra_colors )
        return borrowed_persona_for_sid( pool, stable_session_id )

    chosen = random.choice( free )

    return {
        "name"         : chosen[ "name" ],
        "display_name" : chosen.get( "display_name" ) or display_name_for( chosen[ "name" ] ),
        "voice_id"     : chosen[ "voice_id" ],
        "icon"         : chosen[ "icon" ],
        "color"        : chosen[ "color" ],
        "profile"      : chosen[ "profile" ],
        "borrowed"     : False
    }


def allocate_persona_for_session(
    config_mgr,
    stable_session_id: str,
    declared_managers: Optional[ List[ str ] ] = None
) -> Optional[ PoolPersona ]:
    """
    End-to-end allocation: read pool, scan occupied, pick free (or borrow),
    reserving declared-manager names out of the random draw.

    This is the function the voice_persona router endpoint calls inside its
    asyncio.Lock critical section. It composes load_persona_pool_from_config
    + find_active_voice_persona_sessions (from session_bridge) + pick.

    The returned persona has an `assigned_at` ISO-8601 UTC timestamp added.

    Reserve-from-random (Rick, 2026-06-11): `declared_managers` is the
    COSA_VOICE_MANAGERS__<PROJECT> roster as user-typed names (e.g.
    "Mr. Radio"); each is resolved to its pool entry via the same
    case-insensitive key-form/display-form matching every requested-persona
    lookup uses (_find_persona_in_pool), and the resolved pool-key names are
    excluded from the random draw. Roster names that resolve to no pool
    entry constrain nothing — a typo or renamed pool must not brick
    allocation.

    Requires:
        - config_mgr is an initialized ConfigurationManager
        - stable_session_id is a non-empty string
        - declared_managers is a list of persona-name strings or None

    Ensures:
        - Returns a complete persona dict ready for bridge write, or None if
          the pool is empty (misconfiguration)
        - Never randomly returns a pool persona whose entry matches a
          declared_managers name; exclusion-emptied pools take the existing
          overflow/Extra-N/borrow exhaustion path unchanged
        - Adds an `assigned_at` field with current UTC ISO-8601 timestamp
        - Never raises on bridge-scan failures (the bridge module catches them)

    Args:
        config_mgr: ConfigurationManager
        stable_session_id: Session being allocated
        declared_managers: Declared-manager roster names to reserve out of
            the random draw (user-typed forms accepted)

    Returns:
        dict or None: persona with all 7 fields, or None if pool is empty
    """
    # Imported here to keep this module importable even when run from a
    # context where session_bridge isn't yet on PYTHONPATH. The router
    # always has it, so this is just a defensive ergonomic.
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions

    pool = load_persona_pool_from_config( config_mgr )
    if not pool:
        return None

    overflow = load_overflow_persona_from_config( config_mgr )

    # Read mtime TTL (in seconds) from config — falls back to 12h default if missing.
    # Used by find_active_voice_persona_sessions to reject stale persona-bearing
    # bridges even when the host-side prune at SessionStart didn't fire.
    stale_seconds = config_mgr.get(
        "cc session voice persona stale threshold seconds",
        default=43200, return_type="int", silent=True
    )

    active   = find_active_voice_persona_sessions( stale_threshold_seconds=stale_seconds )
    occupied = { p[ "name" ] for _path, _sid, p in active if isinstance( p, dict ) and p.get( "name" ) }

    # Green-rule-compliant palette for Extra-N overflow identities (cycled by index).
    # Empty/missing → Extras inherit the overflow persona's color.
    extra_colors = [
        c.strip()
        for c in config_mgr.get( "cc session voice persona extra colors", default="", silent=True ).split( "," )
        if c.strip()
    ]

    # Resolve roster names → pool-key names with the SAME matcher the strict
    # requested path uses ("Mr. Radio" / "mr radio" / "MR. RADIO" all land on
    # pool entry "mr radio"). Unresolvable names drop out silently.
    declared_manager_names = {
        match[ "name" ]
        for name in ( declared_managers or [ ] )
        if ( match := _find_persona_in_pool( pool, name ) ) is not None
    }

    persona = pick_unallocated_persona(
        pool, occupied, stable_session_id, overflow_persona=overflow, extra_colors=extra_colors,
        declared_manager_names=declared_manager_names
    )
    if persona is None:  # pragma: no cover  # defensive — pick only returns None for an empty pool, already guarded above
        return None

    persona[ "assigned_at" ] = datetime.now( timezone.utc ).isoformat( timespec="seconds" )

    return persona


# ── Requested-persona allocation primitives ──────────────────────────────────

def _find_persona_in_pool( pool: List[ PoolPersona ], requested_name: str ) -> Optional[ PoolPersona ]:
    """
    Locate a pool entry by name, case-insensitive on both the pool key form
    and the derived display_name.

    Requires:
        - pool is a list of pool persona dicts (may be empty)
        - requested_name is a non-empty string

    Ensures:
        - Returns the matching pool entry if found (matching against either
          the pool key form or display_name_for(name), case-insensitive,
          leading/trailing whitespace tolerated)
        - Returns None when no match found OR when requested_name is empty
          or whitespace-only
        - Never raises

    Args:
        pool: Allocatable persona pool
        requested_name: Name to look up (case-insensitive; user-typed form)

    Returns:
        Matching pool dict or None
    """
    if not requested_name:
        return None

    # Identity parity (Phase 2): match a persona reference to pool entries by the
    # one canonical key, so an accented/punctuated request ("María", "Mr. Radio")
    # resolves to the same pool entry as its pool-key form ("maria", "mr radio").
    # All compare sides moved in lockstep; the pool-key and display-name branches
    # both collapse onto the canonical key.
    needle = canonical_persona_key( requested_name )
    if not needle:
        return None

    for entry in pool:
        if canonical_persona_key( entry[ "name" ] ) == needle:
            return entry
        if canonical_persona_key( display_name_for( entry[ "name" ] ) ) == needle:
            return entry
    return None


def pick_requested_persona(
    pool                   : List[ PoolPersona ],
    occupied_to_session_id : Dict[ str, str ],
    requested_name         : str
) -> Dict[ str, Any ]:
    """
    Look up a requested persona by name and check availability against the
    caller-supplied occupied map.

    The caller (route handler) MUST exclude the requesting session's own
    current persona name from `occupied_to_session_id` before calling this
    helper. This keeps the helper pure (no session_bridge dependency) and
    makes swap semantics — "I currently hold Arnold; give me María" —
    work without false-positive occupied collisions.

    Requires:
        - pool is a list of pool persona dicts (may be empty)
        - occupied_to_session_id maps pool name → holding session_id for all
          currently occupied personas EXCEPT the requesting session's own
        - requested_name is a non-empty string

    Ensures:
        - Returns a dict with `status` ∈ {"ok", "not_in_pool", "occupied"}:
          * ok           → persona (fresh dict with borrowed=False), available
          * not_in_pool  → persona=None, available
          * occupied     → persona=None, holding_session_id, holding_persona_name, available
        - `available` is a list of pool names NOT in occupied_to_session_id, sorted
        - Never raises

    Args:
        pool: Allocatable pool (Sam excluded — he's the overflow, not a peer)
        occupied_to_session_id: name → session_id map for occupied personas
            (excluding the requesting session's own current allocation)
        requested_name: Name to look up (case-insensitive)

    Returns:
        Result dict (see Ensures)
    """
    available = sorted( [ p[ "name" ] for p in pool if p[ "name" ] not in occupied_to_session_id ] )

    match = _find_persona_in_pool( pool, requested_name )
    if match is None:
        return {
            "status"    : "not_in_pool",
            "persona"   : None,
            "available" : available
        }

    if match[ "name" ] in occupied_to_session_id:
        return {
            "status"               : "occupied",
            "persona"              : None,
            "holding_session_id"   : occupied_to_session_id[ match[ "name" ] ],
            "holding_persona_name" : match[ "name" ],
            "available"            : available
        }

    return {
        "status"    : "ok",
        "persona"   : {
            "name"         : match[ "name" ],
            "display_name" : match.get( "display_name" ) or display_name_for( match[ "name" ] ),
            "voice_id"     : match[ "voice_id" ],
            "icon"         : match[ "icon" ],
            "color"        : match[ "color" ],
            "profile"      : match[ "profile" ],
            "borrowed"     : False
        },
        "available" : available
    }


def allocate_requested_persona_for_session(
    config_mgr,
    stable_session_id: str,
    requested_name   : str
) -> Optional[ Dict[ str, Any ] ]:
    """
    End-to-end requested-persona allocation: read pool, scan occupied
    (excluding the requesting session's own current allocation), pick
    requested, stamp `assigned_at` on success.

    The "exclude self" semantics is what makes a swap call work — when the
    requesting session currently holds Arnold and asks for María, the scan
    must not count Arnold as occupied (or the caller would falsely conclude
    "all 6 in use").

    Requires:
        - config_mgr is an initialized ConfigurationManager
        - stable_session_id is a non-empty string
        - requested_name is a non-empty string

    Ensures:
        - Returns None when the pool itself is empty (misconfiguration);
          callers treat this as 500, not 422 — empty pool is a server
          configuration error, not a client input error
        - Otherwise returns a result dict same shape as
          pick_requested_persona, with `assigned_at` (UTC ISO-8601) stamped
          on the persona dict when status is "ok"
        - Excludes the requesting session's own allocation from the occupied
          scan so a swap works correctly
        - Never raises on bridge-scan failures

    Args:
        config_mgr: ConfigurationManager
        stable_session_id: Session requesting the allocation
        requested_name: Persona name being requested (case-insensitive)

    Returns:
        Result dict (see pick_requested_persona) or None if pool is empty
    """
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions

    pool = load_persona_pool_from_config( config_mgr )
    if not pool:
        return None

    stale_seconds = config_mgr.get(
        "cc session voice persona stale threshold seconds",
        default=43200, return_type="int", silent=True
    )

    active = find_active_voice_persona_sessions( stale_threshold_seconds=stale_seconds )

    # Build name → session_id map of currently-occupied personas,
    # excluding the requesting session's own allocation. The exclusion
    # is what makes swap semantics work.
    occupied_to_session_id: Dict[ str, str ] = {}
    for _path, sid, persona in active:
        if sid == stable_session_id:
            continue
        if not isinstance( persona, dict ):
            continue
        name = persona.get( "name" )
        if name:
            occupied_to_session_id[ name ] = sid

    result = pick_requested_persona( pool, occupied_to_session_id, requested_name )

    if result[ "status" ] == "ok":
        result[ "persona" ][ "assigned_at" ] = datetime.now( timezone.utc ).isoformat( timespec="seconds" )

    return result


# ── Declared-manager roster (COSA_VOICE_MANAGERS__<PROJECT>) ─────────────────

def parse_declared_managers( raw ) -> List[ str ]:
    """
    Normalize a declared-manager roster expression into an ordered name list.

    The ONE parser for the roster wherever it travels — the env reader
    (pick_declared_managers_from_env) and the allocate endpoint's
    `declared_managers` query param both call this, so the two carriers can
    never drift. Extracted 2026-06-11 when the roster gained its second
    carrier (hook→server transport for reserve-from-random).

    Requires:
        - raw is a str (comma-separated), a list of strings, or None

    Ensures:
        - Returns an ordered list of stripped, non-empty persona names
          (multi-word names pass through verbatim — commas are the only
          delimiter)
        - `*` elements are dropped (wildcard is chain syntax, meaningless in
          a manager roster — tolerated so a copy-pasted chain can't poison it)
        - Duplicates dropped with a normalize-keyed comparison (F-B:
          "Mr. Radio, mr radio, MR.RADIO" declares ONE manager); the first
          (verbatim) spelling is emitted, ORDER preserved — roster head =
          declared fallback manager
        - Non-string items inside a list input are skipped
        - Returns [] for None, empty/whitespace input, or any other type
        - Never raises

    Examples:
        "Mr. Radio, Tiberius"            → [ "Mr. Radio", "Tiberius" ]
        "Mr. Radio, mr radio, Tiberius"  → [ "Mr. Radio", "Tiberius" ]
        "Mr. Radio,Tiberius,*"           → [ "Mr. Radio", "Tiberius" ]
        None / "" / " , ,*"              → []
    """
    if isinstance( raw, str ):
        items = raw.split( "," )
    elif isinstance( raw, list ):
        items = [ item for item in raw if isinstance( item, str ) ]
    else:
        return [ ]

    managers = [ ]
    seen     = set()
    for item in items:
        stripped = item.strip()
        if not stripped or stripped == "*":
            continue
        # F-B: dedup key is the canonical identity key ("Tiberius, Mr. Radio,
        # mr radio" declares TWO managers, not three); the emitted name stays
        # verbatim. canonical_persona_key keeps internal spaces but is symmetric
        # on both sides, so "Mr. Radio"/"mr radio" still collapse to one entry
        # ("mr radio") — dedup behavior preserved + store-key parity gained.
        key = canonical_persona_key( stripped )
        if key in seen:
            continue
        seen.add( key )
        managers.append( stripped )
    return managers


def pick_declared_managers_from_env( project, environ=None ):
    """
    Read COSA_VOICE_MANAGERS__<PROJECT> — the user's declared-manager roster
    for a repo (Rick, 2026-06-11: multi-manager-per-repo support).

    The value is a comma-separated list of persona names; multi-word names
    pass through verbatim ("Tiberius, Mr. Radio" → ["Tiberius", "Mr. Radio"]).
    Declaration is role + reserve-from-random (Rick's D3 ruling, 2026-06-11,
    superseding the role-only Q2 scope): it marks the personas as managers
    for fleet-status rendering + escalation fanout, AND reserves their names
    OUT of random/chain-`*` allocation (see allocate_persona_for_session).
    It never OCCUPIES a persona — an explicit strict request or named chain
    element still claims a declared name; that is how managers get theirs.

    (Relocated from heartbeat_arbiter/manager_resolver.py 2026-06-11 when the
    allocation corridor became its second consumer — sibling of
    pick_persona_chain_from_env, same `__<PROJECT>` lookup pattern; the LIVE
    SessionStart hook imports THIS module and must not drag
    manager_resolver's lupin_mcp.session_spawner import into its chain.
    Single definition, no re-export shim — one-name rule.)

    Requires:
        - project is a project-key string or None
        - environ is a Mapping (os.environ when None) — injectable for tests

    Ensures:
        - Returns an ordered list of stripped non-empty persona names
          (parse semantics: see parse_declared_managers)
        - Returns [] when project is None/empty/whitespace, the env var is
          unset, or it parses to zero names
        - Normalizes project name: strip + UPPER + hyphens→underscores
        - Never raises

    Examples:
        COSA_VOICE_MANAGERS__LUPIN="Tiberius, Mr. Radio" + project="lupin"
            → [ "Tiberius", "Mr. Radio" ]

    See: src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md
         src/rnd/v0.1.8/2026.06.11-fleet-roster-env-file-and-reserve-from-random.md
    """
    if environ is None:
        environ = os.environ
    if not project or not str( project ).strip():
        return [ ]
    normalized = str( project ).strip().upper().replace( "-", "_" )
    value      = environ.get( f"COSA_VOICE_MANAGERS__{normalized}" )
    if not value:
        return [ ]
    return parse_declared_managers( value )


# ── Persona-chain resolution + allocation ────────────────────────────────────

PERSONA_CHAIN_WILDCARD = "*"


def pick_persona_chain_from_env( project: Optional[ str ], environ=None ) -> Optional[ str ]:
    """
    Read COSA_VOICE_PREFERRED_PERSONA__<PROJECT> from the environment.

    Resolves a per-repo declarative persona CHAIN from the user's shell
    environment. The value is a chain expression — an ordered, comma-separated
    list of persona names with an optional `*` wildcard meaning "then take
    anything free" — e.g. `COSA_VOICE_PREFERRED_PERSONA__LUPIN="Mr. Radio,Tiberius,*"`.
    A bare single name remains valid (a strict chain of one). The env var name
    embeds the project so one universal lookup pattern serves every repo.

    (Renamed from pick_preferred_persona_from_env 2026-06-11 when the value
    semantics widened from single soft-preference name to ordered chain —
    one-name rule, all consumers migrated.)

    Requires:
        - project is either a non-empty string (e.g., "plan", "lupin",
          "cosa-voice") or None/empty (the function tolerates both)

    Ensures:
        - Returns the chain expression string from the env var if set, verbatim
          (does NOT parse or validate — parse_persona_chain is the parser;
          pool validation is the allocator's job)
        - Returns None when project is None, empty, or whitespace-only
        - Returns None when the resolved env var is unset
        - Returns None when the resolved env var is set but empty/whitespace
        - Normalizes project name: strip + UPPER + hyphens→underscores
        - Reads from `environ` when supplied (testability), else os.environ
        - Never raises

    Examples:
        project="plan"        → reads COSA_VOICE_PREFERRED_PERSONA__PLAN
        project="cosa-voice"  → reads COSA_VOICE_PREFERRED_PERSONA__COSA_VOICE
        project="LUPIN"       → reads COSA_VOICE_PREFERRED_PERSONA__LUPIN
        project=None / ""     → returns None silently

    See: src/rnd/v0.1.8/2026.06.11-multi-manager-env-var-and-persona-preference-transport-fix.md
    """
    if environ is None:
        environ = os.environ
    if not project:
        return None
    normalized = project.strip().upper().replace( "-", "_" )
    if not normalized:
        return None
    env_key = f"COSA_VOICE_PREFERRED_PERSONA__{normalized}"
    value   = environ.get( env_key )
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def resolve_session_start_persona_chain( project: Optional[ str ], environ ) -> Optional[ str ]:
    """
    Resolve which persona-chain expression (if any) a SessionStart should
    send to the allocate endpoint, encoding the spawn/user precedence.

    Precedence (Rick, 2026-06-11):
        1. COSA_VOICE_PERSONA_CHAIN — injected by session_spawner when a
           manager passed spawn_sessions(persona_preference=...). Wins.
        2. Headless spawned child (COSA_VOICE_HEADLESS == "1") WITHOUT an
           explicit chain → None (random). The per-repo default is the
           USER's claim on manager names ("Mr. Radio,Tiberius,*"); letting
           a preference-less worker inherit it would squat a manager
           identity. Matches the de-facto pre-chain behavior (workers
           always fell through to random).
        3. COSA_VOICE_PREFERRED_PERSONA__<PROJECT> — the user's per-repo
           shell default, chain syntax.
        4. Nothing set → None → server random-allocates (unchanged).

    Requires:
        - project is a project-key string or None
        - environ is a Mapping (os.environ or a test dict)

    Ensures:
        - Returns the winning chain expression string, stripped, or None
        - Never raises

    Args:
        project: detect_project() result (for the per-repo env var lookup)
        environ: environment mapping to read from

    Returns:
        str or None: chain expression for the `persona_chain` query param
    """
    spawned_chain = ( environ.get( "COSA_VOICE_PERSONA_CHAIN" ) or "" ).strip()
    if spawned_chain:
        return spawned_chain
    if environ.get( "COSA_VOICE_HEADLESS" ) == "1":
        return None
    return pick_persona_chain_from_env( project, environ=environ )


def parse_persona_chain( raw ) -> List[ str ]:
    """
    Normalize a persona-chain expression into an ordered element list.

    A chain expression is either a comma-separated string or a list of
    strings; each element is a persona name (multi-word names like
    "Mr. Radio" pass through verbatim — commas are the only delimiter) or
    the wildcard `*` meaning "then take anything free".

    Requires:
        - raw is a str, a list, or None

    Ensures:
        - Returns an ordered list of stripped, non-empty elements
        - Duplicate elements (case-insensitive) are dropped, first
          occurrence wins — a repeated name cannot change the walk outcome
        - Non-string items inside a list input are skipped
        - Returns [] for None, empty/whitespace input, or any other type
        - Never raises

    Examples:
        "Rio,Krishna,*"            → [ "Rio", "Krishna", "*" ]
        "Mr. Radio, Tiberius , *"  → [ "Mr. Radio", "Tiberius", "*" ]
        [ "Rio", "Krishna" ]       → [ "Rio", "Krishna" ]
        "rio,Rio,*"                → [ "rio", "*" ]
        '["arnold","krishna","*"]' → [ "arnold", "krishna", "*" ]   (JSON-array string, row e071e834)
        None / "" / ",,,"          → []
    """
    if isinstance( raw, str ):
        # DEFENSE-IN-DEPTH (row e071e834, fix part 1 — the single choke point).
        # A caller that passes persona_preference as a JSON-ARRAY STRING (e.g.
        # json.dumps(list) → '["arnold", "krishna", "*"]') would otherwise be
        # comma-split into MANGLED elements ('["arnold"', '"krishna"', '"*"]'),
        # silently killing the `*` wildcard — it becomes '"*"]' and never equals
        # PERSONA_CHAIN_WILDCARD, so the whole chain reads exhausted and the server
        # 409s (nameless seat). Tolerate that form here: if the string parses as a
        # JSON list, treat it as the list input. Any parse failure falls through to
        # the bare comma-split, which is the intended CSV form.
        stripped_raw = raw.strip()
        if stripped_raw.startswith( "[" ):
            try:
                decoded = json.loads( stripped_raw )
            except ( ValueError, TypeError ):
                decoded = None
            items = [ item for item in decoded if isinstance( item, str ) ] if isinstance( decoded, list ) else raw.split( "," )
        else:
            items = raw.split( "," )
    elif isinstance( raw, list ):
        items = [ item for item in raw if isinstance( item, str ) ]
    else:
        return []

    chain = []
    seen  = set()
    for item in items:
        stripped = item.strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add( key )
        chain.append( stripped )
    return chain


def allocate_persona_chain_for_session(
    config_mgr,
    stable_session_id : str,
    chain_raw,
    declared_managers : Optional[ List[ str ] ] = None
) -> Dict[ str, Any ]:
    """
    Walk an ordered persona chain, allocating the first FREE element.

    Strict ordered-fallback semantics (Rick, 2026-06-11): try each named
    element in order via the strict requested-persona path; an occupied or
    unknown name records an outcome and falls through to the next element.
    A `*` element allocates randomly from the free pool ("then take
    anything"). A chain exhausted without `*` is a LOUD predictable fail —
    no silent random fallback.

    Reserve-from-random (Rick, 2026-06-11): `declared_managers` reaches ONLY
    the `*` wildcard's random draw — a NAMED chain element claims a declared
    name through the strict path exactly like an explicit request (that is
    how managers get their names); the wildcard, like plain random
    allocation, must never squat one.

    The caller (router) holds the allocation lock; this function performs
    the whole walk inside one critical section so sibling sessions racing
    the same chain serialize cleanly (first claims a name, second falls
    through to the next).

    Requires:
        - config_mgr is an initialized ConfigurationManager
        - stable_session_id is a non-empty string
        - chain_raw is a chain expression (str | list | None — anything
          parse_persona_chain accepts)

    Ensures:
        - Returns { "status": "ok", "persona": <dict with assigned_at>,
          "satisfied_by": <element>, "wildcard_used": bool,
          "outcomes": [<missed-element records>] } on success
        - Returns { "status": "exhausted", "persona": None, "outcomes": [...],
          "available": [...] } when every named element missed and no `*`
          was present
        - Returns { "status": "empty_chain", ... } when the expression
          parses to zero elements (caller decides the error surface)
        - Returns { "status": "pool_error", ... } when the pool itself is
          empty/misconfigured (caller treats as 500)
        - Each missed named element contributes an outcome record
          { "name", "status" ∈ {"occupied","not_in_pool"},
            [ "holding_session_id", "holding_persona_name" ] }
        - Never raises on bridge-scan failures

    Args:
        config_mgr: ConfigurationManager
        stable_session_id: Session being allocated
        chain_raw: Chain expression (see parse_persona_chain)
        declared_managers: Declared-manager roster names reserved out of the
            `*` wildcard's random draw (named elements unaffected)

    Returns:
        Result dict (see Ensures)
    """
    chain = parse_persona_chain( chain_raw )
    if not chain:
        return { "status": "empty_chain", "persona": None, "outcomes": [], "available": [] }

    outcomes  = []
    available = []

    for element in chain:
        if element == PERSONA_CHAIN_WILDCARD:
            persona = allocate_persona_for_session( config_mgr, stable_session_id, declared_managers=declared_managers )
            if persona is None:
                return { "status": "pool_error", "persona": None, "outcomes": outcomes, "available": available }
            return {
                "status"        : "ok",
                "persona"       : persona,
                "satisfied_by"  : PERSONA_CHAIN_WILDCARD,
                "wildcard_used" : True,
                "outcomes"      : outcomes
            }

        result = allocate_requested_persona_for_session( config_mgr, stable_session_id, element )
        if result is None:
            return { "status": "pool_error", "persona": None, "outcomes": outcomes, "available": available }

        if result[ "status" ] == "ok":
            return {
                "status"        : "ok",
                "persona"       : result[ "persona" ],
                "satisfied_by"  : element,
                "wildcard_used" : False,
                "outcomes"      : outcomes
            }

        outcome = { "name": element, "status": result[ "status" ] }
        if result[ "status" ] == "occupied":
            outcome[ "holding_session_id" ]   = result[ "holding_session_id" ]
            outcome[ "holding_persona_name" ] = result[ "holding_persona_name" ]
        outcomes.append( outcome )
        available = result[ "available" ]

    return { "status": "exhausted", "persona": None, "outcomes": outcomes, "available": available }


# ── Quick smoke test ─────────────────────────────────────────────────────────

def quick_smoke_test():
    """
    Self-contained smoke test for the pure functions.

    Tests pick_unallocated_persona and borrowed_persona_for_sid against
    synthetic pools, covering: empty pool, fully-free, partially-occupied,
    fully-occupied (borrow path), borrow determinism.

    Does NOT test allocate_persona_for_session (requires bridge files +
    config_mgr — covered by unit tests with mocks).
    """
    print( "Voice persona helpers smoke test" )
    print( "================================" )

    pool = [
        { "name": "Nora",    "voice_id": "v1", "icon": "🌸", "color": "#E91E63", "profile": "" },
        { "name": "Quentin", "voice_id": "v2", "icon": "🦉", "color": "#FFA000", "profile": "" },
        { "name": "Rachel",  "voice_id": "v3", "icon": "🕊️", "color": "#4CAF50", "profile": "" }
    ]

    # Test 1: empty pool → None
    assert pick_unallocated_persona( [], set(), "sid-1" ) is None, "Empty pool returns None"

    # Test 2: fully free, all picks come from pool with borrowed=False
    random.seed( 42 )
    picks = [ pick_unallocated_persona( pool, set(), f"sid-{i}" ) for i in range( 10 ) ]
    assert all( p is not None for p in picks ), "All picks should succeed"
    assert all( p[ "borrowed" ] is False for p in picks ), "None borrowed when fully free"
    assert all( p[ "name" ] in { "Nora", "Quentin", "Rachel" } for p in picks ), "Picks within pool"

    # Test 3: 2/3 occupied → must pick the remaining one
    free_pick = pick_unallocated_persona( pool, { "Nora", "Quentin" }, "sid-x" )
    assert free_pick is not None and free_pick[ "name" ] == "Rachel" and free_pick[ "borrowed" ] is False
    print( "  ✓ Allocation respects occupied set" )

    # Test 4: fully occupied → borrow path
    borrowed = pick_unallocated_persona( pool, { "Nora", "Quentin", "Rachel" }, "sid-borrow-1" )
    assert borrowed is not None, "Borrow returns a persona, not None"
    assert borrowed[ "borrowed" ] is True, "Borrow flag is True"
    assert borrowed[ "name" ] in { "Nora", "Quentin", "Rachel" }, "Borrow stays in pool"
    print( f"  ✓ Borrow path engaged on exhaustion (got {borrowed[ 'name' ]} borrowed=True)" )

    # Test 5: borrow determinism — same sid → same voice across calls
    b1 = borrowed_persona_for_sid( pool, "deterministic-sid" )
    b2 = borrowed_persona_for_sid( pool, "deterministic-sid" )
    assert b1 == b2, "Borrow is deterministic for same sid"
    b3 = borrowed_persona_for_sid( pool, "different-sid" )
    # Different sid usually picks different voice, but with pool=3 there's a
    # 1/3 collision chance — assert weakly: the function ran and returned valid
    assert b3 is not None and b3[ "borrowed" ] is True
    print( "  ✓ Borrow is deterministic for same stable_session_id" )

    # Test 6: borrowed_persona_for_sid edge cases
    assert borrowed_persona_for_sid( [],   "sid" ) is None, "Empty pool → None"
    assert borrowed_persona_for_sid( pool, ""    ) is None, "Empty sid → None"

    # Test 7: Arnold-first→Extra-N overflow (Option A, 2026-05-28)
    arnold       = { "name": "arnold", "display_name": "Arnold", "voice_id": "v_arnold",
                     "icon": "🪨", "color": "#FFD600", "profile": "gravelly male", "overflow": True }
    extra_colors = [ "#4527A0", "#6A1B9A", "#9C27B0" ]
    all_pool     = { "Nora", "Quentin", "Rachel" }

    # 7a: pool full, Arnold free → Arnold verbatim
    first = pick_unallocated_persona( pool, all_pool, "sid-a", overflow_persona=arnold, extra_colors=extra_colors )
    assert first[ "name" ] == "arnold" and first[ "overflow" ] is True and first[ "borrowed" ] is False

    # 7b: pool full + Arnold occupied → Extra 1 (shared voice/icon, palette color)
    e1 = pick_unallocated_persona( pool, all_pool | { "arnold" }, "sid-b", overflow_persona=arnold, extra_colors=extra_colors )
    assert e1[ "name" ] == "extra 1" and e1[ "display_name" ] == "Extra 1"
    assert e1[ "voice_id" ] == "v_arnold" and e1[ "icon" ] == "🪨" and e1[ "color" ] == "#4527A0"
    assert e1[ "overflow" ] is True and e1[ "borrowed" ] is False

    # 7c: Arnold + extra 1 occupied → extra 2
    e2 = pick_unallocated_persona( pool, all_pool | { "arnold", "extra 1" }, "sid-c", overflow_persona=arnold, extra_colors=extra_colors )
    assert e2[ "name" ] == "extra 2" and e2[ "color" ] == "#6A1B9A"

    # 7d: gap reuse — extra 1 free though extra 2 taken → extra 1
    gap = pick_unallocated_persona( pool, all_pool | { "arnold", "extra 2" }, "sid-d", overflow_persona=arnold, extra_colors=extra_colors )
    assert gap[ "name" ] == "extra 1"

    # 7e: color cycling beyond palette length wraps via modulo (n=4 → index 0)
    e4 = pick_unallocated_persona(
        pool, all_pool | { "arnold", "extra 1", "extra 2", "extra 3" }, "sid-e",
        overflow_persona=arnold, extra_colors=extra_colors
    )
    assert e4[ "name" ] == "extra 4" and e4[ "color" ] == "#4527A0"

    # 7f: empty palette → Extra inherits the overflow persona's color
    e_nopal = pick_unallocated_persona( pool, all_pool | { "arnold" }, "sid-f", overflow_persona=arnold, extra_colors=None )
    assert e_nopal[ "name" ] == "extra 1" and e_nopal[ "color" ] == arnold[ "color" ]
    print( "  ✓ Arnold-first→Extra-N overflow: Arnold verbatim, then numbered Extras (gap-reusing)" )

    # Test 8: _lowest_free_extra_n unit checks
    assert _lowest_free_extra_n( set() )                        == 1
    assert _lowest_free_extra_n( { "extra 1" } )                == 2
    assert _lowest_free_extra_n( { "extra 2" } )                == 1
    assert _lowest_free_extra_n( { "extra 1", "extra 2" } )     == 3
    print( "  ✓ _lowest_free_extra_n picks lowest unused index" )

    # Test 9: reserve-from-random — declared-manager names never come out of
    # the random draw; exclusion-emptied pool takes the overflow path.
    for _ in range( 10 ):
        reserved_pick = pick_unallocated_persona( pool, set(), "sid-r", declared_manager_names={ "Nora", "Quentin" } )
        assert reserved_pick[ "name" ] == "Rachel", reserved_pick
    all_reserved = pick_unallocated_persona(
        pool, set(), "sid-r2", overflow_persona=arnold, extra_colors=extra_colors,
        declared_manager_names={ "Nora", "Quentin", "Rachel" }
    )
    assert all_reserved[ "name" ] == "arnold" and all_reserved[ "overflow" ] is True
    print( "  ✓ Reserve-from-random: declared managers skipped; emptied pool → overflow" )

    print( "\nAll voice persona helpers smoke tests: ✓ passed" )


if __name__ == "__main__":  # pragma: no cover  # CLI entry point; quick_smoke_test body is exercised by the unit suite
    quick_smoke_test()
