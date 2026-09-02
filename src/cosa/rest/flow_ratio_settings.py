"""
The ONE place the closed-vs-new ratio's window and threshold live.

WHY THIS MODULE EXISTS. The two numbers were hardcoded in THREE places:

    tasks.py             RATIO_DEFAULT_WINDOW_HOURS = 24     the endpoint's window
    tasks.py             verdict = "allow" if ratio < 1.0    the header's verdict
    task_store_rules.py  if ratio < 1.0: return None         the CREATE gate

The endpoint's own docstring already promised the verdict is computed in one place "so
the header and the gate cannot drift apart" — but the THRESHOLD itself was duplicated,
so they could. Editing one literal and not the other would leave the board reporting
"allow" while a create is refused, with nothing anywhere reporting the disagreement.
One module, read by both, removes that by construction.

THREE LAYERS, HIGHEST WINS:

    1. persisted override   the LIVE value    written by the API, a JSON file on disk
    2. INI                  the BOOT default  `task flow ratio window hours` / `... allow below`
    3. module fallback      last resort       today's shipped behaviour, written down

A config file is not a runtime control — a server reads it at boot, so a slider that
wrote only to the INI would move a number the running server never re-reads and would
feel broken. Hence layer 1.

WHY A FILE AND NOT PROCESS MEMORY. An in-process override dies at the next bounce and
is invisible to every other process. `:7999` and `:8000` are separate processes and the
create gate runs in whichever one received the write, so a memory-only override would
give two servers two different live thresholds and lose both on restart. The file is
read on each access (guarded by mtime, so it is a `stat` in the common case), which is
what makes the value both PERSISTENT and CONSISTENT across processes on this box.

It lives under `fleet_data_root()` — the fleet runtime-data directory OUTSIDE the repo.
Not a gitignored path inside the tree: measured 2026-07-26, `git clean -xdf` lists
gitignored runtime files as "would remove", so in-tree state is on the kill list rather
than shielded by it.

⚠️ NO NUMBER IN THIS FILE IS A RECOMMENDATION. The fallbacks are today's shipped
behaviour written down (24 hours; opens below 1.0) so that moving these settings into
config cannot silently change what the gate does. Choosing a different threshold is the
operator's call, made with the live board in front of them — which is what the slider
is for.

⚠️ SCOPE OF "CONSISTENT": one box, one data root. Every process resolving the same
`fleet_data_root()` shares the value, so dev and test agree. A second host does not.
"""

import json
import os

from cosa.config.configuration_manager import ConfigurationManager
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root

# 🔴 THE CONTAINER CANNOT USE fleet_data_root() AND THIS ENV VAR IS WHY.
# Measured 2026-09-01 inside lupin-rest-dev: the resolver returns `/projects-data/lupin`
# (its fallback is <repo-parent-parent>/projects-data/<repo>, and the repo is /var/lupin,
# so the parent-of-parent is `/`), that directory does not exist, and a write raises
# PermissionError [Errno 13] '/projects-data'. Every PATCH from the UI answered 500.
#
# `dm.py:365` already solved this and I did not copy it: resolve an env var FIRST — which
# the containers set, pointing at a bind mount — and fall back to fleet_data_root() only
# on the host, where it is correct. Both names then reach the SAME physical directory —
# which is true only because the fallback appends OVERRIDE_SUBDIR. It did not until
# 2026-09-01, and the two branches named two different files the whole time.
#
# ⚠️ THE MOUNT AND THE ENV VAR RESOLVE AT CONTAINER **CREATE**, so picking them up needs
# `docker compose up -d --force-recreate`, never a plain restart — a restart reuses the
# old values and the change silently does not land.
#
# ⚠️ The container path sits under /var/lupin (the repo mount) while the HOST path is
# outside the checkout, which is what actually matters: the reason runtime state left the
# tree is that `git clean -xdf` lists gitignored files as "would remove". The host side is
# never inside a checkout. dm-corpus is mounted exactly this way; this is not a regression
# of that rule, and it has been questioned once already — hence this note.
_SETTINGS_DIR_ENV = "LUPIN_FLOW_RATIO_DIR"


# Today's shipped behaviour, used only when the INI key is absent or unreadable. A
# MIGRATION of the old hardcoded literals, not a new opinion — see the module docstring.
FALLBACK_WINDOW_HOURS = 24
FALLBACK_ALLOW_BELOW  = 1.0

