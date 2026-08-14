"""
self_respin() core — the testable engine behind the MCP verb (row 9e0678f6, WI-2).

A manager at its context ceiling types `/clear` into its OWN pane and rehydrates
as the same seat (same session id, tmux, persona, board, lineage) from its
repo-root memento — for the price of one memento write instead of a whole
successor's context. The mechanism already ships: a DETACHED, sleeping tmux
injector (hook_common.inject_qualifier_via_tmux) that outlives the caller. This
module is the guarded front door to it.

The verb is IRREVERSIBLE (it zeroes the seat's context), so every guard lives at
the chokepoint — INSIDE the verb, never a caller obligation (Krishna's ruling):

  (a) MEMENTO VERIFY — option (b): the caller stamps a fresh {uuid, iso_ts} nonce
      line into the memento at write time and passes the uuid. The verb confirms
      that exact uuid is on disk AND its stamped ts is within the cycle window —
      proving the memento is complete (a partial write never carries the nonce)
      AND fresh-THIS-cycle (an 8-day-stale body carries an old uuid). Existence is
      neither. Fail ⇒ abort, never clear into nothing.

  (b) CONFIRMATION GATE — the verb itself asks (no caller "already-confirmed"
      kwarg exists). default="yes"; offline / timeout / None / 503 → PROCEED
      (the inverse of the fleet's normal offline→defer reflex — an absent user
      must not cost a manager). A REAL human "no"/"neither" schedules nothing.

  (c) ONE-SHOT AT THE FIRE POINT — the double-fire that matters is a detached
      injection firing AFTER rehydrate, clearing a fresh context. No Python that
      runs later can recall a sleeping detached process, so the guard sits in the
      injected command: `sleep && rm <fire-token> && send-keys /clear`. The FIRST
      fire's `rm` consumes the token; any second fire finds it gone and no-ops.

  wrap=False is LOAD-BEARING and proven at the call site: the injected argv
  carries the verbatim slash command "/clear" and never passes through
  speakerphone_wrap — a wrapped "/clear" becomes a system-reminder blob and never
  fires as a slash command.

The observer's marker (cosa.agents.heartbeat_arbiter.self_respin_observer) is a
SEPARATE file that must PERSIST through the fire (its absence past the deadline is
how the observer detects a dead seat), so it is never the file the injector rm's.

PURITY: every side-effecting seam (tmux resolve, the ask, the detached schedule,
the memento read) is injectable, so the whole decision tree is unit-provable with
fakes. This module makes NO task-store calls — the verb must not mark its own row
done (it is cleared before it could; the observer owns done-state).
"""

import datetime
import os
import subprocess

from dataclasses import dataclass

from cosa.agents.heartbeat_arbiter.self_respin_observer import build_marker_dict, _parse_iso


# The literal ask_yes_no prepends on any non-answer (cosa_voice_mcp.DEFAULT_USED_MARKER).
# Kept as an INJECTABLE default so the MCP wrapper passes the server's own constant
# (single source at the call site) without this module importing the MCP server.
DEFAULT_USED_MARKER          = "[default used] "

FIRE_TOKEN_PREFIX            = ".self-respin-fire-"
NONCE_LINE_PREFIX            = "SELF-RESPIN-NONCE:"     # caller stamps: "SELF-RESPIN-NONCE: <uuid> @ <iso_ts>"
DEFAULT_DELAY_SECONDS        = 20
DEFAULT_CYCLE_WINDOW_SECONDS = 300                      # memento nonce ts must be within this of now


@dataclass
class SelfRespinResult:
    """The verb's structured outcome. `status` is the whole story:
    scheduled = a /clear is queued; declined = human said no; aborted = a guard
    failed (memento/tmux/marker) and nothing was scheduled."""
    status             : str                 # "scheduled" | "declined" | "aborted"
    reason             : str
    marker_path        : "str | None" = None
    fire_token_path    : "str | None" = None
    expected_return_by : "str | None" = None


