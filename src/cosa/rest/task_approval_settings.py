"""
Approver allowlist for the holding area — CONFIGURATION, never a constant.

🔨 RICK, 2026-09-02, making exactly this correction about the ratio gate's enforcement
flag: "Why is this not included as a configuration instead of a constant in the Python
code file? Put it where it belongs!" He also said the approver set is "either a manager
or him, FOR NOW" — and "for now" is the whole requirement. A list that needs a code edit
and a deploy to change is not a "for now" list; it is a permanent one wearing a
temporary label.

WHAT IT GATES. Admission out of `not_approved` — the holding area — onto somebody's
board. A row nobody approved must not become owed work.

🔴 THE HONEST LIMIT, STATED HERE RATHER THAN LEFT FOR SOMEBODY TO FIND. The actor this
list is checked against is `payload.actor`, which the CALLER DECLARES. It is not the
authenticated identity: `require_api_key_or_jwt` proves the caller holds a fleet
credential, and every seat holds the same one. So this refuses an honest caller who is
not an approver; it does not stop a dishonest one from typing an approver's name.

⇒ That makes it a POLICY control, not a security boundary, and the difference matters
for what you may conclude from it: it stops a seat approving its own work by habit, and
it does not stop a seat that decides to. Calling it authorization would overclaim. The
authenticated user id IS recorded alongside, so a false claim is attributable after the
fact — accountability rather than prevention.

WHY IT REUSES THE FLOW-RATIO DIRECTORY AND DOES NOT MOUNT ITS OWN. A new mount resolves
at container CREATE, so it would need `docker compose up -d --force-recreate` on both
servers before a single approval could work — and a plain restart would apply it
silently-not-at-all. `LUPIN_FLOW_RATIO_DIR` is already mounted in `lupin-rest-dev` and
`lupin-rest-test`. A sibling FILE in that directory costs nothing and lands the moment
it is written.

⚠️ The variable's name says flow-ratio and this is not flow-ratio. That mismatch is
deliberate and cheap to fix later (add a second env var, keep this as the fallback);
paying a force-recreate on both servers today to avoid a misleading name would be the
expensive half of the trade.
"""

import json
import os

from cosa.config.configuration_manager import ConfigurationManager
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
from cosa.rest.task_store_rules import NOT_APPROVED_STATUS, WONT_FIX_STATUS
from lupin_mcp.persona_normalization import canonical_persona_key

# Same env var as flow_ratio_settings, for the mount reason in the docstring. Resolved
# FIRST — the container sets it; `fleet_data_root()` is correct only on the host, where
# it returns a real writable directory.
_SETTINGS_DIR_ENV = "LUPIN_FLOW_RATIO_DIR"

# The mount's leaf directory. The host fallback MUST append it, or the two branches name
# two different files — the defect flow_ratio_settings carried for three days.
OVERRIDE_SUBDIR   = "flow-ratio"
OVERRIDE_FILENAME = "task-approval-settings.json"

INI_KEY_APPROVERS   = "task approval approver personas"
INI_KEY_ENFORCEMENT = "task approval enforcement active"

# 🔨 THE BROWSER'S DOOR (Rick, 2026-09-04, row 9d3a975e): "clear the bug that I can't
# approve a ticket sitting in the holding area."
#
# WHY A SECOND KEY AND NOT A LONGER ALLOWLIST. The allowlist above is checked against
# `payload.actor`, and the browser's actor is generated PER WEBSOCKET SESSION —
# measured live 2026-09-04 as "operator foolish goat", where the same page had said
# "operator wise penguin" a day earlier. No fixed entry can ever match a string that
# is re-minted every session, so adding one would fix the click that produced it and
# nothing else.
#
# ⇒ This key maps a LOGIN ACCOUNT to an approver persona, and the account arrives on
# the JWT the browser already sends. Format: comma-separated `email = persona` pairs.
#
#     task approval approver accounts = ricardo.felipe.ruiz@gmail.com = rick
#
# 🔴 AND THIS PATH IS STRONGER THAN THE ACTOR PATH, WHICH IS THE POINT. The module
# docstring's honest limit — "the actor is caller-DECLARED, so this is a policy
# control, not a security boundary" — still describes `is_approver`. It does NOT
# describe this: the email is read off a signature-validated access token, so a caller
# cannot type its way past it. Two doors of different strength, deliberately, and the
# refusal message names both so nobody has to read this file to find the second.
INI_KEY_APPROVER_ACCOUNTS = "task approval approver accounts"

# ⚠️ FALLBACK IS False, DELIBERATELY — the same direction of safety flow_ratio_settings
# chose and for the same reason. An absent or unreadable config must not silently start
# refusing every admission out of the holding area. Turning enforcement ON is an explicit
# operator act; failing OPEN is the safe default, because a gate that fails closed on a
# missing file takes the board down for everyone with no obvious cause.
FALLBACK_ENFORCEMENT_ACTIVE = False

