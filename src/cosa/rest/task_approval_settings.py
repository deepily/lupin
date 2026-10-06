"""
Approver allowlist and approval-gate settings for the holding area, kept in configuration.

The allowlist is configuration and never a constant. A list that needs a code edit and a
deploy to change is a permanent list wearing a temporary label.

It gates admission out of `not_approved` (the holding area) onto somebody's board. A row
nobody approved must not become owed work.

The actor check is a policy control, not a security boundary. The actor it checks is
`payload.actor`, which the caller declares. `require_api_key_or_jwt` proves only that the
caller holds a fleet credential, and every seat holds the same one. So the check refuses an
honest caller who is not an approver. It does not stop a dishonest one typing an approver's name. The authenticated user id is recorded alongside, so a false claim is
attributable afterwards: accountability rather than prevention.

File permissions were never a control: the host user and both server containers run as one
uid, so no file mode can exclude a writer. Only a distinct service uid would give a boundary.

The legacy file sat in the flow-ratio directory, not in a mount of its own. A new mount
resolves at container create, so it needs `docker compose up -d --force-recreate` on both
servers. `LUPIN_FLOW_RATIO_DIR` is already mounted in `lupin-rest-dev` and `lupin-rest-test`.
The name says flow-ratio and this is not. Renaming it would cost that force-recreate, the
expensive half of the trade, so a second env var is the cheap fix for later.

The live settings are in the `approval_settings` table. The only write path is the
validated setter (`set_overrides`), and the HTTP door in front of it resolves the operator
from a signature-checked login token. The old JSON file is read once per database, at boot,
by `import_legacy_override_file`, and never again, so rewriting it changes nothing.

When the database cannot be read, the readers fall back to the INI defaults and print a
loud `[task-approval]` line, at most once a minute. Per key:
    - enforcement_active: INI `task approval enforcement active`, else False. The gate
      advises instead of refusing. That fails open, because a gate that fails closed on
      an outage takes the board down for everyone.
    - manager_pull_disabled: INI `task approval manager pull disabled`, else True. Pulling
      stays frozen. That fails closed, so an outage never hands a manager back an access
      the owner withdrew.
    - approvers, accounts, default_to_holding, sword_of_damocles_active: INI, else the
      module fallback, which is the shipped behaviour.
A write while the database is down raises OSError, and the router answers 500 saying the
live values are unchanged.
"""

import hashlib
import hmac
import json
import os
import time

from cosa.config.configuration_manager import ConfigurationManager
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
from cosa.rest.task_store_rules import NOT_APPROVED_STATUS, WONT_FIX_STATUS
# 🔨 Imported as a MODULE, not as a `from … import PARK_STATUS`, so the park edge below
# ASKS the rules module rather than restating its literal. Two pieces of code deciding
# one rule agree until they do not, and a copied "parked" string would keep agreeing
# right up until somebody renamed the status.
from cosa.rest import task_store_rules as rules
from lupin_mcp.persona_normalization import canonical_persona_key

# Same env var as flow_ratio_settings, for the mount reason in the docstring. Resolved
# FIRST — the container sets it; `fleet_data_root()` is correct only on the host, where
# it returns a real writable directory.
_SETTINGS_DIR_ENV = "LUPIN_FLOW_RATIO_DIR"

# The mount's leaf directory. The host fallback MUST append it, or the two branches name
# two different files — the defect flow_ratio_settings carried for three days.
OVERRIDE_SUBDIR   = "flow-ratio"
OVERRIDE_FILENAME = "task-approval-settings.json"

# Where a stored value is said to come from in a parse complaint. The table, never a
# filesystem path: the message can reach a caller, and a path is a server-side fact.
STORE_LABEL = "the approval_settings table"

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
        - never raises, and never has a default: a hardcoded fallback secret would make
          every stamp forgeable by anyone reading this file, which is worse than no stamp

    Reusing `JWT_SECRET_KEY` adds no new failure mode. Without it, `jwt_service.py` already
    raises a ValueError at import, so a server that cannot sign settings already cannot
    sign tokens and already refuses to boot. "Absent" is therefore not a state a running
    server can be in, so nothing here decides a gate on its absence.
    """
    return os.getenv( "JWT_SECRET_KEY" )


def _expected_stamp( body ):
    """
    The stamp `body` should carry, or None when this process cannot compute one.

    Requires:
        - body is the override dict, with or without its own STAMP_KEY

    Ensures:
        - returns a hex HMAC-SHA256 over the canonical JSON of every key except the
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
    Whether `body` carries a stamp this process can verify and that verifies.

    Ensures:
        - returns True only when a secret exists, a stamp is present, and the two agree
          under a constant-time comparison
        - returns False when the stamp is absent, wrong, or not a string
        - returns None when this process cannot check at all (no secret) — a third
          value, never False, because "unverifiable" and "forged" would otherwise
          be indistinguishable and the caller would treat a keyless dev box as an attack
    """
    expected = _expected_stamp( body )
    if expected is None: return None

    found = body.get( STAMP_KEY )
    if not isinstance( found, str ): return False

    return hmac.compare_digest( found, expected )


# ---------------------------------------------------------------------------
# THE STORE (row 80513825) — the approval_settings table, behind the server
# ---------------------------------------------------------------------------

# Every key a reader projects, so `_read_overrides()` always returns the same shape.
_STORED_KEYS = ( "approvers", "enforcement_active", "default_to_holding", "approver_accounts",
                 "manager_pull_disabled", "sword_of_damocles_active" )

# Marker row written when the legacy JSON file has been imported into a database, so the
# import happens once per database and never again. Not a setting: `_STORED_KEYS` does not
# name it, so no reader ever sees it.
LEGACY_IMPORT_MARKER = "_legacy_file_imported"

# How long a successful read is reused. A gate check is a hot path, and a stale value can
# only outlive a write made by ANOTHER process (this process invalidates its own cache on
# write), so a short window is the whole cost.
CACHE_TTL_SECONDS = 2.0

# The loud line for an unreadable store is printed at most this often.
OUTAGE_LOG_INTERVAL_SECONDS = 60.0

_cache             = None
_cache_loaded_at   = None
_outage_logged_at  = None


def _no_overrides():
    """
    The projection of an empty store: every key present, every value None.
    """
    return { key: None for key in _STORED_KEYS }


class _DbBackend:
    """
    The real store: `approval_settings` rows, read and written through `get_db()`.

    The unit tier swaps this for an in-memory twin (`tests/conftest`), so nothing in the
    unit tier needs a database.
    """

    def load( self ):
        """
        Every stored row as { key: value }.

        Raises:
            - whatever the database layer raises when it cannot be reached
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.approval_setting_repository import ApprovalSettingRepository
        with get_db() as session:
            return ApprovalSettingRepository( session ).get_all()

    def write( self, updates, updated_by ):
        """
        Upsert `updates`, recording `updated_by`, in one transaction.
        """
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.approval_setting_repository import ApprovalSettingRepository
        with get_db() as session:
            ApprovalSettingRepository( session ).upsert_many( updates, updated_by )


