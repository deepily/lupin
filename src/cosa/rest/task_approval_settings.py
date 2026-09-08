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

🔴 AND THE SECOND HONEST LIMIT, WHICH IS ABOUT THE FILE RATHER THAN THE ACTOR --
CORRECTING MY OWN WORDING IN `da6ae6f2`. That commit body says "DO NOT CHMOD THE
OVERRIDE FILE. It is writable by every seat", and both halves of that sentence are
wrong in a way that matters. It is NOT world-writable: measured 2026-09-07, the live
file is `-rw-rw-r-- 1001 1001`, so `other` cannot write it at all.

⇒ The real fact is that PERMISSIONS ARE NOT THE INSTRUMENT HERE, because there is
nobody for them to discriminate between. Measured the same evening: the host user is
uid **1001**, and `lupin-rest-dev` and `lupin-rest-test` BOTH run as uid **1001**. Every
writer on this deployment -- the app in either container, and every Claude seat on the
host -- is the same UID. A mode change cannot express "someone else may not write this"
when there is no someone else.

⇒ SO THE FILE LAYER HAS NO ENFORCEABLE BOUNDARY ON THIS DEPLOYMENT, and no chmod can
give it one. This is ABSENT PROCESS ISOLATION, not a permissions bug, and the fix is a
deployment change (a distinct service UID) rather than a mode. María 🌸 made exactly
this correction; recorded here because a retraction has to reach the artifact, and the
sentence it corrects is in a commit body nobody can edit.

⚠️ The DO-NOT-CHMOD advice still stands, for its OTHER reason, which was sound: the app
writes this file at runtime via `set_manager_pull_disabled`, so read-only would break
the admin endpoint that carries out the operator's order.

⚠️ NOT UNIT-TESTABLE, AND SAID RATHER THAN QUIETLY SKIPPED. Every fact above is a
property of the deployment -- container UIDs, a mount, a file mode -- not of this
module. A test asserting them would pass or fail on where it ran, which is the
wrong-tree defect this repo documents at length. Filed as a defect row instead.

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

import hashlib
import hmac
import json
import os

from cosa.config.configuration_manager import ConfigurationManager
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
from cosa.rest.task_store_rules import NOT_APPROVED_STATUS, PARK_STATUS, WONT_FIX_STATUS
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

# ---------------------------------------------------------------------------
# THE STAMP (row a5bf74ff item D) — Rick ruled it 2026-09-08 ~15:47 EDT
# ---------------------------------------------------------------------------
#
# 🔴 WHAT IT IS FOR, AND IT IS NOT HYPOTHETICAL. At ~15:50 on 2026-09-08 this file was
# found reading `manager_pull_disabled: false` — Rick's rescission, which he ordered
# switched ON and which the validated setter had written as `true`, was OFF. Nobody
# knew. There was no audit trail, and by the time it was noticed the mtime evidence had
# been destroyed by restoring the correct value. The stamp exists so that the NEXT time
# this happens the server says so out loud instead of quietly honouring it.
#
# ⚠️ POLICY CONTROL, NOT A SECURITY BOUNDARY — the same words `refusal_for_admission`
# uses about itself, and for the same reason. Every Claude seat runs as `rruiz` and can
# read this module, so a determined caller reads the scheme and forges a stamp. What it
# stops is the MISTAKE: a stray test fixture, a hand-edit, a half-finished experiment.
# Do not write a test asserting a forged stamp is refused; that would assert something
# the design does not deliver.
#
# 🔴 AND THE REFUSAL IS PER-KEY, WHICH IS THE WHOLE DESIGN. A blanket "ignore an
# unstamped file" would be FAIL-OPEN on `enforcement_active`, whose fallback is False by
# deliberate policy (see FALLBACK_ENFORCEMENT_ACTIVE above) — an unstamped file would
# silently switch the holding-area gate OFF, which is strictly worse than the hole being
# closed. So an unstamped override is REFUSED only where refusing lands on the CLOSED
# side, and merely REPORTED elsewhere. The table is explicit rather than derived,
# because getting one entry wrong here is a silent policy change.
STAMP_KEY = "_stamp"

# Refusing an unstamped value for these keys lands on their fallback, and that fallback
# is the SAFE direction. `manager_pull_disabled` falls back to True = pulling frozen =
# Rick's rescission, so refusing an unstamped override PRESERVES his order rather than
# dropping it.
STAMP_ENFORCED_KEYS = ( "manager_pull_disabled", )


def _stamp_secret():
    """
    The signing secret, or None when this process has none.

    Requires:
        - nothing; safe to call at any time

    Ensures:
        - returns the JWT signing secret when set, else None
        - NEVER raises, and never has a default — a hardcoded fallback secret would make
          every stamp forgeable by anyone reading this file, which is worse than no stamp

    ⚠️ REUSING `JWT_SECRET_KEY` ADDS NO NEW FAILURE MODE, and that was checked rather
    than assumed (Krishna 🦚, 2026-09-08): `env -u JWT_SECRET_KEY` already exits 1 with a
    ValueError at `jwt_service.py:128-129`, with a positive control importing fine when
    it is set. A server that cannot sign settings already cannot sign tokens and already
    refuses to boot — so "absent" is not a state a running server can be in, which is
    why nothing here has to decide a gate on its absence.
    """
    return os.getenv( "JWT_SECRET_KEY" )


def _expected_stamp( body ):
    """
    The stamp `body` should carry, or None when this process cannot compute one.

    Requires:
        - body is the override dict, with or without its own STAMP_KEY

    Ensures:
        - returns a hex HMAC-SHA256 over the canonical JSON of every key EXCEPT the
          stamp itself — sorted keys and fixed separators, so re-serialising an
          unchanged file cannot change its stamp
        - returns None when no secret is available, so callers can distinguish
          "cannot check" from "checked and wrong". Those are different facts and a
          caller acts differently on each
        - never raises on an unserialisable body — it reports and returns None, because
          a settings file must not take the board down
    """
    secret = _stamp_secret()
    if secret is None: return None

    payload = { k: v for k, v in body.items() if k != STAMP_KEY }
    try:
        canonical = json.dumps( payload, sort_keys=True, separators=( ",", ":" ) )
    except ( TypeError, ValueError ) as error:
        print( f"[task-approval] override body is not serialisable ({error}) — cannot stamp it" )
        return None

    return hmac.new( secret.encode( "utf-8" ), canonical.encode( "utf-8" ), hashlib.sha256 ).hexdigest()