# Rick, always. He is not "in the list" — he IS the standing authority the list exists to
# delegate from, so he is unconditional and cannot be configured away. An empty allowlist
# therefore still has exactly one approver rather than none, which is what stops a
# truncated config from locking the whole fleet out of its own holding area.
UNCONDITIONAL_APPROVERS = ( "rick", )

# mtime-guarded cache: a read is a stat, not a parse.
_cache       = { "approvers": None, "enforcement_active": None, "default_to_holding": None,
                 "approver_accounts": None }
_cache_mtime = None


def override_path():
    """
    The persisted override file.

    Ensures:
        - returns $LUPIN_FLOW_RATIO_DIR/task-approval-settings.json when set (the
          containers' mount point)
        - otherwise <fleet_data_root()>/flow-ratio/task-approval-settings.json — the
          SAME physical directory, which is true only because the fallback appends
          OVERRIDE_SUBDIR
        - does NOT create the file or the directory (reads tolerate absence)
    """
    override_dir = os.environ.get( _SETTINGS_DIR_ENV )
    if override_dir:
        return os.path.join( override_dir, OVERRIDE_FILENAME )
    return os.path.join( fleet_data_root(), OVERRIDE_SUBDIR, OVERRIDE_FILENAME )


def _read_overrides():
    """
    Load the persisted overrides, re-parsing only when the file's mtime has moved.

    Ensures:
        - returns a dict with keys "approvers" / "enforcement_active", each a value or None
        - a MISSING file is the ordinary no-override case and returns both None
        - a CORRUPT file is REPORTED on stdout and treated as no-override — it must not
          raise, because a bad settings file taking the board down is worse than the
          setting being ignored, and silence would leave an operator's write apparently
          disregarded with no clue why
    """
    global _cache, _cache_mtime

    path = override_path()
    try:
        mtime = os.path.getmtime( path )
    except OSError:
        _cache_mtime = None
        _cache       = { "approvers": None, "enforcement_active": None, "default_to_holding": None,
                         "approver_accounts": None }
        return _cache

    if mtime == _cache_mtime:
        return _cache

    try:
        with open( path, "r" ) as handle:
            body = json.load( handle )
        if not isinstance( body, dict ):
            raise ValueError( f"expected a JSON object, got {type( body ).__name__}" )
        _cache = {
            "approvers"          : body.get( "approvers" ),
            "enforcement_active" : body.get( "enforcement_active" ),
            "default_to_holding" : body.get( "default_to_holding" ),
            "approver_accounts"  : body.get( "approver_accounts" ),
        }
        _cache_mtime = mtime
    except Exception as error:
        print( f"[task-approval] override file {path} unusable ({error}) — falling back to config" )
        _cache       = { "approvers": None, "enforcement_active": None, "default_to_holding": None,
                         "approver_accounts": None }
        _cache_mtime = mtime

    return _cache


def _ini_value( key, return_type, fallback ):
    """
    Read one INI key, returning `fallback` when it is absent or the manager throws.

    Ensures:
        - returns the configured value, or `fallback`
        - never raises
    """
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        value      = config_mgr.get( key, return_type=return_type )
        return fallback if value is None else value
    except Exception:
        return fallback


def get_approvers():
    """
    The approver persona keys, canonicalized, always including the unconditional set.

    Requires:
        - nothing

    Ensures:
        - returns a frozenset of canonical persona keys
        - ALWAYS contains UNCONDITIONAL_APPROVERS, whatever the config says — an empty
          or truncated allowlist can never lock the fleet out of its own holding area
        - override file wins over the INI key; both are tolerated absent
        - a non-list override is ignored rather than raising (same tolerance as a
          corrupt file — this must not take the board down)
    """
    raw = _read_overrides()[ "approvers" ]
    if not isinstance( raw, list ):
        ini = _ini_value( INI_KEY_APPROVERS, "string", "" )
        raw = [ part for part in str( ini ).split( "," ) if part.strip() ]

    names = set( UNCONDITIONAL_APPROVERS )
    for entry in raw:
        if not isinstance( entry, str ) or not entry.strip(): continue
        names.add( canonical_persona_key( entry ) )
    return frozenset( names )


def get_enforcement_active():
    """
    Whether the approval gate REFUSES, or merely advises.

    Ensures:
        - returns a bool
        - override file wins over the INI key
        - FALLBACK IS False — an absent or broken config fails OPEN, deliberately
    """
    raw = _read_overrides()[ "enforcement_active" ]
    if raw is None:
        # "string" rather than "bool": the manager raises on a missing bool key in some
        # paths, and `_ini_value` would swallow that into the fallback anyway — reading
        # the text and comparing it here keeps the absent case and the false case
        # distinguishable at this level.
        raw = _ini_value( INI_KEY_ENFORCEMENT, "string", None )
        if raw is None: return FALLBACK_ENFORCEMENT_ACTIVE
        return str( raw ).strip().lower() in ( "true", "1", "yes", "on" )
    return bool( raw )