_backend = _DbBackend()


def _invalidate_cache():
    """
    Forget the cached read, so the next reader goes back to the store.
    """
    global _cache, _cache_loaded_at
    _cache           = None
    _cache_loaded_at = None


def _report_outage( error ):
    """
    Print the loud unreadable-store line, at most once per OUTAGE_LOG_INTERVAL_SECONDS.

    Ensures:
        - never raises
        - says which way each key falls back, so the reader of a log does not have to
          open this file to learn what the outage is doing to the gate
    """
    global _outage_logged_at
    now = time.monotonic()
    if _outage_logged_at is not None and now - _outage_logged_at < OUTAGE_LOG_INTERVAL_SECONDS: return
    _outage_logged_at = now
    print(
        f"[task-approval] 🔴 cannot read {STORE_LABEL} ({error}) — using the INI defaults. "
        f"enforcement_active falls back to its INI key (else False: the gate ADVISES, fails OPEN); "
        f"manager_pull_disabled falls back to its INI key (else True: pulling stays FROZEN, fails CLOSED)."
    )


def _read_overrides():
    """
    Load the stored settings, reusing the last read for CACHE_TTL_SECONDS.

    Ensures:
        - returns a dict with keys "approvers" / "enforcement_active" /
          "default_to_holding" / "approver_accounts" / "manager_pull_disabled" /
          "sword_of_damocles_active", each a value or None
        - an empty store is the ordinary no-override case and returns every key None
        - an unreadable store is reported loudly (rate-limited) and answers every key None,
          so each reader falls to its INI default — see the module docstring for which way
          each key fails. It never raises: an unreachable database must not take the board
          down, and silence would leave an operator's write apparently disregarded
        - a failed read is never cached, so the very next call tries the store again
        - the legacy JSON file is never read here
    """
    global _cache, _cache_loaded_at

    now = time.monotonic()
    if _cache is not None and _cache_loaded_at is not None and now - _cache_loaded_at < CACHE_TTL_SECONDS:
        return _cache

    try:
        stored = _backend.load()
    except Exception as error:
        _report_outage( error )
        return _no_overrides()

    _cache           = { key: stored.get( key ) for key in _STORED_KEYS }
    _cache_loaded_at = now
    return _cache


def legacy_override_path():
    """
    The retired override file, named only so the one-time import can find it.

    Ensures:
        - returns $LUPIN_FLOW_RATIO_DIR/task-approval-settings.json when set, else
          <fleet_data_root()>/flow-ratio/task-approval-settings.json
        - nothing but `import_legacy_override_file` calls it; no reader does
    """
    override_dir = os.environ.get( _SETTINGS_DIR_ENV )
    if override_dir:
        return os.path.join( override_dir, OVERRIDE_FILENAME )
    return os.path.join( fleet_data_root(), OVERRIDE_SUBDIR, OVERRIDE_FILENAME )