def _stamp_is_valid( body ):
    """
    Whether `body` carries a stamp this process can verify AND that verifies.

    Ensures:
        - returns True only when a secret exists, a stamp is present, and the two agree
          under a CONSTANT-TIME comparison
        - returns False when the stamp is absent, wrong, or not a string
        - returns None when this process cannot check at all (no secret) — deliberately
          a THIRD value, never False, because "unverifiable" and "forged" would otherwise
          be indistinguishable and the caller would treat a keyless dev box as an attack
    """
    expected = _expected_stamp( body )
    if expected is None: return None

    found = body.get( STAMP_KEY )
    if not isinstance( found, str ): return False

    return hmac.compare_digest( found, expected )


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
        - returns a dict with keys "approvers" / "enforcement_active" /
          "default_to_holding" / "approver_accounts" / "manager_pull_disabled",
          each a value or None
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
                         "approver_accounts": None, "manager_pull_disabled": None }
        return _cache

    if mtime == _cache_mtime:
        return _cache

    try:
        with open( path, "r" ) as handle:
            body = json.load( handle )
        if not isinstance( body, dict ):
            raise ValueError( f"expected a JSON object, got {type( body ).__name__}" )

        # 🔴 THE STAMP CHECK (row a5bf74ff item D). Three outcomes, and they are three
        # different facts — collapsing any two of them is how this goes wrong:
        #   None  this process has no secret, so it CANNOT check. Honour everything and
        #         say nothing: a keyless dev box is not an attack, and refusing here
        #         would make the absence of a key decide a gate, which is exactly what
        #         Rick's ruling removed.
        #   True  stamped by the server's own writer. Honour everything, silently.
        #   False absent or wrong. Somebody wrote this file by a path that is not the
        #         validated writer. SAY SO LOUDLY, and refuse ONLY the keys whose
        #         fallback is the closed side (STAMP_ENFORCED_KEYS).
        verdict = _stamp_is_valid( body )
        if verdict is False:
            print(
                f"[task-approval] 🔴 override file {path} is UNSTAMPED or its stamp does not "
                f"verify — it was not written by the validated writer. Keys {list( STAMP_ENFORCED_KEYS )} "
                f"are being IGNORED (they fall back to the closed side); the rest are honoured "
                f"because refusing them would fail OPEN. Rewrite via PATCH /api/tasks/approval-settings."
            )

        _cache = {
            "approvers"          : body.get( "approvers" ),
            "enforcement_active" : body.get( "enforcement_active" ),
            "default_to_holding" : body.get( "default_to_holding" ),
            "approver_accounts"  : body.get( "approver_accounts" ),
            "manager_pull_disabled" : body.get( "manager_pull_disabled" ),
        }
        if verdict is False:
            for key in STAMP_ENFORCED_KEYS: _cache[ key ] = None
        _cache_mtime = mtime
    except Exception as error:
        print( f"[task-approval] override file {path} unusable ({error}) — falling back to config" )
        _cache       = { "approvers": None, "enforcement_active": None, "default_to_holding": None,
                         "approver_accounts": None, "manager_pull_disabled": None }
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
        - a STRING is PARSED, never coerced: "false" / "no" / "0" / "off" all mean False
        - an UNPARSEABLE value is REPORTED and falls through to the next layer rather
          than being read as False — it is not a decision, so it must not make one
        - FALLBACK IS False — an absent or broken config fails OPEN, deliberately

    🔴 WHY THIS DELEGATES RATHER THAN CARRYING ITS OWN PARSE. `e98659d2` fixed the
    `bool( "false" )` half here and the string case has been correct since. What it
    left was the JUNK case: `"banana"` fell through the `in ( "true", ... )` membership
    test and came out False, silently — indistinguishable from a deliberate "off", and
    pointing toward enforcement OFF.

    ⇒ Same defect, second half. `_as_bool_or_none` is where it was already solved for
    the pull toggle, and a THIRD hand-rolled parse in this file is exactly how the
    first two drifted apart. There is now ONE, and a guard enforces that by PREDICATE
    rather than by naming today's readers — see
    `test_one_boolean_parser_for_every_surface.py`.
    """
    value = _as_bool_or_none( _read_overrides()[ "enforcement_active" ],
                              f"override file {override_path()}" )
    if value is not None: return value

    value = _as_bool_or_none( _ini_value( INI_KEY_ENFORCEMENT, "string", None ),
                              f"config key '{INI_KEY_ENFORCEMENT}'" )
    if value is not None: return value

    return FALLBACK_ENFORCEMENT_ACTIVE


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
        - returns None when the transition is none of the three approver-only moves:
          an admission out of the holding area, a won't-fix close, or a demote back
          into the holding area (the not_approved -> not_approved no-op is neither an
          admission nor a demote, and is left to the legal-edge graph to refuse)
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
    # THREE approver-only moves, not one.
    #
    #   ADMISSION  — out of the holding area onto a board.
    #   WON'T-FIX  — closing a row nobody will act on.
    #   DEMOTE     — back INTO the holding area, off the active list.
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
    # -- DEMOTE: THE HOLDING AREA'S ENTRANCE (Rick's P0, 2026-09-07, row d8be585a) --
    #
    # Rick, by voice: "I want to be able to demote out of the active task list items
    # that I don't think merit being in the active task list."
    #
    # 🔴 IT IS GUARDED FOR THE SAME REASON ADMISSION IS, READ IN THE OTHER DIRECTION.
    # Admission turns a filed row into somebody's owed work; a demote takes somebody's
    # owed work OFF the board. Both change what the fleet is actually doing, so both
    # are the operator's or a manager's call -- and a worker able to demote its own
    # assigned row could quietly clear its board without ever closing anything.
    #
    # ⚠️ NOTHING GUARDED THIS BEFORE. Measured 2026-09-07: both clauses above key on
    # `from_status == NOT_APPROVED_STATUS`, i.e. admission OUT, so a demote -- which is
    # admission IN -- fell through to the `else` and was refused by nothing at all. The
    # client has carried a demote control since 9298715c and its only restraint was
    # JavaScript, which is presentation and not a control: anything posting straight to
    # the API bypassed it.
    #
    # The `to_status != from_status` clause is the mirror of the one above it, for the
    # same reason: the no-op is already an illegal edge in LEGAL_TRANSITIONS, and
    # answering it with a permission refusal would name the wrong defect.
    elif to_status == NOT_APPROVED_STATUS and from_status != NOT_APPROVED_STATUS:
        move = f"demoting a row back into '{NOT_APPROVED_STATUS}'"
    # -- UN-PARK: THE FOURTH APPROVER-ONLY MOVE (Rick's P0, row 03d3bf78, 2026-09-08) --
    #
    # Rick, by voice: "I need to be able to un-park a ticket that's currently parked,
    # that is I want to make it available for you to work on." Asked whether the verb
    # should be approver-only or open to anyone who can edit the row, he chose
    # APPROVER-ONLY -- and against my recommendation, which I had argued from the fact
    # that un-park only reaches a state the row provably already held.
    #
    # 🔴 HIS CALL IS THE BETTER ONE AND HERE IS THE ARGUMENT I MISSED. I reasoned about
    # where the row LANDS; the control is about who decides what the fleet WORKS ON.
    # Park and demote are both approver-only, and both are ways of taking work off the
    # board. Un-park is the way of putting it back. Leaving the reverse of two guarded
    # moves unguarded would let a worker restore its own parked row the moment nobody
    # was looking -- re-admitting work the operator had deliberately set down.
    #
    # ⚠️ AND IT MUST BE HERE, NOT IN THE BUTTON. The demote comment three clauses up
    # records exactly this being got wrong: the client carried the control and "its
    # only restraint was JavaScript, which is presentation and not a control." This
    # verb ships to TWO clients, so a UI-only rule would have to be got right twice.
    elif from_status == PARK_STATUS and to_status != PARK_STATUS:
        move = f"un-parking a row out of '{PARK_STATUS}'"
    else:
        return None

    if not get_enforcement_active(): return None

    # 🔨 THE ACTOR DOOR IS CLOSED HERE, DELIBERATELY. Rick ruled it 2026-09-07 ~21:47
    # EDT by keypress, row b8205986, verbatim from the option he clicked: "Close it —
    # require a real account." María 🌸 then ruled the SHAPE, 2026-09-07 ~22:03: drop
    # the actor door outright and read the persona off the validated account, rather
    # than merely requiring that SOME account be present.
    #
    # 🔴 SO `actor` IS DELIBERATELY NOT CONSULTED FOR AUTHORIZATION, AND THAT IS NOT AN
    # OVERSIGHT. It reads like one — the parameter is right there and `is_approver`
    # sits three functions up — so a later reader will be tempted to "restore" the
    # check. Do not. The line that used to be here was
    #
    #     if is_approver( actor ): return None
    #
    # and it made a CALLER-DECLARED STRING the authorization. Measured 2026-09-07 as a
    # pure function, all three moves, identical: actor="maria e2908f90" with no account
    # was ALLOWED, while the same call with a real but unmapped account was refused.
    # Anyone holding the shared fleet API key admitted, won't-fixed or demoted any row
    # by typing an approver's name.
    #
    # ⚠️ WHY "REQUIRE AN ACCOUNT TO BE PRESENT" WAS NOT ENOUGH, since it is the obvious
    # smaller fix and was considered: `account_email and is_approver( actor )` closes
    # the measured case and leaves the same defect keyed on "have any login" — a caller
    # with any validated token could still declare themselves an approver. Rick said
    # "close it", not "narrow it".
    #
    # ⇒ `actor` survives on this path for the LEDGER, not for the gate: the refusal
    # names it so a human can see who claimed what, and `recorded_actor` writes it
    # beside the server-known identity. Naming and authorizing are different jobs.
    #
    # ⚠️ SCOPE — SUPERSEDED, and left in place with its retraction so the reasoning is
    # still auditable. This note used to read that `refusal_for_pull` STILL CONSULTS
    # `is_approver`, that the pull was a fourth surface never put to Rick, and that
    # changing it would be "building past the ruling". That was true when written and
    # is false now: the fourth path WAS put to him and he ruled "close the pull hole"
    # (2026-09-08 ~10:39 EDT). `refusal_for_pull` no longer consults `is_approver`, and
    # it carries its own do-not-restore note. Do not act on the sentence above.

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
        f"{move} requires a LOGIN ACCOUNT that maps to an approver. You were "
        f"authenticated as {seen_as}, which does not. "
        f"⚠️ The name you sent as `actor` ('{actor}') is recorded but confers "
        f"nothing — Rick closed that door on 2026-09-07 (row b8205986) because it was "
        f"caller-declared, so anyone could type an approver's name. "
        f"To proceed: sign in with an account that "
        f"`{INI_KEY_APPROVER_ACCOUNTS}` maps to one of {sorted( get_approvers() )} "
        f"(`<email> = <persona>`, comma-separated), or ask one of them to make this "
        f"move. Both lists are configuration, not code: `{INI_KEY_APPROVERS}` and "
        f"`{INI_KEY_APPROVER_ACCOUNTS}`, or PATCH /api/tasks/approval-settings, which "
        f"is the only sanctioned way to change them."
    )


# ── NO MANAGER BATCHES (Rick, 2026-09-04) ──────────────────────────────────────
#
# "A manager should never be able to fire a batch. They should only ever request 1
# ticket at a time." Batch approve and batch won't-fix are RICK-ONLY, and the refusal
# is SERVER-SIDE — a UI that merely hides the button is not the control, which is this
# module's own standing position about won't-fix.
#
# 🔴 THERE IS NOTHING TO REFUSE AT THE REQUEST LEVEL, AND THAT IS THE WHOLE DIFFICULTY.
# Measured 2026-09-04: 14 task routes, 10 distinct paths, ZERO batch or bulk doors, and
# no task model carrying a list of row ids — verified with a positive control (the same
# search finds admin/users/batch-delete), so the zero is evidence rather than silence.
# The UI's batch approve is a CLIENT-SIDE LOOP (`notifications.js _applyHoldingBatch`)
# firing N single-row transitions. Each one is well-formed and byte-indistinguishable
# from somebody approving one ticket.
#
# ⇒ So the only thing that distinguishes a batch is CARDINALITY OVER TIME, counted from
# the append-only event trail. A window of one means "one ticket at a time" literally.
INI_KEY_ADMISSION_WINDOW = "task approval admission window seconds"

# ⚠️ FALLBACK IS 0 — OFF — AND THE DIRECTION IS DELIBERATE, matching every other flag in
# this module. An absent or unreadable config must not silently start refusing an
# approver's second ticket; turning a throttle ON is an explicit act. Wrong-OFF leaves
# today's behaviour visibly in place, wrong-ON quietly blocks the people doing the work.
FALLBACK_ADMISSION_WINDOW_SECONDS = 0


def get_admission_window_seconds():
    """
    How long a non-exempt approver must wait between admissions. 0 disables the rule.

    Read at CALL time, like every other key here, so an operator's edit lands on the next
    request rather than the next deploy.

    Ensures:
        - returns a non-negative int; 0 means the rule is off
        - a negative or unparseable value reads as 0 rather than raising, because a
          malformed throttle must fail OPEN for the same reason the flags above do
        - never raises
    """
    raw = _ini_value( INI_KEY_ADMISSION_WINDOW, "int", FALLBACK_ADMISSION_WINDOW_SECONDS )
    try:
        seconds = int( raw )
    except ( TypeError, ValueError ):
        return 0
    return seconds if seconds > 0 else 0


def refusal_for_batch( actor, account_persona, recent_admissions ):
    """
    The batch rule's whole decision, as a pure function: the refusal detail, or None.

    Pure and separate from the count for the same reason `refusal_for_admission` is
    separate from the router: every clause is observable without standing up a database,
    so the tests that matter cannot degrade into asserting on a predicate that is wired
    to nothing.

    Requires:
        - actor is the caller-declared actor string
        - account_persona is the approver persona the caller's LOGIN ACCOUNT resolved to,
          or None
        - recent_admissions is how many rows this caller has already admitted inside the
          window (0 when the rule is off, or when nothing was counted)

    Ensures:
        - returns None when the window is 0 (rule off)
        - returns None when the caller is ask-exempt — Rick may batch; the ruling is that
          MANAGERS may not, and batch approve is HIS control
        - returns None when recent_admissions is 0 — the first ticket always passes, which
          is what "one ticket at a time" means
        - otherwise a non-empty detail naming the count, the window, and the dial, so a
          manager who meets it can tell a throttle from a permissions problem
        - never raises
    """
    window = get_admission_window_seconds()
    if window <= 0: return None

    # 🔴 EXEMPTION KEYED ON THE PERSONA, NOT ON "HAS AN ACCOUNT". Rick's ruling restricts
    # MANAGERS; batch approve is his own control and he must keep it. A manager who has a
    # login account is still a manager. This is the same distinction — and deliberately
    # the same list — that decides who skips the promotion ask, because both answer "is
    # this Rick?" rather than "may this caller approve?".
    from cosa.rest.task_promotion_gate import ASK_EXEMPT_PERSONAS
    if account_persona in ASK_EXEMPT_PERSONAS: return None

    if not recent_admissions: return None

    return (
        f"'{actor}' has already admitted {recent_admissions} row(s) out of "
        f"'{NOT_APPROVED_STATUS}' in the last {window}s — one ticket at a time. Batch "
        f"approve and batch won't-fix are limited to {sorted( UNCONDITIONAL_APPROVERS )}. "
        f"This is a THROTTLE, not a permissions problem: wait {window}s and the same "
        f"request will succeed. The window is configuration, not code: edit "
        f"`{INI_KEY_ADMISSION_WINDOW}` (0 disables it) — that key has no endpoint yet, "
        f"so the config file is still its only door."
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
        - a STRING is PARSED, never coerced
        - an UNPARSEABLE value is REPORTED and falls through rather than deciding
        - never raises

    🔴 THIS WAS THE LIVE `bool( "false" )` DEFECT IN THIS MODULE, AND IT WAS NOT THE
    ONE EVERYBODY WAS LOOKING AT. The override branch read `on = bool( raw )`, and
    `bool( "false" )` is True — so an operator who hand-wrote
    `"default_to_holding": "false"` turned the holding-area default ON, the switch
    doing the opposite of what its own file said.

    MEASURED 2026-09-08 against the shipped reader, `override_path` pointed at a temp
    file, cache forced to re-read, WITH a positive control proving the injection moved
    the answer at all (True -> not_approved, False -> queued):

        'false' -> not_approved        'no' -> not_approved
          'off' -> not_approved         '0' -> not_approved

    ⚠️ AND MY FIRST PROBE OF THIS MEASURED NOTHING. It injected into `_cache` with a
    fabricated mtime; the live file exists, so `_read_overrides` re-read from disk and
    discarded the injection every time. Every row came back identical — which reads as
    "the defect is everywhere" and actually meant the fixture had no effect. A uniform
    column is the tell, and the positive control above is why the second probe counts.

    ⚠️ THE FILE'S OWN PROSE POINTED AT THE WRONG FUNCTION WHILE THIS SAT HERE.
    `get_manager_pull_disabled`'s docstring said the defect was "live TODAY in
    `get_enforcement_active` directly above" — true when written, fixed by `e98659d2`,
    never re-aimed. A reader following it landed on correct code 140 lines from the
    real one. Both notes are corrected in the same commit as this fix.
    """
    on = _as_bool_or_none( _read_overrides()[ "default_to_holding" ],
                           f"override file {override_path()}" )
    if on is None:
        on = _as_bool_or_none( _ini_value( INI_KEY_DEFAULT_TO_HOLDING, "string", None ),
                               f"config key '{INI_KEY_DEFAULT_TO_HOLDING}'" )
    if on is None:
        on = FALLBACK_DEFAULT_TO_HOLDING
    return NOT_APPROVED_STATUS if on else "queued"