# 🔨 RICK, 2026-09-02, on being shown that enforcement was a Python constant:
# "Why is this not included as a configuration instead of a constant in the Python
# code file? Put it where it belongs!"
#
# He is right, and the reason is not tidiness. The window and the threshold were
# ALREADY operator-adjustable here — he can move a slider and the gate follows within
# one request. Enforcement, the one setting that decides whether any of that has teeth,
# needed a code edit and a deploy. So the dial he could turn was the one that changed
# nothing, and the switch that mattered was the one he could not reach.
#
# ⚠️ FALLBACK IS False, DELIBERATELY. An absent config must not silently start 422ing
# every create — that is the direction where being wrong is loud and destructive. An
# operator turning it ON is an explicit act; the code failing open is the safe default.
FALLBACK_ENFORCEMENT_ACTIVE = False

INI_KEY_WINDOW_HOURS = "task flow ratio window hours"
INI_KEY_ALLOW_BELOW  = "task flow ratio allow below"
INI_KEY_ENFORCEMENT  = "task flow ratio enforcement active"

# The mount's leaf directory. The host fallback MUST append it: the container is
# handed `<fleet_data_root>/flow-ratio` as its whole world, so a fallback that stops
# at `<fleet_data_root>` names a different file than every server writes.
OVERRIDE_SUBDIR   = "flow-ratio"
OVERRIDE_FILENAME = "flow-ratio-settings.json"

# Bounds. The window mirrors the endpoint's existing Query( ge=1, le=8760 ) so the API
# and this module cannot disagree about what is acceptable. The threshold's ceiling is
# deliberately generous: a very high number is a legitimate operator choice meaning
# "effectively open", and refusing it would be this module making the policy call it
# just said belongs to the operator.
MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 8760
MIN_ALLOW_BELOW  = 0.0
MAX_ALLOW_BELOW  = 1000.0

# mtime-guarded cache of the override file, so a read is a stat rather than a parse.
_cache       = { "window_hours": None, "allow_below": None }
_cache_mtime = None


def override_path():
    """
    The persisted override file.

    Ensures:
        - returns $LUPIN_FLOW_RATIO_DIR/flow-ratio-settings.json when the variable is
          set (the container's mount point — see the note beside _SETTINGS_DIR_ENV)
        - otherwise <fleet_data_root()>/flow-ratio/flow-ratio-settings.json — the
          host-side convention hold files and the rest of the fleet's runtime state
          already use, with OVERRIDE_SUBDIR appended so this names the SAME file the
          env-var branch does. The subdirectory is not decoration; see below.
        - does NOT create the file or the directory (reads tolerate absence)

    🔴 THE FALLBACK MUST APPEND `flow-ratio/`, AND FOR THREE DAYS IT DID NOT. Measured
    2026-09-01 in the running containers and on the host:

        lupin-rest-dev    /var/lupin/flow-ratio/flow-ratio-settings.json
        lupin-rest-test   /var/lupin/flow-ratio/flow-ratio-settings.json
        host (before)     <fleet_data_root>/flow-ratio-settings.json        <-- one level up
        host (after)      <fleet_data_root>/flow-ratio/flow-ratio-settings.json

    The mount hands the container `<fleet_data_root>/flow-ratio` as its whole world, so a
    fallback stopping at `<fleet_data_root>` named a different file than every server
    writes — and this block claimed the opposite, that "both name the SAME physical
    directory". `dm.py`, which this resolver was copied from, gets it right: its fallback
    is `fleet_data_root()/dm-corpus`, subdirectory included. The subdirectory was dropped
    in the copy. Adding it back is the whole fix, and the claim is now true.

    Nothing had to be migrated: `<fleet_data_root>/flow-ratio-settings.json` did not
    exist, because no host-side caller has ever written one. That is also why this sat
    unnoticed — the wrong path was only ever going to be read by a host process, and
    there is not one yet.

    """
    override_dir = os.environ.get( _SETTINGS_DIR_ENV )
    if override_dir:
        return os.path.join( override_dir, OVERRIDE_FILENAME )
    return os.path.join( fleet_data_root(), OVERRIDE_SUBDIR, OVERRIDE_FILENAME )


def _read_overrides():
    """
    Load the persisted overrides, re-parsing only when the file's mtime has moved.

    Ensures:
        - returns a dict with keys "window_hours" / "allow_below" /
          "enforcement_active", each a value or None
        - a MISSING file is the ordinary no-override case and returns both None
        - a CORRUPT file is REPORTED on stdout and treated as no-override. It does not
          raise: a bad settings file must not take the board's header down, and silence
          would leave an operator's write apparently ignored with no clue why.
    """
    global _cache, _cache_mtime

    path = override_path()
    try:
        mtime = os.path.getmtime( path )
    except OSError:
        _cache_mtime = None
        _cache       = { "window_hours": None, "allow_below": None, "enforcement_active": None }
        return _cache

    if mtime == _cache_mtime:
        return _cache

    try:
        with open( path, "r" ) as handle:
            body = json.load( handle )
        if not isinstance( body, dict ):
            raise ValueError( f"expected a JSON object, got {type( body ).__name__}" )
        _cache = {
            "window_hours"       : body.get( "window_hours" ),
            "allow_below"        : body.get( "allow_below" ),
            "enforcement_active" : body.get( "enforcement_active" ),
        }
        _cache_mtime = mtime
    except Exception as error:
        print( f"[flow-ratio] override file {path} unusable ({error}) — falling back to config" )
        _cache       = { "window_hours": None, "allow_below": None, "enforcement_active": None }
        _cache_mtime = mtime

    return _cache