def import_legacy_override_file():
    """
    Copy the retired JSON file's values into the table, once per database, then ignore it.

    Ensures:
        - returns { "status": ..., "imported": [keys] } where status is one of
          "already-imported" (this database has its marker; the file is not opened),
          "no-file" (marker written, nothing to copy), "unreadable" (file present but not
          a JSON object; marker written, nothing copied, reported loudly),
          "refused-unverified" (the stamp did not verify; marker written, nothing copied),
          "imported"
        - a file whose stamp does not verify imports nothing: every key is skipped and the
          setting falls to its INI default. Until this first boot import runs the file is
          still writable by every seat, so an unverified `approvers`, `approver_accounts` or
          `enforcement_active` must not be laundered into the table.
          "Cannot check" (no signing secret) counts as not verified. The safe direction for
          enforcement_active is therefore the INI default, chosen over
          importing an unverified value
        - only keys in WRITABLE_KEYS whose value passes that key's validator are copied; a
          bad value is reported and skipped
        - every imported and every skipped key is logged with its value, so the boot log
          records exactly what entered the table
        - the marker row is written in the same transaction as the values, so a second boot
          finds it and does nothing — a seat that edits the file afterwards changes nothing
        - the file is not renamed or deleted: `:7999` and `:8000` share the directory but
          not the database, and each database needs its own one-time copy
        - the database being unreadable raises: boot must not proceed on a half-known store

    Raises:
        - whatever the database layer raises when it cannot be reached
    """
    stored = _backend.load()
    if LEGACY_IMPORT_MARKER in stored:
        return { "status": "already-imported", "imported": [] }

    path     = legacy_override_path()
    imported = {}
    status   = "no-file"

    if os.path.exists( path ):
        try:
            with open( path, "r" ) as handle:
                body = json.load( handle )
            if not isinstance( body, dict ):
                raise ValueError( f"expected a JSON object, got {type( body ).__name__}" )
        except Exception as error:
            body   = None
            status = "unreadable"
            print( f"[task-approval] legacy override file {path} unusable ({error}) — nothing imported" )

        if body is not None:
            verified = _stamp_is_valid( body ) is True
            status   = "imported" if verified else "refused-unverified"
            for key in WRITABLE_KEYS:
                if key not in body: continue
                if not verified:
                    print( f"[task-approval] legacy override {key}={body[ key ]!r} NOT imported — the file's "
                           f"stamp does not verify, so {key} keeps its INI default" )
                    continue
                try:
                    imported[ key ] = _VALIDATORS[ key ]( body[ key ] )
                except ValueError as error:
                    print( f"[task-approval] legacy override {key}={body[ key ]!r} skipped — {error}" )

    for key, value in imported.items():
        print( f"[task-approval] legacy override imported: {key}={value!r}" )

    marker = { LEGACY_IMPORT_MARKER: { "status": status, "keys": sorted( imported ), "source": path } }
    _backend.write( { **imported, **marker }, "legacy-file-migration" )
    _invalidate_cache()
    print( f"[task-approval] legacy override file {status}: {sorted( imported )} — the file is ignored from now on" )
    return { "status": status, "imported": sorted( imported ) }


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
        - always contains UNCONDITIONAL_APPROVERS, whatever the config says — an empty
          or truncated allowlist can never lock the fleet out of its own holding area
        - stored override wins over the INI key; both are tolerated absent
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
    Whether the approval gate refuses, or merely advises.

    Ensures:
        - returns a bool
        - the stored override wins over the INI key
        - a string is parsed, never coerced: "false" / "no" / "0" / "off" all mean False
        - an unparseable value is reported and falls through to the next layer rather
          than being read as False, because it is not a decision and so must not make one
        - the fallback is False: an absent or broken config fails open
        - parsing is delegated to `_as_bool_or_none`, because a third hand-rolled parse
          would drift from the others. The junk case `"banana"` once fell through a
          membership test and came out False, silently, which is indistinguishable from a
          deliberate "off". `test_one_boolean_parser_for_every_surface.py` requires one parser.
    """
    value = _as_bool_or_none( _read_overrides()[ "enforcement_active" ],
                              STORE_LABEL )
    if value is not None: return value

    value = _as_bool_or_none( _ini_value( INI_KEY_ENFORCEMENT, "string", None ),
                              f"config key '{INI_KEY_ENFORCEMENT}'" )
    if value is not None: return value

    return FALLBACK_ENFORCEMENT_ACTIVE


def get_approver_accounts():
    """
    The login-account -> approver-persona map, canonicalized on both sides.

    Requires:
        - nothing

    Ensures:
        - returns a dict { lowercased-email : canonical persona key }
        - stored override `approver_accounts` (an object) wins over the INI key
        - INI form is comma-separated `email = persona` pairs; an entry missing its
          `=`, or blank on either side, is skipped rather than raising — a typo in one
          pair must not take the whole map, and with it the browser's door, down
        - returns {} when unconfigured, which is today's behaviour written down
        - never raises
        - it is a map and not a list of emails because the refusal message and the audit
          trail speak in personas, so an account must say which approver it is. A bare
          list could also make the two configs disagree unseen: an email whose persona is
          not in `task approval approver personas` would silently grant more than the
          allowlist does
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
        - account_email is the email on a validated access token, or None

    Ensures:
        - returns None for None/blank/non-string, and for an unmapped account
        - returns None when the mapped persona is not currently an approver — the
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
        - matches on the canonical persona key, so "María 🌸 session3", "maria" and
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


# The status a close lands in. Named for the manager-close carve-out below (row adaf7698)
# and read by the router for the same edge, so the two cannot spell it differently.
DONE_STATUS = "done"


# ── WHICH APPROVER-ONLY MOVE IS THIS? ──────────────────────────────────────────
#
# 🔴 ONE DERIVATION, BECAUSE THERE ARE NOW TWO READERS. `refusal_for_admission`
# needs the move to write its refusal; the REQUEST DOOR (Rick's ruling 2026-09-08,
# row c9fafb9d — "managers may only request") needs it to decide whether the refusal
# may be carried to Rick and to word the ask. Those are the same question, and this
# file already carries a warning about two predicates answering one question by
# different routes: they agree right up until their inputs diverge.
#
# ⚠️ THE ORDER OF THE THREE TESTS IS LOAD-BEARING AND IS THE ORDER THE REFUSAL USED
# BEFORE THIS FUNCTION EXISTED. A won't-fix close is checked FIRST, so a
# `not_approved -> wont_fix` is a won't-fix rather than an admission. Reordering
# would silently reclassify that edge and hand it to a door that must not have it.
MOVE_ADMIT    = "admit"
MOVE_WONT_FIX = "wont_fix"
MOVE_DEMOTE   = "demote"
MOVE_UN_PARK  = "un_park"

# The sentences the refusal has always used, kept BYTE-IDENTICAL. They are a
# published surface: callers read them out of a 403, and one of them is quoted in
# `test_the_admission_gate_refuses.py`.
MOVE_SENTENCES = {
    MOVE_WONT_FIX : f"closing a row as '{WONT_FIX_STATUS}'",
    MOVE_ADMIT    : f"admitting a row out of '{NOT_APPROVED_STATUS}'",
    MOVE_DEMOTE   : f"demoting a row back into '{NOT_APPROVED_STATUS}'",
    MOVE_UN_PARK  : f"un-parking a row out of '{rules.PARK_STATUS}'",
}

# 🔨 WHICH MOVES A MANAGER MAY REQUEST — RICK'S OWN TWO VERBS AND NOT A THIRD.
# His words, 2026-09-08 ~11:58 EDT by keypress: "it is me and me alone not managers
# that gets to promote and demote task items into the live list and out of it back
# into the task area me alone. Only thing managers can do is request".
#
# 🔴 WON'T-FIX IS DELIBERATELY ABSENT, AND ITS ABSENCE IS A DECISION RATHER THAN AN
# OVERSIGHT. He ruled on promotion and demotion; nobody has put a won't-fix request
# to him. `refusal_for_admission`'s own note explains why that move is the load-
# bearing one — a seat that could close rows this way holds both halves of a
# mint-by-deletion loop against the ratio gate — so widening it on an inference is
# exactly the wrong place to guess. A won't-fix keeps today's flat refusal.
REQUESTABLE_MOVES = frozenset( { MOVE_ADMIT, MOVE_DEMOTE } )