# ── THE MANAGER PULL TOGGLE (Rick's P0, row 458e9947, 2026-09-06) ──────────────
#
# HIS WORDS, and the polarity is his: "when the toggle is off managers can pull,
# when the toggle is on managers can't pull." So the stored flag is DISABLED-when-
# True. It is named for what it does rather than for the switch's label, because a
# flag called `pull_enabled` holding the switch's own position is how an inverted
# read ships.
#
# HIS MOTIVE, which defines done: a manager loaded up on task items in one session
# and it displaced the P0 work. "I want to be able to turn it off momentarily while
# you guys focus on what I deem to be the most important tasks."
#
# 🔴 THIS GATES TAKING, NOT FILING, AND THAT IS THE WHOLE POINT OF A SEPARATE GATE.
# Rick, when asked: "We already have a gate to the creation of new tasks. It's called
# the fucking task gate." He is right — the flow-ratio gate refuses `task_create`
# fleet-wide already. Nothing whatsoever gated a caller MOVING an existing row into
# `in_progress`, which is the door his incident actually came through.
#
# MEASURED BEFORE BUILDING (Tiffany 💍, b6031094, main checkout, by content):
# the holding-area predicate `item.status == NOT_APPROVED_STATUS` sits at exactly two
# sites and both also require `to_status != NOT_APPROVED_STATUS`, so both fire ONLY on
# admission OUT of the holding area. For `queued -> in_progress` the first clause is
# False at both, so NEITHER runs — not rarely, never. The predicate tests the row's
# CURRENT status against one literal, so it is STRUCTURALLY incapable of matching;
# that is why this needed a new gate rather than a switch wired to an existing one.
#
# ⚠️ AND A CLIENT-SIDE CHECKBOX COULD NOT HAVE DONE IT (María 🌸's point, and it is
# the design's real trap). The flag is read SERVER-SIDE at call time, so the checkbox
# is a remote control rather than the control. A browser-only toggle would gate the UI
# while `task_transition` kept working from every MCP session — which is exactly the
# path the incident took.