def _ini_value( key, return_type, fallback ):
    """
    Read one INI key, falling back on a missing key or an unusable value.

    Ensures:
        - returns the configured value, or `fallback`
        - never raises — a malformed INI must not take the endpoint down. A bad value is
          REPORTED rather than swallowed, because a silent fallback is how an operator's
          edit appears to do nothing at all.
    """
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        value      = config_mgr.get( key, return_type=return_type )
        return fallback if value is None else value
    except Exception as error:
        print( f"[flow-ratio] INI key '{key}' unreadable ({error}) — using fallback {fallback}" )
        return fallback


def _clamp_window( value, fallback ):
    """Coerce to an in-range int, falling back when the value is not a number at all."""
    try:
        value = int( value )
    except ( TypeError, ValueError ):
        print( f"[flow-ratio] window {value!r} is not an integer — using {fallback}" )
        return fallback
    return max( MIN_WINDOW_HOURS, min( MAX_WINDOW_HOURS, value ) )


def _clamp_threshold( value, fallback ):
    """Coerce to an in-range float, falling back when the value is not a number at all."""
    try:
        value = float( value )
    except ( TypeError, ValueError ):
        print( f"[flow-ratio] threshold {value!r} is not a number — using {fallback}" )
        return fallback
    return max( MIN_ALLOW_BELOW, min( MAX_ALLOW_BELOW, value ) )


def get_window_hours():
    """
    The live window, in hours — persisted override, else INI, else fallback.

    Ensures:
        - always an int inside [ MIN_WINDOW_HOURS, MAX_WINDOW_HOURS ]
    """
    stored = _read_overrides()[ "window_hours" ]
    if stored is not None:
        return _clamp_window( stored, FALLBACK_WINDOW_HOURS )
    return _clamp_window( _ini_value( INI_KEY_WINDOW_HOURS, "int", FALLBACK_WINDOW_HOURS ),
                          FALLBACK_WINDOW_HOURS )


def get_allow_below():
    """
    The live threshold — the gate OPENS on a ratio strictly below this number.

    Ensures:
        - persisted override, else INI, else fallback
        - always a float inside [ MIN_ALLOW_BELOW, MAX_ALLOW_BELOW ]
    """
    stored = _read_overrides()[ "allow_below" ]
    if stored is not None:
        return _clamp_threshold( stored, FALLBACK_ALLOW_BELOW )
    return _clamp_threshold( _ini_value( INI_KEY_ALLOW_BELOW, "float", FALLBACK_ALLOW_BELOW ),
                             FALLBACK_ALLOW_BELOW )


def get_enforcement_active():
    """
    Does the ratio gate actually REFUSE a create, or only warn about it?

    This is the switch that decides whether the window and the threshold have teeth.
    It lives here, beside them, because Rick asked for it here (2026-09-02) — and the
    asymmetry he objected to was real: the two numbers were live-adjustable while the
    one that made them matter needed a code edit and a deploy.

    Ensures:
        - persisted override, else INI, else FALLBACK_ENFORCEMENT_ACTIVE
        - always a bool — an unparseable value falls back rather than raising, because
          the caller is on the create path and must not 500 over a settings file
        - the FALLBACK IS False: an absent or broken config warns, it does not start
          refusing every create. Failing open is the safe direction here; failing closed
          would take the board's write path down over a missing file.
    """
    stored = _read_overrides()[ "enforcement_active" ]
    if stored is not None:
        return bool( stored )
    # ⚠️ "boolean", NOT "bool". ConfigurationManager._get_typed_value tests
    # `return_type == "boolean"` exactly and RAISES on anything else — and
    # `_ini_value` catches that and returns the fallback. So "bool" here would not
    # error: it would silently report enforcement OFF forever, whatever the INI said.
    # (`src/cosa/rest/email_service.py:148,207` passes "bool" for `smtp use tls` and
    # is presumably taking its default the same way — noted, not fixed here.)
    return bool( _ini_value( INI_KEY_ENFORCEMENT, "boolean", FALLBACK_ENFORCEMENT_ACTIVE ) )