def requested_move( from_status, to_status ):
    """
    Which approver-only move this transition is, or None if it is not one of them.

    Requires:
        - from_status / to_status are status strings

    Ensures:
        - returns MOVE_WONT_FIX / MOVE_ADMIT / MOVE_DEMOTE / MOVE_UN_PARK, or None
        - the `not_approved -> not_approved` no-op is neither an admission nor a
          demote and returns None: it is already an illegal edge in the transition
          graph, and answering it with a permission refusal would name the wrong
          defect
        - never raises
    """
    if to_status == WONT_FIX_STATUS:                                             return MOVE_WONT_FIX
    if from_status == NOT_APPROVED_STATUS and to_status != NOT_APPROVED_STATUS:  return MOVE_ADMIT
    if to_status == NOT_APPROVED_STATUS and from_status != NOT_APPROVED_STATUS:  return MOVE_DEMOTE
    if from_status == rules.PARK_STATUS and to_status != rules.PARK_STATUS:      return MOVE_UN_PARK
    return None


def move_for_ticket( to_status ):
    """
    The move a promotion ticket represents, from the one field it persists.

    Requires:
        - to_status is the `to_status` persisted on a TaskPromotionTicket

    Ensures:
        - returns MOVE_DEMOTE when to_status is the holding area, else MOVE_ADMIT
        - never raises
        - it is shorter than `requested_move` because its population is smaller: a ticket
          is only minted for a move in `REQUESTABLE_MOVES`, which is {admit, demote}, so
          `to_status` alone settles it. A demote lands in the holding area; everything
          else is an admission out of it
        - it never classifies an arbitrary transition: fed `queued -> wont_fix` it answers
          MOVE_ADMIT, confidently and wrongly. That is `requested_move`'s job
    """
    return MOVE_DEMOTE if to_status == NOT_APPROVED_STATUS else MOVE_ADMIT