def get_approver_accounts():
    """
    The login-account -> approver-persona map, canonicalized on both sides.

    THE SHAPE, AND WHY IT IS A MAP RATHER THAN A LIST OF EMAILS. The refusal message
    and the audit trail both speak in personas; an account that grants approval has to
    say WHICH approver it is, or a reader of either would have to guess. A bare list
    would also make the two configs disagree in a way nobody could see: an email in the
    list whose persona is not in `task approval approver personas` would silently grant
    more than the allowlist does.

    Requires:
        - nothing

    Ensures:
        - returns a dict { lowercased-email : canonical persona key }
        - override file key `approver_accounts` (an object) wins over the INI key
        - INI form is comma-separated `email = persona` pairs; an entry missing its
          `=`, or blank on either side, is SKIPPED rather than raising — a typo in one
          pair must not take the whole map, and with it the browser's door, down
        - returns {} when unconfigured, which is today's behaviour written down
        - never raises
    """
    # `.get`, not `[ ]`: `_cache` is a module global that tests monkeypatch with a
    # dict of their own, and several existing files build it with only the keys they
    # care about. A KeyError here would fail those files for a key they never asked
    # about — the new reader breaking old callers, which is the defect this whole row
    # is about, one level down.
    raw = _read_overrides().get( "approver_accounts" )
    pairs = [ ]
    if isinstance( raw, dict ):
        pairs = list( raw.items() )
    else:
        ini = _ini_value( INI_KEY_APPROVER_ACCOUNTS, "string", "" )
        for part in str( ini ).split( "," ):
            if "=" not in part: continue
            email, persona = part.split( "=", 1 )
            pairs.append( ( email, persona ) )

    accounts = { }
    for email, persona in pairs:
        if not isinstance( email, str ) or not isinstance( persona, str ): continue
        email, persona = email.strip().lower(), persona.strip()
        if not email or not persona: continue
        accounts[ email ] = canonical_persona_key( persona )
    return accounts


def approver_persona_for_account( account_email ):
    """
    The approver persona a logged-in account speaks as, or None.

    Requires:
        - account_email is the email on a VALIDATED access token, or None

    Ensures:
        - returns None for None/blank/non-string, and for an unmapped account
        - returns None when the mapped persona is NOT currently an approver — the
          allowlist stays the single place that says who approves, so revoking a
          persona there revokes its accounts too, with no second edit to remember
        - matching is case-insensitive on the email
        - never raises
    """
    if not isinstance( account_email, str ) or not account_email.strip(): return None
    persona = get_approver_accounts().get( account_email.strip().lower() )
    if persona is None:                     return None
    if persona not in get_approvers():      return None
    return persona


def is_approver( actor ):
    """
    Whether `actor` may admit a row out of the holding area.

    Requires:
        - actor is the caller-declared "persona + session id" string, or None

    Ensures:
        - returns False for None/blank — an unnamed caller is never an approver
        - matches on the CANONICAL persona key, so "María 🌸 611e3c47", "maria" and
          "Maria" all resolve to the same entry (the actor string carries a session id
          suffix, so a raw equality test would never match anything)
        - never raises
    """
    if not isinstance( actor, str ) or not actor.strip(): return False
    approvers = get_approvers()
    # The actor string is "<persona words> <session-id-ish>". Try progressively shorter
    # leading word-runs so a multi-word persona ("mr radio") matches without the caller
    # having to know how many words its name has.
    words = actor.strip().split()
    for take in range( len( words ), 0, -1 ):
        if canonical_persona_key( " ".join( words[ :take ] ) ) in approvers: return True
    return False