# ---------------------------------------------------------------------------
# (b) The confirmation-gate decision — pure
# ---------------------------------------------------------------------------
def gate_proceed( ask_result, *, default_used_marker=DEFAULT_USED_MARKER ):
    """
    Decide PROCEED vs ABORT from an ask_yes_no return string.

    Requires:
        - ask_result is the ask_yes_no return (a string), or anything defensively
        - default_used_marker is the prefix ask_yes_no prepends on a non-answer

    Ensures:
        - PROCEED (True) iff the result carries the default-used prefix (offline /
          timeout / None / 503 → the "yes" default was substituted) OR the human's
          clean answer begins "yes"
        - ABORT (False) for a real "no"/"neither", or a non-string
        - returns ( proceed: bool, reason: str )
        - never raises
    """
    if not isinstance( ask_result, str ):
        return False, "no answer string — abort (fail safe: do not clear)"
    if ask_result.startswith( default_used_marker ):
        return True, "default used (offline/timeout/None/503) → PROCEED per default=yes"
    answer = ask_result.strip().lower()
    if answer.startswith( "yes" ):
        return True, "human answered yes"
    return False, f"human declined ({ask_result.strip()}) — schedule nothing"


# ---------------------------------------------------------------------------
# (a) The memento freshness/completeness proof — pure
# ---------------------------------------------------------------------------
def build_nonce_line( nonce_uuid, ts ):
    """
    Ensures:
        - returns the canonical stamp line the caller writes into the memento:
          "SELF-RESPIN-NONCE: <uuid> @ <iso_ts>" (aware ISO)
    """
    return f"{NONCE_LINE_PREFIX} {nonce_uuid} @ {ts.isoformat()}"


def verify_memento_content( content, nonce_uuid, now, *, cycle_window_seconds=DEFAULT_CYCLE_WINDOW_SECONDS ):
    """
    Prove the memento on disk is COMPLETE and FRESH-THIS-CYCLE (option (b)).

    Requires:
        - content is the memento file text (or None when the file was unreadable)
        - nonce_uuid is the uuid the caller stamped this cycle (str), or None/""
        - now is an aware datetime

    Ensures:
        - ( False, reason ) when: content is empty/None; nonce_uuid is blank; no
          `SELF-RESPIN-NONCE: <nonce_uuid> @ <ts>` line is present (memento not
          written this cycle, or a partial write that never reached the nonce); the
          stamped ts is naive/unparseable; or the ts is outside ±cycle_window of now
          (a stale body carries an old stamp)
        - ( True, reason ) only when the exact nonce line is present AND its ts is
          fresh — existence alone is never enough
        - never raises
    """
    if not content or not content.strip():
        return False, "memento missing or empty — refusing to clear into nothing"
    if not nonce_uuid:
        return False, "no memento nonce supplied — cannot prove this-cycle freshness"

    stamped_ts = None
    needle     = f"{NONCE_LINE_PREFIX} {nonce_uuid} @ "
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith( needle ):
            stamped_ts = _parse_iso( stripped[ len( needle ): ].strip() )
            break

    if stamped_ts is None:
        return False, "memento nonce not found (or its timestamp is naive/unparseable) — stale or partial write"

    # Directional freshness (Krishna nit 1): the stamp must be in the recent PAST,
    # never the future. Caller and verb share one host + one clock, so a stamp is
    # always <= now; a future ts means a corrupt/forged stamp, not a fresh write.
    age = ( now - stamped_ts ).total_seconds()
    if age < 0:
        return False, "memento nonce is future-dated — corrupt or forged stamp, refusing to clear"
    if age > cycle_window_seconds:
        return False, f"memento nonce is stale ({int( age )}s > {cycle_window_seconds}s window) — not written this cycle"
    return True, "memento verified complete + fresh this cycle"


# ---------------------------------------------------------------------------
# (c) The guarded, fire-point-consuming injector argv — pure
# ---------------------------------------------------------------------------
def build_guarded_clear_argv( tmux_session, fire_token_path, delay, text="/clear" ):
    """
    Build the detached Popen argv that types `text` into a pane AFTER consuming a
    one-shot fire token — the double-fire guard sits where the keystrokes land.

    Requires:
        - tmux_session is the target pane's tmux session name
        - fire_token_path is the one-shot token the FIRST fire rm's
        - delay is seconds the detached process sleeps before firing

    Ensures:
        - returns a `bash -c` argv whose script is
          `sleep $1 && rm $4 && tmux send-keys -t $2 -l -- $3 && sleep 0.25 && tmux send-keys -t $2 Enter`
          — `rm $4` (no -f) SHORT-CIRCUITS send-keys when the token is already
          gone, so a second detached fire after rehydrate no-ops
        - `text` is passed VERBATIM as a positional arg — never wrapped by the
          speakerphone rider (a wrapped "/clear" would never fire as a slash cmd)
    """
    bash = (
        'sleep "$1" && rm "$4" && tmux send-keys -t "$2" -l -- "$3" '
        '&& sleep 0.25 && tmux send-keys -t "$2" Enter'
    )
    return [ "bash", "-c", bash,
             "_",                       # $0 placeholder
             str( delay ),             # $1
             tmux_session,             # $2
             text,                     # $3  (verbatim "/clear" — NOT wrapped)
             fire_token_path ]         # $4  (the one-shot, rm'd at the fire point)