def refusal_for_admission( from_status, to_status, actor, account_email=None, closer_is_manager=False ):
    """
    The gate's whole decision, as a pure function: the refusal detail, or None.

    It is not inline in the router, so every clause is observable without a database. Inline,
    tests would assert on `is_approver` and call that the control: a predicate wired to nothing.

    Requires:
        - from_status / to_status are status strings; actor is the caller-declared
          "persona + session id" string, or None
        - account_email is the email on the caller's validated access token, or None
          when the caller authenticated by API key (which carries no account)
        - closer_is_manager is the router's answer to "is this caller a manager seat?",
          resolved once from the server-side manager check. It is never a value the
          caller typed

    Ensures:
        - returns None for 'not_approved' -> 'done' when closer_is_manager: a manager
          may close a held row. Won't-fix, promote, demote, un-park and 'parked' -> 'done'
          are untouched by it
        - a refused '->done' says what to do instead: a held row names that a manager
          may close it, a parked row names the park and says to ask Rick
        - returns None when the transition is none of the four approver-only moves:
          an admission out of the holding area, a won't-fix close, a demote back
          into the holding area, or an un-park (the not_approved -> not_approved no-op is
          neither an admission nor a demote, and is left to the legal-edge graph to refuse)
        - returns None when enforcement is off — the config is read at call time, so
          an operator's edit lands on the next request rather than the next deploy
        - returns None when the authenticated account maps to a current approver —
          the browser's door, and the only approver door on this path
        - `actor` buys no approver authority here. It is named in the refusal for
          legibility, never consulted for permission. The old `if is_approver( actor )`
          clause made a caller-declared string the authorization, so a caller holding the
          shared fleet API key could act as an approver by typing a name. The comment
          below explains why that check does not come back
        - otherwise returns a non-empty detail string naming the actor, the account it
          was authenticated as, the current allowlist, and both ways to change each —
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
    #
    # 🔴 THE FOUR-WAY TEST MOVED OUT TO `requested_move` AND THE SENTENCES TO
    # `MOVE_SENTENCES`, UNCHANGED IN BOTH ORDER AND WORDING. The REQUEST DOOR (Rick's
    # ruling 2026-09-08, row c9fafb9d — "the only thing managers can do is request")
    # needs the same classification to decide whether a refusal may be carried to him
    # and to word the ask. That is the same question this ladder answers, and this
    # file already warns what happens to two predicates answering one question by
    # different routes. What was here is now one lookup; the notes below stay where
    # they were written, because they explain the RULE and the rule has not moved.
    kind = requested_move( from_status, to_status )
    if kind is None: return None
    # -- A MANAGER MAY CLOSE A HELD ROW (Rick, 2026-09-10, row adaf7698) --
    #
    # "A manager should be able to close a ticket. That is not a matter of state
    # security." Closing records finished work as finished; admission decides what the
    # fleet works on. Both used to fall into the admission clause below, and that
    # sharing was the defect.
    #
    # 🔴 IT KEYS ON `MOVE_ADMIT`, WHICH `requested_move` ONLY ANSWERS AFTER ITS WON'T-FIX
    # TEST. A won't-fix is classified before this line is reached, so a later mistaken
    # widening of this clause still cannot hand a manager the won't-fix half of the
    # mint-by-deletion loop described above.
    #
    # ⚠️ ONE EDGE, ONE KIND OF CALLER. `not_approved -> done`, and only for a caller the
    # router resolved as a manager. `parked -> done` is deliberately NOT here: a park is
    # Rick's own not-now (Mr. Radio's review ruling, 2026-09-10 17:10 EDT), so it stays
    # with the un-park clause below.
    if kind == MOVE_ADMIT and to_status == DONE_STATUS and closer_is_manager: return None
    move = MOVE_SENTENCES[ kind ]
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

    # A refused CLOSE gets its own way forward, because "sign in as an approver" is the
    # wrong advice for the one move a manager may now make (row adaf7698).
    close_note = ""
    if to_status == DONE_STATUS:
        close_note = (
            f" ⇒ THIS ROW IS PARKED, and a park is Rick's own not-now, so a manager may not "
            f"close it either. Ask Rick to un-park it or to close it himself."
            if from_status == rules.PARK_STATUS else
            f" ⇒ CLOSING IS NOT ADMITTING: a manager may close it. Rick ruled 2026-09-10 "
            f"(row adaf7698) that a MANAGER seat may move a held row to '{DONE_STATUS}', so "
            f"ask your manager to close this row, citing a commit, a test_run or their own "
            f"manager_attestation."
        )
    # 🔨 A REFUSED PROMOTE OR DEMOTE NAMES THE REQUEST DOOR (row c9fafb9d, design §8). With
    # the allowlist emptied, "ask one of them to make this move" means Rick alone, and a
    # refusal that names no way to reach him is a dead end wearing a 403. Only the two
    # REQUESTABLE moves get it — won't-fix and un-park are not requestable — and not a
    # close, whose own note above already says what to do.
    request_note = ""
    if kind in REQUESTABLE_MOVES and to_status != DONE_STATUS:
        request_note = (
            f" ⇒ TO ASK RICK FOR THIS MOVE, FILE A REQUEST: POST /api/tasks/<task id>/request "
            f"with {{\"move\": \"{kind}\", \"reason\": \"…\", \"actor\": \"…\"}} (MCP: task_request). "
            f"It waits on his board until he answers; no answer means no."
        )
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
        f"{close_note}"
        f"{request_note}"
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

    Read at call time, like every other key here, so an operator's edit lands on the next
    request rather than the next deploy.

    Ensures:
        - returns a non-negative int; 0 means the rule is off
        - a negative or unparseable value reads as 0 rather than raising, because a
          malformed throttle must fail open for the same reason the flags above do
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

    Pure and separate from the count, so every clause is testable without a database.
    Tests then assert on the decision itself, not on a predicate wired to nothing.

    Requires:
        - actor is the caller-declared actor string
        - account_persona is the approver persona the caller's login account resolved to,
          or None
        - recent_admissions is how many rows this caller has already admitted inside the
          window (0 when the rule is off, or when nothing was counted)

    Ensures:
        - returns None when the window is 0 (rule off)
        - returns None when the caller is ask-exempt — Rick may batch; managers
          may not, and batch approve is the operator's control
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

    It is a function, not a `Field( default=... )`. A Pydantic default is evaluated at import,
    so the flag would freeze at boot and a flip would need a restart. Read at call time, a
    flip lands on the next request.

    Ensures:
        - returns "not_approved" when the holding-area default is on
        - otherwise returns "queued" — today's behaviour, unchanged
        - a string is parsed, never coerced
        - an unparseable value is reported and falls through rather than deciding
        - never raises
        - "false", "no", "off" and "0" in the stored override all read as off:
          `bool( "false" )` is True, so coercion would turn the holding-area default on
          while the stored value said off
    """
    on = _as_bool_or_none( _read_overrides()[ "default_to_holding" ],
                           STORE_LABEL )
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
    Parse one configured boolean strictly: True, False, or None for "says nothing".

    Requires:
        - `where` names the source, for the operator who has to go and fix it

    Ensures:
        - returns True / False for a real bool, or for one of TRUE_WORDS / FALSE_WORDS
          (case- and whitespace-insensitive)
        - returns None for absent, and for any other value -- including a truthy one
        - reports an unparseable value on stdout. A setting that is ignored in silence is
          how an operator concludes the switch itself is broken
        - never raises
        - an unrecognized value is None and never False: both `return bool( raw )` and a
          membership-test tail fail open on junk (`"banana"`, `""`, `0`, `[]` and `{}` all
          read as False, meaning pulling is allowed), so a typo in a hand-edited value
          would restore a capability the owner rescinded
        - it mirrors the `bool( "false" )` problem named in `get_manager_pull_disabled`: that
          one is a string read backwards, this one a string not understood at all
        - None means "decline to decide": the question falls to the next layer and ends at
          the setting's own fallback. Fallbacks point opposite ways:
          FALLBACK_MANAGER_PULL_DISABLED is True (fails closed) while
          FALLBACK_ENFORCEMENT_ACTIVE, FALLBACK_DEFAULT_TO_HOLDING and
          FALLBACK_SWORD_OF_DAMOCLES_ACTIVE are False (fail open), so None is the safe
          direction for the pull key only
        - non-strings are strict too, including a bare JSON `0` or `1`: the toggle is left
          closed and a printed line says why. The validated write path refuses anything but
          a real bool, so nothing this codebase writes arrives here as a number
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
    Whether pulling work into `in_progress` is currently switched off.

    Ensures:
        - returns a bool
        - the stored override wins over the INI key, and is re-read after CACHE_TTL_SECONDS,
          so an operator's flip lands on the next request rather than the next deploy
        - the fallback is True — an absent or broken config fails closed, as the
          operator ruled. See `FALLBACK_MANAGER_PULL_DISABLED`.
        - a string in the stored override is parsed, never coerced: "false" / "no" / "0"
          / "off" all mean False
        - never raises

    The string case is handled because `bool( "false" )` is True, so a hand-written
    `"manager_pull_disabled": "false"` would turn the toggle on while the operator believed
    it was off. All boolean surfaces share `_as_bool_or_none`; the guard
    (`test_one_boolean_parser_for_every_surface.py`) is a predicate over the module's own
    syntax, so a new surface trips it where a list of today's readers would not.
    """
    value = _as_bool_or_none( _read_overrides()[ "manager_pull_disabled" ],
                              STORE_LABEL )
    if value is not None: return value

    value = _as_bool_or_none( _ini_value( INI_KEY_MANAGER_PULL_DISABLED, "string", None ),
                              f"config key '{INI_KEY_MANAGER_PULL_DISABLED}'" )
    if value is not None: return value

    return FALLBACK_MANAGER_PULL_DISABLED


def actor_is_claiming_their_own_row( actor, item_owner, item_manager ):
    """
    Whether this pull is a worker picking up work already assigned to them.

    A manager pulling new work out of the holding area is one act. A worker starting a row
    a manager already handed them is another, and the toggle alone cannot tell them apart.

    Requires:
        - actor is the caller-declared "persona + session id" string, or None
        - item_owner / item_manager are persona strings off the row, or None

    Ensures:
        - returns False unless both halves hold: the actor is the row's owner and the
          row's accountable manager is somebody else — an unowned row, an unmanaged row, a
          row whose owner and manager are the same persona, and a caller who is not the
          owner all get False
        - matches on the canonical persona key, so "María 🌸 session3" and "maria" are
          the same person, exactly as `is_approver` does it
        - never raises
        - the second half is required: without it a manager who owns a row would be exempt
          from the switch on that row, which is the self-assignment the owner rescinded.
          Requiring a different manager means somebody else put the row on this actor's board
        - the actor is caller-declared, so a caller who types the owner's name claims the
          exemption. This is a policy control, not a boundary: it stops a worker taking
          someone else's row by habit, not one who decides to
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

    It is separate from the router so every clause is observable directly. Inline, tests
    would assert on the flag getter and call that the control; now the router test only
    has to prove the call happens.

    Requires:
        - from_status / to_status are status strings; actor is the caller-declared
          "persona + session id" string, or None
        - account_email is the email on the caller's validated access token, or None

    Ensures:
        - returns None when the transition is not into `in_progress` — this gate has
          one edge and takes no interest in any other
        - returns None for the `in_progress -> in_progress` no-op, so a re-PATCH of a
          row already being worked is never refused by a switch flipped after it started
        - returns None when the toggle is off — read at call time
        - returns None for an approver only by authenticated account. The caller-declared
          `actor` buys no approver authority on this path — it is named in the refusal for
          legibility and recorded in the ledger, never consulted for approver permission
        - but `actor` is still consulted, below, by the self-claim carve-out: a caller
          claiming their own row with a non-blank `reason` is permitted on a typed name
          alone, which is the owner's term "permitted with a receipt". So this gate is
          shut to a typed name claiming to be an approver and open to a typed name
          claiming to be the row's owner. Read the clause above as narrower than "no typed
          name ever passes here", because that is not what the code does
        - otherwise returns a non-empty detail naming the toggle, the edge it refused,
          and both ways to turn it back on — a refusal that does not say how to proceed
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
        # 🔨 WITH ONE EXCEPTION HE RULED SEPARATELY: `parked`. See below.
        #
        # ⚠️ THE RECEIPT SURVIVES, and it is a different ruling by a different person.
        # "Permitted with a receipt" is Rick's via María 🌸 (2026-09-07 ~22:07); the account
        # requirement was his own of ~12:5x. He reversed the second and said nothing about
        # the first, so the `reason` clause below stands untouched.

        # ── UN-PARKING IS THE ONE EDGE THAT STILL NEEDS AN ACCOUNT ────────────
        #
        # 🔨 RICK, 2026-09-08 ~17:00 EDT, by keypress (answered=true, default_used=false —
        # a real click, not a timeout). Asked: "You park a row. Should a worker be able to
        # un-park it and start work, without asking you?" Answered: NO.
        #
        # 🔴 WHY THIS EDGE IS NOT LIKE THE OTHER FOUR. `queued`, `blocked`, `claimed` and
        # `review` are work that was merely INTERRUPTED — resuming them is the case his
        # 16:05 reversal exists for. `parked` is different in kind: a park is a HUMAN's
        # deliberate not-now, carrying a `park_reason` that QUOTES the row's own decisive
        # sentence, and it self-expires at its `next_chase_ts`. So `parked -> in_progress`
        # on a typed name is a worker overturning a human ruling, not picking their work
        # back up.
        #
        # ⚠️ HOW IT CAME TO BE OPEN, recorded because the mechanism matters more than the
        # fix. It was NOT a defect anyone introduced deliberately: the self-claim carve-out
        # has never looked at `from_status`, so when the account requirement came off at
        # `bd48c140` this edge came off with it. Measured at the real door before Rick was
        # asked, typed owner name and NO account:
        #
        #     queued/blocked/claimed/review -> in_progress   200   (intended, kept)
        #     parked  -> in_progress                          200   (unintended, closed here)
        #     not_approved -> in_progress                     403   (refusal_for_admission)
        #
        # ⇒ THE EXPIRY PATH IS UNTOUCHED AND IS THE REASON THIS COSTS ALMOST NOTHING. A park
        # is bounded and self-expiring: once `next_chase_ts` passes, the row rejoins the owed
        # set automatically at READ time, with no daemon and no human action. This refuses
        # only an EARLY un-park — overturning a hold that is still standing.
        #
        # ⚠️ AND IT IS STILL A POLICY CONTROL, NOT A BOUNDARY. `actor` remains caller-declared
        # everywhere else on this path; requiring an account here raises the cost of
        # overturning a park from "type a name" to "hold a login", which is what Rick asked
        # for. It is not proof of identity and must never be described as one.
        if from_status == rules.PARK_STATUS and not (
                isinstance( account_email, str ) and account_email.strip() ):
            return (
                f"'{item_owner}' owns this row, but it is PARKED — somebody deliberately "
                f"ruled it not-now, and un-parking it is not the same act as picking your "
                f"own work back up. That takes a VALIDATED LOGIN ACCOUNT (Rick's ruling "
                f"2026-09-08: a worker may start their own row, but may not un-park one "
                f"without asking). You are calling with no login account. "
                f"⇒ TWO WAYS FORWARD, and neither is a dead end: authenticate with a Bearer "
                f"token carrying your account, or simply WAIT — a park is self-expiring, so "
                f"this row rejoins the owed set on its own once its chase time passes. "
                f"Every OTHER way into '{PULL_TARGET_STATUS}' is still open to you on a "
                f"typed name; this is the one edge that is not."
            )

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

