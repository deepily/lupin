"""
How a spawned session's voice starts: the worker default voice mode.

Rick's ruling, 13 Nov 2026: a worker spawned by `spawn_sessions` starts quiet, so he hears his
managers and not the workers. Quiet means speakerphone off with the ding kept. It does not mean
silent: an urgent notify from a quiet worker still speaks.

One INI key, `cc session worker default voice mode`, holds one of three words:

    quiet        speakerphone off (the default)
    speakerphone speakerphone on
    inherit      the mode-aware default of `session_bridge._get_default_speakerphone`
                 (solo off, chorus on)

Three places use this module:

    1. `spawn_sessions` reads the key and forwards it to the child as `COSA_VOICE_WORKER_VOICE_MODE`.
       A spawn with role "manager" always forwards `inherit`.
    2. The child's SessionStart hook (`register_session`) turns that word into `speakerphone_on`.
       After the voice persona is allocated it re-applies `inherit` to any session whose persona is
       a standing manager, whatever role the session was spawned with.
    3. `notify_user` asks `is_quiet_worker_bridge` whether to stamp `worker_quiet` on the event.

See: src/rnd/v0.2.3/2026.11.13-workers-quiet-by-default-plan.md
"""

from typing import Callable, Optional

INI_KEY       = "cc session worker default voice mode"
ENV_VAR       = "COSA_VOICE_WORKER_VOICE_MODE"
MODE_QUIET    = "quiet"
MODE_SPEAKER  = "speakerphone"
MODE_INHERIT  = "inherit"
MODES         = ( MODE_QUIET, MODE_SPEAKER, MODE_INHERIT )
MANAGER_ROLE  = "manager"


def resolve_worker_voice_mode( config_mgr ) -> str:
    """
    Read the worker default voice mode through the configuration manager.

    Requires:
        - config_mgr has a `get( key, default=None )` method, as ConfigurationManager does

    Ensures:
        - returns one of the three mode words, lower-cased and stripped

    Raises:
        - ValueError naming INI_KEY when the key is absent, blank, or not one of the three mode words. There is
          no default in code: a silent fallback would hide a mistyped value
    """
    raw = config_mgr.get( INI_KEY, default=None )
    if raw is None or not str( raw ).strip():
        raise ValueError( f"INI key '{INI_KEY}' is missing or blank; set it to one of {', '.join( MODES )}" )
    mode = str( raw ).strip().lower()
    if mode not in MODES:
        raise ValueError( f"INI key '{INI_KEY}' is '{raw}'; it must be one of {', '.join( MODES )}" )
    return mode


def worker_voice_env( role: str, config_fn: Callable ) -> dict:
    """
    Build the env entry that tells a spawned child how to start its voice.

    Requires:
        - role is the spawn role string
        - config_fn() returns a ConfigurationManager (not called for a manager spawn)

    Ensures:
        - a role equal to "manager" (exact match) gives `{ ENV_VAR: "inherit" }` without reading the INI
        - any other role gives `{ ENV_VAR: <the key's value> }`

    Raises:
        - ValueError from `resolve_worker_voice_mode` when the key is unusable
    """
    if role == MANAGER_ROLE: return { ENV_VAR: MODE_INHERIT }
    return { ENV_VAR: resolve_worker_voice_mode( config_fn() ) }


def speakerphone_for_mode( mode: Optional[ str ], inherit_fn: Callable ) -> bool:
    """
    Turn a mode word into the bridge's `speakerphone_on` value.

    Requires:
        - mode is one of the three mode words, None, or any other string
        - inherit_fn() returns the mode-aware default boolean

    Ensures:
        - quiet gives False, speakerphone gives True, inherit gives inherit_fn()
        - None or an unknown word gives False, today's behaviour for a child spawned by an older server
    """
    if mode == MODE_SPEAKER: return True
    if mode == MODE_INHERIT: return bool( inherit_fn() )
    return False


def is_quiet_worker_bridge( data: dict, manager_stamp_field: str ) -> bool:
    """
    Decide whether a bridge belongs to a quiet worker, so `notify_user` stamps `worker_quiet`.

    Requires:
        - data is the parsed bridge dict
        - manager_stamp_field names the bridge field holding the implicit manager-figure answer

    Ensures:
        - True only when the bridge has `spawned_by`, its role is not exactly "manager", the implicit
          manager stamp is explicitly False, and `speakerphone_on` is explicitly False
        - an absent or true stamp gives False, so a legacy bridge or a standing manager spawned with
          any role (Cheech was measured as role "author") is never quieted by mistake
        - never raises
    """
    try:
        if not data.get( "spawned_by" ): return False
        if data.get( "role" ) == MANAGER_ROLE: return False
        if data.get( manager_stamp_field ) is not False: return False
        return data.get( "speakerphone_on" ) is False
    except AttributeError:
        return False