INI_KEY_MANAGER_PULL_DISABLED = "task approval manager pull disabled"

# 🔨 FAILS CLOSED -- RICK'S DIRECT ORDER, 2026-09-07 ~21:25 EDT, broadcast c43a29c5,
# row 1ec67228. THIS CONSTANT USED TO BE False, AND THE REASONING FOR THAT IS KEPT
# BELOW RATHER THAN DELETED, because it was sound and it was OVERRULED rather than
# found wrong.
#
# It read: "an absent or unreadable config must not silently freeze every seat's
# ability to take work. The cost of a wrong False is that Rick's quiet hour is not
# enforced and he says so; the cost of a wrong True is a fleet that cannot work and
# cannot see why."
#
# 🔴 THE OPERATOR HAS NOW PRICED THAT TRADE HIMSELF, AND HE PRICED IT THE OTHER WAY:
# "I want to rescind the feature that allows you to pull from the holding area into
# the queue and it must default to NO. That way you can never do it without my
# approval. I run the fucking board." A frozen fleet is loud, immediate, and asks him
# a question; work quietly entering the live queue without him is none of those. He
# would rather be asked than surprised, and pricing that trade is his call, not this
# module's.
#
# ⚠️ STATE IS NOT DEFAULT, AND THAT DISTINCTION IS THE WHOLE REASON THIS CONSTANT HAD
# TO CHANGE AT ALL. The live override was flipped True on his keypress the same
# evening, which protects him TODAY and protects nothing about a fresh install, a
# reset config, a redeployed container, or a wiped override file -- every one of which
# would have resurrected the old default with nobody told. A runtime flip is a fact
# about now; this constant is the fact about always.
FALLBACK_MANAGER_PULL_DISABLED = True

PULL_TARGET_STATUS = "in_progress"

TRUE_WORDS  = ( "true",  "1", "yes", "on"  )
FALSE_WORDS = ( "false", "0", "no",  "off" )