# ── Sword of Damocles ─────────────────────────────────────────────────────────
# Rick, 2026-09-14 ~22:32 EDT (row ab8c5728): a manager's admit request must name a ticket
# of their own to delete, "and you will make it runtime configurable so I can turn it on
# or off as I see fit". This is that switch. It governs what a request must CARRY at
# filing; a pledge a request already offered is honoured whatever the switch says later.
# Plan: src/rnd/v0.2.1/2026.09.14-sword-of-damocles-enforcement-plan.md §3.1.
INI_KEY_SWORD_OF_DAMOCLES = "task approval sword of damocles active"

# Fails OPEN, like `FALLBACK_ENFORCEMENT_ACTIVE`: a missing config must not start refusing
# every promote request. The shipped INI sets it True, which is where the rule is in force.
FALLBACK_SWORD_OF_DAMOCLES_ACTIVE = False


def get_sword_of_damocles_active():
    """
    Whether an admit request must name a deletion ticket.

    Ensures:
        - returns a bool
        - the stored override wins over the INI key, so Rick's flip lands on the next request
        - strings are parsed by `_as_bool_or_none`, never coerced; junk falls through
        - FALLBACK is False (fails open) — see the constant
        - never raises
    """
    value = _as_bool_or_none( _read_overrides()[ "sword_of_damocles_active" ],
                              STORE_LABEL )
    if value is not None: return value

    value = _as_bool_or_none( _ini_value( INI_KEY_SWORD_OF_DAMOCLES, "string", None ),
                              f"config key '{INI_KEY_SWORD_OF_DAMOCLES}'" )
    if value is not None: return value

    return FALLBACK_SWORD_OF_DAMOCLES_ACTIVE


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
    "sword_of_damocles_active",
)