def set_overrides( window_hours=None, allow_below=None, enforcement_active=None ):
    """
    Persist a runtime override for either value, or both.

    Requires:
        - window_hours is None (leave unchanged) or coercible to int
        - allow_below is None (leave unchanged) or coercible to float
        - enforcement_active is None (leave unchanged) or a bool

    Ensures:
        - a supplied value is validated, clamped into range, and written to
          `override_path()` so it survives a bounce and is visible to every process
          resolving the same data root
        - an omitted (None) argument leaves that setting alone — this is a PATCH, not a
          replace, so an operator moving one slider cannot silently reset the other
        - the write is ATOMIC (temp file + os.replace), so a concurrent reader sees the
          old file or the new one, never a half-written one
        - returns the live pair after the write, so a caller reports what actually took
          effect rather than what it asked for. Those differ when a value clamps, and a
          UI echoing the request would then show a number the gate is not using.

    Raises:
        - ValueError naming the offending argument when a supplied value is not a
          number. It REFUSES rather than falling back: a fallback here would answer an
          operator's explicit write with a different number and report success.
        - OSError if the data root cannot be written. Deliberately NOT swallowed — a
          slider that reports success while persisting nothing is the failure this whole
          module exists to avoid.
    """
    current = dict( _read_overrides() )

    if window_hours is not None:
        try:
            window_hours = int( window_hours )
        except ( TypeError, ValueError ):
            raise ValueError( f"window_hours must be an integer, got {window_hours!r}" )
        current[ "window_hours" ] = max( MIN_WINDOW_HOURS, min( MAX_WINDOW_HOURS, window_hours ) )

    if allow_below is not None:
        try:
            allow_below = float( allow_below )
        except ( TypeError, ValueError ):
            raise ValueError( f"allow_below must be a number, got {allow_below!r}" )
        current[ "allow_below" ] = max( MIN_ALLOW_BELOW, min( MAX_ALLOW_BELOW, allow_below ) )

    if enforcement_active is not None:
        # No clamp and no coercion from a string: "false" is truthy in Python, and an
        # operator who typed it would get enforcement switched ON while being told it
        # was off. A bool is demanded rather than guessed at.
        if not isinstance( enforcement_active, bool ):
            raise ValueError( f"enforcement_active must be a bool, got {enforcement_active!r}" )
        current[ "enforcement_active" ] = enforcement_active

    _write_overrides( current )
    return current_settings()


def clear_overrides():
    """
    Drop every persisted override so the INI values govern again.

    Ensures:
        - the override file is removed (absence is not an error — clearing an
          already-clear setting is a no-op, not a failure)
        - returns the live pair after the reset
    """
    global _cache, _cache_mtime
    try:
        os.remove( override_path() )
    except FileNotFoundError:
        pass
    _cache       = { "window_hours": None, "allow_below": None }
    _cache_mtime = None
    return current_settings()


def _write_overrides( values ):
    """
    Atomically persist `values` to `override_path()`.

    Ensures:
        - the parent directory exists
        - the file is replaced atomically, so no reader observes a partial write
        - the in-process cache is invalidated, so the very next read re-parses. Without
          this, a write followed by a read inside the same second could return the OLD
          value: mtime has one-second granularity on some filesystems, which is the same
          whole-second trap that defeats .pyc invalidation elsewhere in this repo.
    """
    global _cache, _cache_mtime

    path = override_path()
    os.makedirs( os.path.dirname( path ), exist_ok=True )

    temp = f"{path}.tmp"
    with open( temp, "w" ) as handle:
        json.dump( values, handle, indent=2 )
        handle.write( "\n" )
    os.replace( temp, path )

    _cache       = { "window_hours": None, "allow_below": None }
    _cache_mtime = None


def current_settings():
    """
    The live pair plus its provenance.

    Ensures:
        - returns { window_hours, allow_below, window_source, threshold_source } where
          each source is "override" or "config"
        - the sources are reported because a number alone cannot tell an operator
          whether their INI edit is in force or is being MASKED by a persisted override
          — which is exactly the confusion a two-layer scheme otherwise creates
    """
    stored = _read_overrides()
    return {
        "window_hours"       : get_window_hours(),
        "allow_below"        : get_allow_below(),
        "enforcement_active" : get_enforcement_active(),
        "window_source"      : "override" if stored[ "window_hours" ]       is not None else "config",
        "threshold_source"   : "override" if stored[ "allow_below"  ]       is not None else "config",
        "enforcement_source" : "override" if stored[ "enforcement_active" ] is not None else "config",
    }