def _as_bool_or_none( raw, where ):
    """
    Parse one configured boolean STRICTLY: True, False, or None for "says nothing".

    🔴 WHY AN UNRECOGNIZED VALUE IS `None` AND NOT `False`. This replaces a tail that
    ended `return bool( raw )` with a membership test above it, and BOTH of those fail
    OPEN on junk: `"banana"`, `""`, `0`, `[]` and `{}` were every one of them read as
    False -- i.e. "pulling is allowed". Measured 2026-09-07 against the shipped reader,
    all five opened the gate. So a hand-edited override file with a typo in the VALUE
    silently restored the capability Rick rescinded, which is the missing-INI-key defect
    of row 1ec67228 one layer further in.

    ⚠️ AND IT IS THE MIRROR OF THE `bool( "false" )` TRAP ALREADY NAMED IN
    `get_manager_pull_disabled`. That one is a string the reader understands BACKWARDS;
    this is a string it does not understand AT ALL. Fixing the first and leaving the
    second is how the hole survived -- an unrecognized word fell through the `in (...)`
    test and came out False, which is indistinguishable from a deliberate "off".

    ⇒ A value nobody can parse is not a decision. Returning None hands the question to
    the next layer down, ending at that setting's own fallback.

    ⚠️ AND THE FALLBACK IS NOT ONE VALUE ANY MORE, WHICH THIS NOTE USED TO ASSUME.
    Written for the pull toggle alone, it said the fall-through ends at
    `FALLBACK_MANAGER_PULL_DISABLED`, "which is closed". Since 2026-09-08 this parser
    serves THREE keys and their fallbacks point opposite ways:

        FALLBACK_MANAGER_PULL_DISABLED   True    fails CLOSED  (Rick's rescission)
        FALLBACK_ENFORCEMENT_ACTIVE      False   fails OPEN    (deliberate)
        FALLBACK_DEFAULT_TO_HOLDING      False   fails OPEN

    ⇒ So "returning None is the safe direction" is TRUE OF THE PULL KEY and is not a
    property of this function. For the other two, an unparseable value falls through to
    a gate that is OFF. That is the pre-existing policy for those settings, not a
    regression introduced here — but a reader must not carry the pull key's reassurance
    across to them. The corrected sentence is the general one: this parser DECLINES to
    decide, and what happens next is the caller's fallback, which each caller states.

    ⚠️ STRICT ABOUT NON-STRINGS TOO, including a bare JSON `0` or `1`. An operator who
    means false and writes `0` gets the toggle left CLOSED and a printed line telling
    them why -- the safe direction, and a loud one. The validated write path
    (`set_manager_pull_disabled`) refuses anything but a real bool, so nothing this
    codebase writes can ever arrive here as a number.

    Requires:
        - `where` names the source, for the operator who has to go and fix it

    Ensures:
        - returns True / False for a real bool, or for one of TRUE_WORDS / FALSE_WORDS
          (case- and whitespace-insensitive)
        - returns None for absent, and for ANY other value -- including a truthy one
        - REPORTS an unparseable value on stdout, the same courtesy a corrupt override
          file already gets. A setting that is ignored in silence is how an operator
          concludes the switch itself is broken
        - never raises
    """
    if raw is None:             return None
    if isinstance( raw, bool ): return raw
    if isinstance( raw, str ):
        word = raw.strip().lower()
        if word in TRUE_WORDS:  return True
        if word in FALSE_WORDS: return False

    print(
        f"[task-approval] {where} holds {raw!r}, which is not a boolean -- ignoring it "
        f"and falling through. Write true/false (or one of {TRUE_WORDS + FALSE_WORDS})."
    )
    return None


def get_manager_pull_disabled():
    """
    Whether pulling work into `in_progress` is currently switched OFF.

    Ensures:
        - returns a bool
        - the override file wins over the INI key, and is re-read when its mtime moves,
          so an operator's flip lands on the NEXT REQUEST rather than the next deploy
        - FALLBACK IS True — an absent or broken config fails CLOSED, by the
          operator's ruling of 2026-09-07 (row 1ec67228). See the constant.
        - a STRING in the override file is parsed, never coerced: "false" / "no" / "0"
          / "off" all mean False
        - never raises

    🔴 WHY THE STRING CASE IS HANDLED RATHER THAN `bool( raw )`. `bool( "false" )` is
    True, so a hand-written `"manager_pull_disabled": "false"` would turn the toggle ON
    while the operator believed they had turned it off — the switch doing the opposite
    of what its own file says.

    ⚠️ THIS PARAGRAPH USED TO NAME `get_enforcement_active` AS CARRYING THAT DEFECT
    "TODAY". That was true when written and stopped being true at `e98659d2`, and the
    sentence was never re-aimed — so for two days it sent a reader to correct code
    while the REAL live instance sat 140 lines further down in `default_mint_status`,
    unmentioned. Both are on `_as_bool_or_none` as of 2026-09-08.

    ⇒ The durable lesson is not about this key: a prose pointer at a defect goes stale
    the moment somebody fixes it, and nothing reddens when it does. That is why the
    guard for this is now a PREDICATE over the module's own syntax
    (`test_one_boolean_parser_for_every_surface.py`) rather than a sentence naming
    today's offenders — a fifth surface written next month trips it; a paragraph
    listing four names would not.
    """
    value = _as_bool_or_none( _read_overrides()[ "manager_pull_disabled" ],
                              f"override file {override_path()}" )
    if value is not None: return value

    value = _as_bool_or_none( _ini_value( INI_KEY_MANAGER_PULL_DISABLED, "string", None ),
                              f"config key '{INI_KEY_MANAGER_PULL_DISABLED}'" )
    if value is not None: return value

    return FALLBACK_MANAGER_PULL_DISABLED


def actor_is_claiming_their_own_row( actor, item_owner, item_manager ):
    """
    Whether this pull is a worker picking up work ALREADY ASSIGNED TO THEM.

    🔨 MARÍA 🌸 RULED THIS, 2026-09-07 ~22:02 EDT, and the trigger was the gate refusing
    her own instruction: she told Sam to move row 1ec67228 into `in_progress` and the
    store answered 409, because a worker is not an approver and EVERY transition into
    `in_progress` is a "pull". Rick's order is about a manager PULLING NEW WORK out of
    the holding area onto the board. A worker starting the row a manager already handed
    them is a different act, and the toggle could not tell them apart.

    HER RULE, both halves required — she was explicit that the second is not decorative:
        - the actor IS the row's owner, AND
        - the row's accountable manager is SOMEBODY ELSE

    🔴 WHY THE SECOND HALF MATTERS. Without it a manager who owns a row is exempt from
    the switch on that row, which is precisely the self-assignment Rick rescinded — the
    exemption would let anyone create work for themselves and then start it. Requiring
    a DIFFERENT manager means somebody else put the row on this actor's board, which is
    the whole thing the toggle exists to guarantee.

    ⚠️ THIS IS A POLICY CONTROL, NOT A BOUNDARY, AND FOR THE SAME REASON AS EVERYTHING
    ELSE KEYED ON `actor` IN THIS MODULE: the actor is caller-DECLARED. A caller who
    types the owner's name claims the exemption. It stops a worker taking someone
    else's row by habit; it does not stop one who decides to. Rick has ruled the actor
    door closed for admit / won't-fix / demote (row b8205986); when that lands, this
    clause should be brought onto whatever identity those three end up using rather
    than left behind on the weak one.

    Requires:
        - actor is the caller-declared "persona + session id" string, or None
        - item_owner / item_manager are persona strings off the row, or None

    Ensures:
        - returns False unless BOTH halves hold — an unowned row, an unmanaged row, a
          row whose owner and manager are the same persona, and a caller who is not the
          owner all get False
        - matches on the CANONICAL persona key, so "María 🌸 611e3c47" and "maria" are
          the same person, exactly as `is_approver` does it
        - never raises
    """
    if not isinstance( actor, str )        or not actor.strip():        return False
    if not isinstance( item_owner, str )   or not item_owner.strip():   return False
    if not isinstance( item_manager, str ) or not item_manager.strip(): return False

    owner   = canonical_persona_key( item_owner )
    manager = canonical_persona_key( item_manager )
    if not owner or owner == manager: return False

    # The actor carries a trailing session id, so try each leading prefix — the same
    # walk `is_approver` uses, and for the same reason: "sam b29ad216" is "sam".
    words = actor.strip().split()
    for take in range( len( words ), 0, -1 ):
        if canonical_persona_key( " ".join( words[ :take ] ) ) == owner: return True
    return False