# ---------------------------------------------------------------------------
# Default (live) seams — thin IO boundaries, injected away in tests
# ---------------------------------------------------------------------------
def _default_resolve_tmux( session_id ):   # pragma: no cover - live bridge read
    """
    Ensures: returns the session's tmux_session from its bridge, or None — resolved
    by EXACT full-id match (exact=True). Self-respin is irreversible and self-aimed,
    so an 8-char-prefix collision with another live seat must never redirect the
    /clear to the wrong pane (Krishna/Cheech merge gate).
    """
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
    data = find_session_by_id( session_id, exact=True )
    return data.get( "tmux_session" ) if data else None


def _default_read_text( path ):
    """Ensures: returns the file's text, or None when unreadable (never raises)."""
    try:
        with open( path, "r" ) as f:
            return f.read()
    except OSError:
        return None


def _default_schedule( argv ):   # pragma: no cover - live detached subprocess boundary
    """Spawn the detached injector exactly as production does (outlives the caller)."""
    subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _write_json_atomic( path, data ):
    """Ensures: atomic (temp→rename) JSON write via the shared bridge helper."""
    from lupin_cli.claude_code.hooks.lib.session_bridge import atomic_write_json
    atomic_write_json( path, data )


# ---------------------------------------------------------------------------
# The orchestrator — every guard in order, every side effect injectable
# ---------------------------------------------------------------------------
def perform_self_respin(
    session_id,
    *,
    persona,
    memento_path,
    memento_nonce,
    pre_clear_status,
    pre_clear_pct,
    delay_seconds        = DEFAULT_DELAY_SECONDS,
    cycle_window_seconds = DEFAULT_CYCLE_WINDOW_SECONDS,
    grace_seconds        = None,
    base_dir             = None,
    now                  = None,
    resolve_tmux_fn      = None,
    ask_fn               = None,
    schedule_fn          = None,
    read_text_fn         = None,
    write_json_fn        = None,
):
    """
    Run the full self-re-spin decision + (on a go) schedule the detached /clear.

    ORDER (each guard is a hard gate; a failure returns without scheduling):
      1. resolve the seat's tmux session          — no session ⇒ aborted
      2. verify the memento (nonce + freshness)    — fail ⇒ aborted (clear into nothing averted)
      3. fire the confirmation ask, always         — real "no"/"neither" ⇒ declined
      4. write the persistent OBSERVER marker + read it back for durability
         AND write the one-shot FIRE token         — read-back fail ⇒ aborted
      5. schedule the guarded, fire-point-consuming detached /clear

    Requires:
        - session_id, persona non-empty; memento_path points at the seat's memento
        - memento_nonce is the uuid the caller stamped into that memento this cycle
        - pre_clear_status is the seat's context-pressure `status` at fire time
          (recorded so the observer can prove the over_budget→within_budget return)
        - the *_fn seams are callables (or None ⇒ the live defaults)

    Ensures:
        - returns a SelfRespinResult; status ∈ {scheduled, declined, aborted}
        - NO detached /clear is scheduled unless memento verify passed AND the ask
          resolved to yes/default-yes AND the observer marker is durable on disk
        - the ask is ALWAYS called on the go-path — there is no kwarg that skips it
        - makes NO task-store calls (the verb never marks its own row done)
        - never raises on an injected-seam failure it can classify; a genuinely
          unexpected error propagates (the caller — the MCP tool — wraps it)
    """
    now             = now             if now             is not None else datetime.datetime.now( datetime.timezone.utc )
    resolve_tmux_fn = resolve_tmux_fn if resolve_tmux_fn is not None else _default_resolve_tmux
    ask_fn          = ask_fn          if ask_fn          is not None else _default_ask
    schedule_fn     = schedule_fn     if schedule_fn     is not None else _default_schedule
    read_text_fn    = read_text_fn    if read_text_fn    is not None else _default_read_text
    write_json_fn   = write_json_fn   if write_json_fn   is not None else _write_json_atomic

    # 1. resolve tmux session
    tmux_session = resolve_tmux_fn( session_id )
    if not tmux_session:
        return SelfRespinResult( status="aborted", reason="no tmux session in the bridge for this seat" )

    # 2. memento verify — BEFORE the ask (no point asking to clear into nothing)
    ok, reason = verify_memento_content(
        read_text_fn( memento_path ), memento_nonce, now, cycle_window_seconds=cycle_window_seconds
    )
    if not ok:
        return SelfRespinResult( status="aborted", reason=f"memento verify failed: {reason}" )

    # 3. confirmation ask — ALWAYS runs on this path; no skip kwarg exists
    proceed, gate_reason = gate_proceed( ask_fn() )
    if not proceed:
        return SelfRespinResult( status="declined", reason=gate_reason )

    # 4. persistent observer marker (durability read-back) + one-shot fire token
    marker = build_marker_dict(
        session_id=session_id, persona=persona, tmux_session=tmux_session,
        fired_at=now, delay_seconds=delay_seconds,
        pre_clear_status=pre_clear_status, pre_clear_pct=pre_clear_pct,
        memento_path=memento_path, memento_verified=True,
        **( { "grace_seconds": grace_seconds } if grace_seconds is not None else {} ),
    )
    base            = base_dir if base_dir is not None else _resolve_base_dir()
    marker_path     = os.path.join( base, f"{_MARKER_PREFIX}{session_id}.json" )
    fire_token_path = os.path.join( base, f"{FIRE_TOKEN_PREFIX}{session_id}.token" )

    write_json_fn( marker_path, marker )
    if not _readback_ok( read_text_fn, marker_path, session_id ):
        return SelfRespinResult(
            status="aborted",
            reason="observer marker did not survive read-back — refusing to clear without a durable record",
        )
    write_json_fn( fire_token_path, { "session_id": session_id, "fired_at": now.isoformat() } )
    # Read-back the FIRE token too (Krishna nit 2): a silent token-write failure
    # would let the verb report "scheduled" while the /clear self-cancels at the
    # fire point (rm fails → no send-keys). Catch it here and fail fast — and
    # remove the observer marker we just wrote so it cannot raise a DEAD alarm for
    # a clear the caller already knows never scheduled.
    if not _readback_ok( read_text_fn, fire_token_path, session_id ):
        _best_effort_remove( marker_path )
        return SelfRespinResult(
            status="aborted",
            reason="fire token did not survive read-back — refusing to schedule a clear that would self-cancel",
        )

    # 5. schedule the guarded, fire-point-consuming detached /clear
    schedule_fn( build_guarded_clear_argv( tmux_session, fire_token_path, delay_seconds ) )

    return SelfRespinResult(
        status="scheduled",
        reason="memento verified, gate passed, marker durable — detached /clear scheduled",
        marker_path=marker_path,
        fire_token_path=fire_token_path,
        expected_return_by=marker[ "expected_return_by" ],
    )