# The subset of WRITABLE_KEYS whose value is a boolean, and therefore whose PROVENANCE
# depends on whether the stored value parses rather than merely on it being present.
_BOOLEAN_KEYS = ( "enforcement_active", "default_to_holding", "manager_pull_disabled",
                  "sword_of_damocles_active" )


def _validated_bool( key, raw ):
    """
    Return `raw` unchanged if it is a real bool, else raise ValueError naming the key.

    A string is refused, never coerced. `bool( "false" )` is True, so coercing it would switch
    a gate on while the caller believed they had turned it off. The reader parses strings
    for the operator who hand-edits, and nothing should arrive at the writer as one.

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
        - does not canonicalize — `get_approvers` does that on read, and storing a
          canonicalized form would make the stored value disagree with what the operator sent,
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
    "sword_of_damocles_active" : lambda raw: _validated_bool( "sword_of_damocles_active", raw ),
}


def _write_overrides( updates, updated_by ):
    """
    Persist `updates` to the store, atomically, and drop the cached read.

    Requires:
        - updates is a non-empty dict whose values are already validated

    Ensures:
        - the other keys are preserved — this is a PATCH, not a replace
        - the write is one transaction, so a reader sees the old rows or the new ones
        - the cache is invalidated, so the very next read in this process sees the write
        - a failure to reach the store raises OSError, which is what the router already
          answers 500 ("the live values are UNCHANGED"); nothing is half-applied
    """
    try:
        _backend.write( updates, updated_by )
    except Exception as error:
        raise OSError( f"could not write {STORE_LABEL}: {error}" ) from error
    _invalidate_cache()


def current_settings():
    """
    Every approval setting in force right now, with the layer each came from.

    Ensures:
        - returns { key: { "value": <live value>, "source": "override"|"config" } }
        - the value is read through the public reader, so it is what the gate will
          actually use — not the raw stored rows. A settings endpoint that echoes the
          stored rows rather than the effective value is how an operator comes to believe a
          setting is in force while a fallback is overruling it
        - the source is included for the reason the ratio endpoint includes its own: a
          value alone cannot tell an operator whether the INI is in force or is being
          masked by a saved override, which is the one confusion a two-layer scheme
          reliably creates
        - never raises
    """
    overrides = _read_overrides()

    def _source( key ):
        """
        Which layer the effective value actually came from.

        Presence is not provenance. A key can be present and hold a value the reader cannot
        parse, and an unparseable override falls through to the config layer. Reporting
        "override" for it would name a layer that did not produce the value. For a boolean
        the question is whether the value parsed, which `_as_bool_or_none` exists to answer.
        A value nobody can parse is not a decision, so it is not a source either.
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
        "sword_of_damocles_active" : { "value" : get_sword_of_damocles_active(),
                                       "source": _source( "sword_of_damocles_active" ) },
    }