def refusal_for_pull( from_status, to_status, actor, account_email=None,
                      item_owner=None, item_manager=None, reason=None ):
    """
    The pull toggle's whole decision, as a pure function: the refusal detail, or None.

    Pulled out of the router for the reason `refusal_for_admission` was: inline, the
    only way to watch it refuse is to stand up a database and drive a PATCH, so the
    cheap tests would have had to assert on the flag getter instead and call THAT the
    control — the fixture-that-cannot-discriminate shape. Here every clause is
    observable directly and the router test only has to prove the call happens.

    Requires:
        - from_status / to_status are status strings; actor is the caller-declared
          "persona + session id" string, or None
        - account_email is the email on the caller's VALIDATED access token, or None

    Ensures:
        - returns None when the transition is not INTO `in_progress` — this gate has
          one edge and takes no interest in any other
        - returns None for the `in_progress -> in_progress` no-op, so a re-PATCH of a
          row already being worked is never refused by a switch flipped after it started
        - returns None when the toggle is off — read at CALL time
        - returns None for an APPROVER only by AUTHENTICATED ACCOUNT. The caller-declared
          `actor` buys no APPROVER authority on this path — it is named in the refusal for
          legibility and recorded in the ledger, never consulted for approver permission
        - ⚠️ but `actor` IS still consulted, below, by the SELF-CLAIM carve-out: a caller
          claiming their OWN row with a non-blank `reason` is permitted on a typed name
          alone. That is Rick's "permitted with a receipt" and it is deliberate. So this
          gate is shut to a typed name claiming to be an APPROVER and open to a typed name
          claiming to be the row's OWNER — do not read the clause above as "no typed name
          ever passes here", because that is not what the code does
        - otherwise returns a non-empty detail naming the toggle, the edge it refused,
          and BOTH ways to turn it back on — a refusal that does not say how to proceed
          is a dead end wearing a 403
        - never raises
    """
    if to_status   != PULL_TARGET_STATUS: return None
    if from_status == PULL_TARGET_STATUS: return None
    if not get_manager_pull_disabled():   return None

    # 🔴 THE ACCOUNT IS THE ONLY APPROVER DOOR ON THIS PATH TOO. Rick's ruling
    # 2026-09-08 ~11:10 EDT, by keypress: "close the pull hole."
    #
    # An `if is_approver( actor ): return None` clause stood immediately above this line
    # and made the whole rescind advisory. Measured on this branch before it was removed,
    # as a pure function with no account on any call:
    #
    #     admit / wont-fix / demote,  actor="maria e2908f90"  ->  REFUSED
    #     pull,                       actor="maria e2908f90"  ->  ALLOWED     <- the hole
    #     pull,                       actor="nobody at all"   ->  REFUSED     <- control
    #
    # The control is what makes that ALLOWED mean something: the gate was not merely
    # permissive, it was specifically honouring a typed approver NAME. So the switch whose
    # own words are "you can never do it without my approval" was openable by anyone
    # holding the shared fleet API key, with no account and no token, by typing a name.
    #
    # ⚠️ THE SIBLING GATE WAS ALREADY CLOSED AND THIS ONE WAS NOT. `refusal_for_admission`
    # carries a long "do not restore this check" comment; this path had nothing equivalent,
    # which is how a fourth move went unswept while its commit read "closed on all three
    # moves" — Rick's three NAMED moves. The pull is the fourth, and it is the one the
    # rescind is actually about. Do not restore the clause here either.
    if approver_persona_for_account( account_email ) is not None: return None
    if actor_is_claiming_their_own_row( actor, item_owner, item_manager ):
        # 🔨 RICK'S TERMS, via María 🌸, 2026-09-07 ~22:07 EDT: self-pull is "permitted
        # with a receipt — the row records who pulled it and why." The exemption is
        # therefore CONDITIONAL, not free, and the condition is enforced HERE rather
        # than in the shared transition rules because it applies only to the pull the
        # exemption itself let through. An approver's ordinary pull is untouched.
        #
        # THE "WHO" HALF NEEDS NOTHING ADDED: the transition door already writes
        # `recorded_actor( payload.actor, account_email )`, which puts the server-known
        # identity FIRST and the caller's claim in parentheses. This is the "why".
        #
        # 🔨 AND THE "WHO" DOES **NOT** NEED AN ACCOUNT — RICK REVERSED HIS OWN RULING OF
        # FOUR HOURS EARLIER, 2026-09-08 ~16:05 EDT, by keypress. From the option text he
        # clicked: "Let a worker start its own row" — permit the move into `in_progress`
        # when the actor IS the row's own owner, WITHOUT an account; every other move
        # stays account-bound. The account check that stood here is therefore gone.
        #
        # 🔴 WHAT THAT CHECK COST WHILE IT STOOD, which is what he was shown before he
        # ruled. He ruled at ~12:5x that this path needed an account ("close it, require
        # an account here too"); it was built the same afternoon and it worked exactly as
        # ruled. It then refused Krishna 🦚 the move of HIS OWN ASSIGNED ROW out of
        # `queued`:
        #
        #     "Pulling work into 'in_progress' is switched OFF right now…
        #      'Krishna ed4f1a4e' tried to move a 'queued' row into 'in_progress'."
        #
        # Agent seats hold only the shared fleet API key and carry NO account, so the
        # carve-out was unreachable for EVERY worker seat, not merely that one. The
        # standing mandate is that a seat keeps its own row's status current — that is the
        # signal the work-owed oracle and the manager tick read — and no seat could. Boards
        # read `queued` while the work happened, so the liveness signal degraded QUIETLY
        # rather than loudly. That is the cost he weighed.
        #
        # ⚠️ THE COST HE ACCEPTED IN EXCHANGE, recorded rather than disputed because it was
        # written into the option he clicked: ONE typed-name path stays open here. A caller
        # who types the owner's persona claims this exemption, and owner personas are
        # visible in every board listing. It is the narrowest edge available — the row's OWN
        # owner, one transition, and only when a DIFFERENT manager assigned it — but it is
        # not zero. Do not summarise this module as fully account-bound while this branch
        # exists; that is the same over-claim `refusal_for_pull`'s docstring already warns
        # against two paragraphs up.
        #
        # ⇒ WHAT THIS DOES NOT REOPEN. Admit, won't-fix and demote stay account-bound per
        # his 2026-09-07 ~21:47 ruling, and so does the APPROVER door twenty lines above:
        # a typed name still buys no approver authority on this path. This is a carve-out
        # on ONE transition for the row's OWN owner, not a rollback of the actor door.
        #
        # ⚠️ AND THE EDGE IS DELIBERATELY NOT NARROWED TO `queued -> in_progress`, though
        # his option text used that phrasing as its example. Narrowing it would REFUSE a
        # worker resuming a `blocked` row of their own — a NEW refusal invented by a ruling
        # whose whole purpose was to remove one. He ruled the account away, not the edge in.
        #
        # ⚠️ THE RECEIPT SURVIVES, and it is a different ruling by a different person.
        # "Permitted with a receipt" is Rick's via María 🌸 (2026-09-07 ~22:07); the account
        # requirement was his own of ~12:5x. He reversed the second and said nothing about
        # the first, so the `reason` clause below stands untouched.
        if isinstance( reason, str ) and reason.strip(): return None
        return (
            f"You may start your own row — '{item_owner}' is the owner and "
            f"'{item_manager}' assigned it, so this is not the manager pull that is "
            f"switched off. But it is permitted WITH A RECEIPT: pass a non-blank "
            f"`reason` saying why you are picking this row up now. "
            f"A row that moves onto a board with no justification is "
            f"indistinguishable from one that pulled itself, which is the exact "
            f"thing the toggle exists to make impossible."
        )

    return (
        f"Pulling work into '{PULL_TARGET_STATUS}' is switched OFF right now. "
        f"'{actor}' tried to move a '{from_status}' row into '{PULL_TARGET_STATUS}'. "
        f"This is the manager pull toggle (row 458e9947), turned into a standing "
        f"rescission by Rick on 2026-09-07 (row 1ec67228): \"you can never do it "
        f"without my approval\". "
        f"⇒ THE WAY FORWARD IS AN APPROVER, NOT A SWITCH. Ask one to make this "
        f"transition, or to approve you making it — on THIS path an approver is "
        f"recognized ONLY by the login account on your token. Setting `actor` to an "
        f"approver's name does nothing here and will return you this same message; "
        f"the name you send is recorded, never trusted. "
        f"An OPERATOR who means to lift the rescission itself does it through "
        f"PATCH /api/tasks/approval-settings with manager_pull_disabled=false, on a "
        f"login account that is an approver, or by setting "
        f"'{INI_KEY_MANAGER_PULL_DISABLED} = False' in the config — that is Rick's call "
        f"to make, not a step for whoever hit this message. Editing the settings FILE by "
        f"hand is not the sanctioned path. "
        f"Filing new rows is unaffected — that door is the flow-ratio gate, not this one."
    )