def _best_effort_remove( path ):
    """Ensures: removes `path` if present; a missing file or OS error is swallowed."""
    try:
        os.remove( path )
    except OSError:
        pass


def _readback_ok( read_text_fn, marker_path, session_id ):
    """Ensures: True iff the just-written marker reads back and names this session."""
    import json
    raw = read_text_fn( marker_path )
    if not raw:
        return False
    try:
        return json.loads( raw ).get( "session_id" ) == session_id
    except ( ValueError, AttributeError ):
        return False


def _resolve_base_dir():   # pragma: no cover - live fleet_data_root read (tests pass base_dir)
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return str( fleet_data_root() )


def self_respin_from_bridge(
    memento_path,
    memento_nonce,
    *,
    delay_seconds        = DEFAULT_DELAY_SECONDS,
    cycle_window_seconds = DEFAULT_CYCLE_WINDOW_SECONDS,
    identity_fn,
    pressure_fn,
    perform_fn           = perform_self_respin,
):
    """
    Resolve THIS seat's own identity + pre-clear pressure, then run the verb.

    The safety rule (Cheech): the session id is resolved from the BRIDGE, never
    accepted from the caller — a caller-supplied id is how a verb aimed at your
    own pane ends up aimed at someone else's. So this takes an `identity_fn`
    (the bridge resolver), not a session_id argument.

    Requires:
        - identity_fn() → ( session_id, persona ) resolved from the local bridge
        - pressure_fn( persona ) → ( pre_clear_status, pre_clear_pct ) — the seat's
          own context-pressure `status`/pct at fire time (best-effort; the caller's
          live default is fine when the sensor is unreachable)
        - perform_fn is perform_self_respin (or a test double)

    Ensures:
        - returns a SelfRespinResult
        - a bridge that yields no session id ⇒ aborted (never a blind clear)
        - session_id is NEVER read from a caller argument
        - never raises on an identity/pressure seam that returns cleanly
    """
    session_id, persona = identity_fn()
    if not session_id:
        return SelfRespinResult( status="aborted", reason="could not resolve own session id from the bridge" )

    pre_clear_status, pre_clear_pct = pressure_fn( persona )
    return perform_fn(
        session_id,
        persona              = persona,
        memento_path         = memento_path,
        memento_nonce        = memento_nonce,
        pre_clear_status     = pre_clear_status,
        pre_clear_pct        = pre_clear_pct,
        delay_seconds        = delay_seconds,
        cycle_window_seconds = cycle_window_seconds,
    )