def refusal_for_admission( from_status, to_status, actor, account_email=None ):
    """
    The gate's whole decision, as a pure function: the refusal detail, or None.

    WHY THIS IS NOT INLINE IN THE ROUTER, WHERE IT STARTED. Inline, the only way to
    watch it refuse is to stand up a database, mint a row in the holding area, and
    drive a PATCH — so the cheap tests would have had to assert on `is_approver`
    instead and CALL THAT the control. That is the fixture-that-cannot-discriminate
    shape this repo keeps finding: a correct predicate wired to nothing passes every
    such test. Pulled out here, all four clauses are observable directly, and the
    router test only has to prove the call happens.

    Requires:
        - from_status / to_status are status strings; actor is the caller-declared
          "persona + session id" string, or None
        - account_email is the email on the caller's VALIDATED access token, or None
          when the caller authenticated by API key (which carries no account)

    Ensures:
        - returns None when the transition is NOT an admission out of the holding
          area (any other from_status, and the not_approved -> not_approved no-op)
        - returns None when enforcement is off — the config is read at CALL time, so
          an operator's edit lands on the next request rather than the next deploy
        - returns None when the actor is an approver
        - returns None when the AUTHENTICATED ACCOUNT maps to a current approver —
          the browser's door, and the one a per-session actor string cannot open
        - otherwise returns a non-empty detail string naming the actor, the account it
          was authenticated as, the current allowlist, and BOTH ways to change each —
          a refusal that does not say how to proceed is a dead end wearing a 403
        - never raises
    """
    # TWO approver-only moves, not one.
    #
    #   ADMISSION  — out of the holding area onto a board.
    #   WON'T-FIX  — closing a row nobody will act on.
    #
    # 🔴 WON'T-FIX IS LOAD-BEARING, NOT TIDINESS (María, corrected by Rick 2026-09-02,
    # planning-is-prompting a1f2697). `wont_fix` COUNTS toward the create/close ratio
    # — `dropped` still does not — so a seat that could close rows this way would hold
    # both halves of a mint-by-deletion loop: close to raise the closed count, then
    # create against the headroom it just manufactured. Approver-only is what shuts
    # that, which makes THIS check the thing standing between the ratio gate and a
    # generator. ⚠️ A UI-only restriction hands every worker that loop; the button
    # must not be the control.
    if to_status == WONT_FIX_STATUS:
        move = f"closing a row as '{WONT_FIX_STATUS}'"
    elif from_status == NOT_APPROVED_STATUS and to_status != NOT_APPROVED_STATUS:
        move = f"admitting a row out of '{NOT_APPROVED_STATUS}'"
    else:
        return None

    if not get_enforcement_active(): return None
    if is_approver( actor ):         return None

    # THE BROWSER'S DOOR (row 9d3a975e). Checked SECOND, and its absence is why Rick
    # could not approve his own board: the transition endpoint has always resolved an
    # authenticated caller, and the gate had never been shown it. This reads an email
    # off a signature-validated token, so unlike the actor above it is not something a
    # caller can type.
    if approver_persona_for_account( account_email ) is not None: return None

    # NAME THE ACCOUNT, NOT ONLY THE ACTOR. The refusal Rick actually got named a
    # string he had never chosen and could not change, and listed personas he could not
    # become — so it read as a dead end. Whoever hits this next is told the one fact
    # that lets them act: which account the server believes they are.
    seen_as = account_email if account_email else "no login account (API-key caller)"
    return (
        f"'{actor}' is not an approver — {move} is limited to "
        f"{sorted( get_approvers() )}. The list is configuration, not code: edit "
        f"`{INI_KEY_APPROVERS}`, or the override file at {override_path()}. "
        f"You were authenticated as {seen_as}; a login account approves when "
        f"`{INI_KEY_APPROVER_ACCOUNTS}` maps it to one of those personas "
        f"(`<email> = <persona>`, comma-separated)."
    )


INI_KEY_DEFAULT_TO_HOLDING = "task approval new tickets start in holding area"

# ⚠️ FALLBACK IS False, AND THIS ONE IS THE MOST CONSEQUENTIAL FALSE IN THE MODULE.
# Turning it on redirects EVERY create fleet-wide into a queue somebody must work
# through by hand. That is a policy Rick turns on when he has watched the holding
# area work, not a default a deploy imposes on him — and the failure directions are
# not symmetric: wrong-ON silently buries every seat's filed work behind a human,
# wrong-OFF just leaves today's behaviour in place, visibly.
FALLBACK_DEFAULT_TO_HOLDING = False


def default_mint_status():
    """
    The status a create mints when the caller did not ask for one.

    WHY A FUNCTION AND NOT A FIELD DEFAULT. A Pydantic `Field( default=... )` is
    evaluated at import, so the flag would be frozen at boot and an operator's flip
    would need a restart — the exact asymmetry Rick objected to in the ratio gate,
    where the dials he could turn were the ones that changed nothing. Read at CALL
    time, a flip lands on the next request.

    Ensures:
        - returns "not_approved" when the holding-area default is ON
        - otherwise returns "queued" — today's behaviour, unchanged
        - never raises; an unreadable config yields "queued"
    """
    raw = _read_overrides()[ "default_to_holding" ]
    if raw is None:
        raw = _ini_value( INI_KEY_DEFAULT_TO_HOLDING, "string", None )
        if raw is None: on = FALLBACK_DEFAULT_TO_HOLDING
        else:           on = str( raw ).strip().lower() in ( "true", "1", "yes", "on" )
    else:
        on = bool( raw )
    return NOT_APPROVED_STATUS if on else "queued"