# ── THE VALIDATED WRITE PATH FOR EVERY KEY IN THIS FILE ───────────────────────
#
# 🔨 RICK, 2026-09-08: "Only the server writes it." Agents lose direct file access;
# changes go through an authenticated endpoint. He accepted, knowingly, that a seat
# editing the file today breaks.
#
# 🔴 WHY A `chmod` IS NOT THE FIX, AND THE MEASUREMENT THAT KILLS IT. The file is
# `664 rruiz:rruiz` in a `775 rruiz:rruiz` directory, and EVERY Claude seat runs as
# rruiz. It is not world-writable — it is OWNER-writable, and every seat IS the owner.
# Permission bits cannot express "someone else may not write this" when there is no
# someone else, so a tightening looks applied, passes a smoke test, and changes
# nothing. Do not propose one. This is ABSENT PROCESS ISOLATION — a deployment change
# (a distinct service UID) — not a permissions bug.
#
# ⚠️ WHAT THIS BUYS, SAID PLAINLY SO NOBODY CALLS IT SECURITY. It makes the endpoint
# the SANCTIONED path. It does not make it the ONLY one: a seat with a text editor
# still reaches the bytes. Mr. Radio's ruling, verbatim — "the endpoint is the
# SANCTIONED path; it does not make it the ONLY one."

# The keys the server will write. A key absent from here cannot be written through the
# door at all — which is why the door REPORTS an unknown key rather than ignoring it.
# A setting that is ignored in silence is how an operator concludes the switch itself
# is broken.
WRITABLE_KEYS = (
    "enforcement_active",
    "default_to_holding",
    "manager_pull_disabled",
    "approvers",
    "approver_accounts",
)


# The subset of WRITABLE_KEYS whose value is a boolean, and therefore whose PROVENANCE
# depends on whether the stored value parses rather than merely on it being present.
_BOOLEAN_KEYS = ( "enforcement_active", "default_to_holding", "manager_pull_disabled" )


def _validated_bool( key, raw ):
    """
    Return `raw` unchanged if it is a REAL bool, else raise ValueError naming the key.

    🔴 A STRING IS REFUSED, NEVER COERCED, AND "false" IS THE WHOLE REASON.
    `bool( "false" )` is True, so coercing here would switch a gate ON while the caller
    believed they had turned it off. The READER parses strings, for the operator who
    hand-edits; nothing should ever ARRIVE at the writer as one.

    Requires:
        - key names the setting, for the caller who has to fix their request

    Ensures:
        - returns raw when it is a real bool
        - raises ValueError naming the key and the type it got, otherwise
    """
    if not isinstance( raw, bool ):
        raise ValueError(
            f"{key} must be a real boolean, got {type( raw ).__name__} ({raw!r}). The "
            f"string \"false\" is a particularly bad value here: it is TRUTHY, so "
            f"coercing it would switch the setting ON while the caller believed they "
            f"had turned it off."
        )
    return raw


def _validated_approvers( raw ):
    """
    Check an `approvers` payload, returning the value to store.

    Ensures:
        - raises ValueError unless raw is a list of non-blank strings
        - returns each entry stripped
        - does NOT canonicalize — `get_approvers` does that on read, and storing a
          canonicalized form would make the file disagree with what the operator sent,
          which is how an operator concludes their own edit did not take
    """
    if not isinstance( raw, list ):
        raise ValueError(
            f"approvers must be a list of persona names, got "
            f"{type( raw ).__name__} ({raw!r})."
        )
    cleaned = [ ]
    for entry in raw:
        if not isinstance( entry, str ) or not entry.strip():
            raise ValueError(
                f"every approver must be a non-blank string; got {entry!r} in {raw!r}."
            )
        cleaned.append( entry.strip() )
    return cleaned


def _validated_approver_accounts( raw ):
    """
    Check an `approver_accounts` payload, returning the value to store.

    Ensures:
        - raises ValueError unless raw maps non-blank string to non-blank string
        - lower-cases the email side, which is what the reader compares on
    """
    if not isinstance( raw, dict ):
        raise ValueError(
            f"approver_accounts must be an object mapping login email to persona, got "
            f"{type( raw ).__name__} ({raw!r})."
        )
    cleaned = { }
    for email, persona in raw.items():
        if not isinstance( email, str ) or not email.strip() \
           or not isinstance( persona, str ) or not persona.strip():
            raise ValueError(
                f"approver_accounts needs non-blank string keys and values; got "
                f"{email!r}: {persona!r}."
            )
        cleaned[ email.strip().lower() ] = persona.strip()
    return cleaned


_VALIDATORS = {
    "enforcement_active"    : lambda raw: _validated_bool( "enforcement_active", raw ),
    "default_to_holding"    : lambda raw: _validated_bool( "default_to_holding", raw ),
    "manager_pull_disabled" : lambda raw: _validated_bool( "manager_pull_disabled", raw ),
    "approvers"             : _validated_approvers,
    "approver_accounts"     : _validated_approver_accounts,
}