def resolve_identity_from_cc_meta( cc_meta, fallback_sid ):
    """
    Resolve ( session_id, persona ) from bridge metadata — the same precedence the
    injector and _flip_speakerphone use (stable_session_id wins for /clear-resistance).

    Requires:
        - cc_meta is the session-bridge metadata dict (may be partial/empty)
        - fallback_sid is the module-level SESSION_ID prefix used when the bridge
          carries neither a stable nor a plain session id

    Ensures:
        - session_id = stable_session_id or session_id or fallback_sid
        - persona    = voice_persona.name, or "unknown" when unset
        - never raises
    """
    sid     = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or fallback_sid
    persona = ( cc_meta.get( "voice_persona" ) or {} ).get( "name" ) or "unknown"
    return sid, persona


def resolve_own_identity( get_cc_meta_fn, fallback_sid ):
    """
    Resolve THIS seat's ( session_id, persona ), fetching bridge metadata via
    `get_cc_meta_fn` and tolerating its failure — so the fallback-on-error logic
    is HERE (unit-testable), not stranded in a wrapper closure the core cannot reach.

    Requires:
        - get_cc_meta_fn() → the session-bridge metadata dict (may raise)
        - fallback_sid is the module-level SESSION_ID prefix

    Ensures:
        - a raising get_cc_meta_fn ⇒ resolves against {} ⇒ ( fallback_sid, "unknown" )
        - otherwise resolves via resolve_identity_from_cc_meta
        - never raises
    """
    try:
        cc_meta = get_cc_meta_fn()
    except Exception:
        cc_meta = {}
    return resolve_identity_from_cc_meta( cc_meta, fallback_sid )


def _live_own_pressure( persona ):   # pragma: no cover - live :8001 pressure read (tests inject pressure_fn)
    """
    Read THIS persona's own context-pressure record for the pre-clear stamp.

    Ensures:
        - returns ( status, consumption_pct_of_window ) from the live payload
        - when the sensor is unreachable or the persona is absent, records the
          status as "unknown" with pct None — NEVER a manufactured "over_budget".
          A forged status is a CLAIM that a reading happened; a missed reading is
          "unknown", recorded as unknown. The observer then treats it as an
          unobserved pre-clear state rather than an observed over-budget one.
    """
    try:
        from cosa.agents.heartbeat_arbiter.self_respin_observer import _fetch_live_pressure
        section = _fetch_live_pressure() or {}
        record  = ( section.get( "personas" ) or {} ).get( persona ) or {}
        status  = record.get( "status" ) or "unknown"
        return status, record.get( "consumption_pct_of_window" )
    except Exception:
        return "unknown", None


def _default_ask():   # pragma: no cover - live MCP ask boundary (tests inject ask_fn)
    """
    Fire the confirmation ask on the human surface, default=yes, and return the
    raw ask_yes_no string. Imported lazily so this module never pulls the MCP
    server in at import time.
    """
    from lupin_mcp.cosa_voice_mcp import ask_yes_no, DEFAULT_USED_MARKER as _M   # noqa: F401
    return ask_yes_no.fn(
        question="You are at your context ceiling. Self-re-spin (clear + rehydrate) now?",
        default="yes",
        timeout_seconds=120,
        priority="high",
        abstract="Manager self-re-spin: I will write my memento, verify it on disk, and type /clear into my "
                 "own pane, rehydrating as the same seat at low context. Defaults to YES if you are away.",
    )


# The observer's marker prefix — imported by name so the two files agree on the
# ONE filename shape (build_marker_dict's schema, MARKER_PREFIX's name).
from cosa.agents.heartbeat_arbiter.self_respin_observer import MARKER_PREFIX as _MARKER_PREFIX