def set_overrides( updated_by=None, **updates ):
    """
    Persist one or more approval settings through the one validated door.

    Validation for every key lives here, so a bad value is refused before anything is stored.

    Requires:
        - every keyword names a key in WRITABLE_KEYS
        - each value satisfies that key's validator (booleans must be real booleans)
        - updated_by is the login account the door resolved from a signature-checked token
          (or None); it is recorded beside each written row and never used to decide anything

    Ensures:
        - raises ValueError on an unknown key or a bad value, naming the offender
        - writes nothing when any key is bad — validation completes for every key
          before the store is touched, so a two-key call cannot half-apply and leave the
          gate in a state the caller never asked for and cannot see
        - unrelated keys already stored are preserved
        - the write is atomic and the read cache is invalidated
        - returns the live settings read back after the write, never the values asked
          for, so a caller reports what took effect rather than what it requested
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

    _write_overrides( validated, updated_by )
    return current_settings()


def set_manager_pull_disabled( disabled, updated_by=None ):
    """
    Persist the pull toggle, atomically, and return the live value after the write.

    A validated write path makes the flag a control rather than a file: with a hand edit,
    `bool( "false" )` could turn a switch on.

    Requires:
        - disabled is a real bool. A string is refused, not coerced — the reader parses
          strings for the operator who hand-edits, but nothing should arrive as one.

    Ensures:
        - raises ValueError on any non-bool, naming what it got
        - the other stored keys are preserved — this is a PATCH of one
          key, not a replace. Clobbering `approvers` while flipping a toggle would take
          the approval gate down as a side effect of an unrelated switch
        - the write is atomic (one database transaction), so a concurrent reader sees the
          old row or the new one, never a half-written one
        - the in-process cache is invalidated, so the very next read goes back to the
          store. Without this, a read right after the write could return the old cached
          value for up to CACHE_TTL_SECONDS
        - returns the value actually in force after the write, read back through
          `get_manager_pull_disabled()` rather than echoed from the argument, so a
          caller reports what took effect rather than what it asked for

    The body delegates to `_validated_bool` and `_write_overrides`, which `set_overrides`
    shares, because four keys need the identical machinery and a second copy is two things
    to keep in step. This function stays as the named door for the one key that already had
    callers and tests.
    """
    _validated_bool( "manager_pull_disabled", disabled )
    _write_overrides( { "manager_pull_disabled": disabled }, updated_by )
    return get_manager_pull_disabled()


# ── THE CREATE DOOR (Rick's P0, row 0ef62dfd, 2026-09-08) ─────────────────────
#
# THE DEFECT THIS CLOSES. `default_mint_status()` above is applied by the router
# ONLY when the caller omitted `status` — an explicit `status="queued"` wins, and
# the comment at that call site says so on purpose: "Explicit intent always wins
# over a default." So the holding area could be bypassed by NAMING the thing it
# defaults you away from. Measured 2026-09-08: three rows of María's were live on
# Rick's board having never entered holding, so there was no pending request for
# him to approve OR deny.
#
# 🔴 THAT IS NOT A GATE DEFAULTING TO YES. It is a gate that was never consulted,
# which is worse — a denial leaves an audit event and this left nothing.
#
# HIS RULING, quoted: "I want to refuse a live status on create except in the case
# of P0 tickets." The P0 carve-out is his and it is not a loophole by accident:
# he sets P0 himself, so a caller minting one live is claiming an instruction he
# can check. Every other priority goes to holding and waits for him.
#
# ⚠️ WHY THIS IS A PREDICATE AND NOT AN `if` IN THE ROUTER. The router's own
# bypass was invisible because it lived inside a comment explaining why it was
# correct. A named function with its own tests can be asserted about — and the
# wiring test can prove the router still calls it, which is the failure mode that
# kills gates silently (a control perfectly implemented and imported by nobody).

def refusal_for_live_mint( requested_status, status_was_explicit, priority, caller_is_operator ):
    """
    Decide whether a create may mint a live status, or must go to the holding area.

    Requires:
        - requested_status is a string naming the status the create would mint
        - status_was_explicit is True iff the caller named `status` on the payload
          (the router reads pydantic's `model_fields_set`; an omitted field and an
          explicit "queued" are the same string and only this flag separates them)
        - priority is the create's priority string
        - caller_is_operator is True iff the router proved the caller is Rick from a
          validated account (`task_priority_firewall.caller_is_operator`), never
          from a caller-declared string

    Ensures:
        - returns None when the mint is allowed
        - returns a non-empty refusal string when it is not, naming the row's own
          way forward (omit `status`, or carry a P0 Rick set)
        - returns None whenever the holding-area default is off — there is no
          holding area to bypass on such a deployment, and refusing there would
          break callers who never had a gate
        - returns None for an explicit mint of the holding status itself: asking
          to go where the gate would send you is not a bypass
        - returns None for the operator: the operator's create is the approval
        - never raises; an unreadable config leaves the door as it is today
    """
    if not status_was_explicit:                      return None
    if default_mint_status() != NOT_APPROVED_STATUS: return None
    if requested_status == NOT_APPROVED_STATUS:      return None
    if str( priority ).strip().upper() == "P0":      return None

    # 🔴 THE OPERATOR IS EXEMPT — added 2026-09-11 (María, row 2d786391) when this
    # branch landed, because the door gained a caller after 09-08 that the original
    # commit could not have known about: Rick's own New Ticket card (row c9895403).
    # `shared/task-create.js` sends status="queued" whenever his "approved" field is
    # on, and he ruled that field defaults to approved. Without this line his own P1
    # or P2 ticket would be refused 403 by a gate whose whole premise is "I am the
    # only 1 who approves a move" — his create with approved=true IS that approval.
    # A BOOL, not an account: `task_priority_firewall` already imports this module,
    # so the proof is computed at the router and handed in.
    if caller_is_operator:                           return None

    # 🔴 BLOCKED IS *NOT* EXEMPT — Rick ruled it, 2026-09-08 ~15:35 EDT.
    # I asked whether his 2026-07-20 one-call blocked mint should survive this rule
    # and he said no. A blocked row is on the live board, so minting one straight
    # from a create bypasses holding exactly as a queued mint does. Holding is now
    # the only way onto the board, P0 aside.
    # ⇒ CONSEQUENCE, recorded rather than left for someone to discover: the
    # manager-only blocked-mint guard further down routers/tasks.py is now reached
    # only by a P0 or by the operator — every other explicit blocked mint is refused
    # here first. It is NOT removed — that is a separate change with its own blast
    # radius, and it still guards the two paths that pass this door.


    return (
        f"create refused: this row asks to be minted '{requested_status}', which puts it "
        f"straight onto the live board without ever entering the holding area — so there "
        f"is no request for the approver to allow or deny. Rick's ruling of 2026-09-08: a "
        f"create may name a live status ONLY for a P0, and this one is '{priority}'. "
        f"⇒ OMIT `status` and the row lands in '{NOT_APPROVED_STATUS}' and waits for him. "
        f"That is not a rejection of the content — the row is filed either way."
    )