def _patch_override_file( updates ):
    """
    Merge `updates` into the override file atomically, preserving every other key.

    Requires:
        - updates is a non-empty dict whose values are ALREADY validated

    Ensures:
        - the other keys in the file are PRESERVED — this is a PATCH, not a replace.
          Clobbering `approvers` while flipping a toggle would take the approval gate
          down as a side effect of an unrelated switch
        - the write is ATOMIC (temp + os.replace), so a concurrent reader sees the old
          file or the new one, never a half-written one
        - a CORRUPT existing file is reported and replaced rather than raising — the
          same tolerance the reader has, for the same reason: a bad file must not make
          the settings unflippable
        - the in-process cache is invalidated, so the very next read re-parses. Without
          this a write-then-read inside one second can return the OLD value: mtime has
          one-second granularity, the same whole-second trap that defeats .pyc
          invalidation elsewhere in this repo
    """
    global _cache, _cache_mtime

    path = override_path()
    os.makedirs( os.path.dirname( path ), exist_ok=True )

    body = { }
    try:
        with open( path, "r" ) as handle:
            existing = json.load( handle )
        if isinstance( existing, dict ): body = existing
        else: print( f"[task-approval] override file {path} is not an object — replacing it" )
    except FileNotFoundError:
        pass
    except Exception as error:
        print( f"[task-approval] override file {path} unusable ({error}) — replacing it" )

    body.update( updates )

    # 🔴 STAMP WHAT WE WROTE (row a5bf74ff item D). Computed over the body AFTER the
    # update and WITHOUT the stamp key itself, so re-writing an unchanged file is
    # idempotent. A process with no secret writes an UNSTAMPED file rather than a wrong
    # one — the reader's three-way verdict handles that honestly, and a bogus stamp
    # would be worse than none: it would read as forged rather than as unverifiable.
    body.pop( STAMP_KEY, None )
    stamp = _expected_stamp( body )
    if stamp is not None: body[ STAMP_KEY ] = stamp

    temp = f"{path}.tmp"
    with open( temp, "w" ) as handle:
        json.dump( body, handle, indent=2 )
        handle.write( "\n" )
    os.replace( temp, path )

    _cache_mtime = None


def current_settings():
    """
    Every approval setting in force right now, with the layer each came from.

    Ensures:
        - returns { key: { "value": <live value>, "source": "override"|"config" } }
        - the VALUE is read through the PUBLIC reader, so it is what the gate will
          actually use — not the raw file contents. A settings endpoint that echoes the
          file rather than the effective value is how an operator comes to believe a
          setting is in force while a fallback is overruling it
        - the SOURCE is included for the reason the ratio endpoint includes its own: a
          value alone cannot tell an operator whether the INI is in force or is being
          masked by a saved override, which is the one confusion a two-layer scheme
          reliably creates
        - never raises
    """
    overrides = _read_overrides()

    def _source( key ):
        """
        Which LAYER the effective value actually came from.

        🔴 PRESENCE IS NOT PROVENANCE, AND MY FIRST VERSION OF THIS CONFLATED THEM. It
        read `overrides.get( key ) is not None`, which reports "override" for a key
        that is PRESENT — including one holding a value the reader cannot parse. An
        unparseable override falls through to the config layer, so that version said
        "override" about a value the override did not produce. Caught by
        `test_current_settings_reports_the_EFFECTIVE_value_not_the_FILE`, whose whole
        subject is that this endpoint must not describe the file.

        ⇒ For a boolean, the question is not "is a key there" but "did it PARSE" — the
        same distinction `_as_bool_or_none` exists to make. A value nobody can parse is
        not a decision, so it is not a source either.
        """
        raw = overrides.get( key )
        if raw is None: return "config"
        if key in _BOOLEAN_KEYS:
            return "override" if _as_bool_or_none( raw, "" ) is not None else "config"
        return "override"

    return {
        "enforcement_active"    : { "value" : get_enforcement_active(),
                                    "source": _source( "enforcement_active" ) },
        "default_to_holding"    : { "value" : default_mint_status() == NOT_APPROVED_STATUS,
                                    "source": _source( "default_to_holding" ) },
        "manager_pull_disabled" : { "value" : get_manager_pull_disabled(),
                                    "source": _source( "manager_pull_disabled" ) },
        "approvers"             : { "value" : sorted( get_approvers() ),
                                    "source": _source( "approvers" ) },
        "approver_accounts"     : { "value" : get_approver_accounts(),
                                    "source": _source( "approver_accounts" ) },
    }


def set_overrides( **updates ):
    """
    Persist one or more approval settings through the ONE validated door.

    🔴 FOUR OF THE FIVE KEYS IN THIS FILE HAD NO WRITER AT ALL BEFORE THIS. Measured at
    `2da8896f` with a fixed-string sweep and working positive controls:
    `manager_pull_disabled` had `set_manager_pull_disabled` and an HTTP door;
    `enforcement_active`, `approvers`, `approver_accounts` and `default_to_holding` had
    neither — so hand-editing was the only way in, and it had no validation whatsoever.
    That is the "guard on the door nobody could open" shape, four times over.

    Requires:
        - every keyword names a key in WRITABLE_KEYS
        - each value satisfies that key's validator (booleans must be REAL booleans)

    Ensures:
        - raises ValueError on an unknown key or a bad value, naming the offender
        - writes NOTHING when any key is bad — validation completes for EVERY key
          before the file is touched, so a two-key call cannot half-apply and leave the
          gate in a state the caller never asked for and cannot see
        - unrelated keys already in the file are PRESERVED
        - the write is atomic and the read cache is invalidated
        - returns the live settings READ BACK after the write, never the values asked
          for, so a caller reports what TOOK EFFECT rather than what it requested
    """
    if not updates:
        raise ValueError( "set_overrides needs at least one setting to write." )

    unknown = sorted( set( updates ) - set( WRITABLE_KEYS ) )
    if unknown:
        raise ValueError(
            f"not a writable approval setting: {', '.join( unknown )}. "
            f"Writable keys are {', '.join( sorted( WRITABLE_KEYS ) )}."
        )

    validated = { key: _VALIDATORS[ key ]( value ) for key, value in updates.items() }

    _patch_override_file( validated )
    return current_settings()


def set_manager_pull_disabled( disabled ):
    """
    Persist the pull toggle, atomically, and return the live value after the write.

    🔴 THIS MODULE HAD NO WRITER AT ALL UNTIL NOW, AND THAT IS THE DEFECT THIS CLOSES.
    Hand-editing `override_path()` was the ONLY way to flip anything here — which is
    exactly the "guard on the door nobody could open" shape: `bool( "false" )` could
    turn a switch on through the only reachable door, while the validated path existed
    for a request nobody could send. A validated write path is what makes the flag a
    control rather than a file.

    Requires:
        - disabled is a REAL bool. A string is refused, not coerced — the reader parses
          strings for the operator who hand-edits, but nothing should ARRIVE as one.

    Ensures:
        - raises ValueError on any non-bool, naming what it got
        - the other keys in the override file are PRESERVED — this is a PATCH of one
          key, not a replace. Clobbering `approvers` while flipping a toggle would take
          the approval gate down as a side effect of an unrelated switch
        - the write is ATOMIC (temp + os.replace), so a concurrent reader sees the old
          file or the new one, never a half-written one
        - the in-process cache is invalidated, so the very next read re-parses. Without
          this a write-then-read inside one second can return the OLD value: mtime has
          one-second granularity, the same whole-second trap that defeats .pyc
          invalidation elsewhere in this repo
        - returns the value actually in force after the write, read back through
          `get_manager_pull_disabled()` rather than echoed from the argument, so a
          caller reports what TOOK EFFECT rather than what it asked for

    ⚠️ THE BODY NOW DELEGATES, AND THE CONTRACT IS UNCHANGED. Validation, the
    read-modify-write, the atomic replace and the cache invalidation all moved to
    `_validated_bool` / `_patch_override_file` when `set_overrides` was added
    (2026-09-08) — four keys needed the identical machinery, and a second copy of it is
    two things to keep in step. This function survives as the NAMED door for the one
    key that already had callers and tests; those tests are the regression check that
    the move changed nothing.
    """
    _validated_bool( "manager_pull_disabled", disabled )
    _patch_override_file( { "manager_pull_disabled": disabled } )
    return get_manager_pull_disabled()
