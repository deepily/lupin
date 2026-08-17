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
import uuid

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

# The wake-after-clear readiness gate (row 275cb0b9, GAP 1 + John's ruling 1). The
# rehydrated seat is proven ready by its BRIDGE FILE being rewritten (SessionStart
# fires on the /clear path and atomic_write_json's the bridge — register_session.py),
# NOT by a send-keys exit code (tmux returns 0 for "keystrokes delivered" regardless
# of what the app did — gating on it rebuilds this very row's bug inside its fix). The
# detached injector polls the bridge mtime up to READY_TIMEOUT_POLLS × POLL_INTERVAL
# seconds; on timeout it gives up LOUDLY (stderr) and types NOTHING rather than landing
# the wake in the pre-reset (old) context.
DEFAULT_READY_TIMEOUT_POLLS   = 40                     # 40 × 0.5s = 20s bounded wait for the rehydrate write
DEFAULT_POLL_INTERVAL_SECONDS = 0.5


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
def build_wake_text( memento_path, wake_nonce, wake_proof_path ):
    """
    Ensures:
        - returns a SINGLE-LINE rehydrate prompt (no embedded newlines — it is typed
          via `send-keys -l` then one Enter, so a newline would submit early) that:
          (a) states only what THIS side can prove — a /clear was fired at the pane and
          the bridge then reported a new session — and asks the seat to decide whether
          it actually rehydrated; (b) instructs it to write `wake_proof_path` containing
          the exact line "SELF-RESPIN-WAKE-PROOF: <nonce>" ONLY IF it did, and to write
          a dispute instead if it did not. The nonce is what proves the wake reached a
          real turn and was OURS — the observer keys RETURNED on that proof (a peer DM
          cannot echo an unknown nonce).

    🔴 WHY THIS DOES NOT SAY "you just re-spun" (bug e88ebfae, Cheech 2026-08-17).
    It used to. The wake is composed from the SCHEDULING artifact — the nonce it quotes
    comes from the marker written before the /clear was even sent — so it can prove
    "a clear was scheduled and its token was consumed" and nothing more. On the run
    that found this, the pane never cleared: the seat read 519,378 tokens / 51.9% of
    window at the moment the wake arrived, and the wake told it, in the second person,
    that it had rehydrated at low context. The seat correctly refused to write the
    proof, because a proof marker is a receipt and a receipt for an event that did not
    happen is a plausible fact on disk that the observer, a peer, or a later reader
    takes as evidence.

    Only the process can answer whether it was cleared, so the wake ASKS instead of
    asserting, and names the check that separates the two cases: a rehydrated seat has
    no memory of the work and has to read its memento to learn what it was doing. That
    check costs the seat one sentence of self-examination and closes the gap that no
    amount of disk-side evidence can.
    """
    return (
        f"A /clear was fired at this pane and the bridge then reported a new session, so you "
        f"were PROBABLY just re-spun as the same seat — but only you can confirm it. Check: do you "
        f"remember the work of this session, or is your context near-empty and this the first you "
        f"have seen of it? IF you rehydrated, write {wake_proof_path} containing exactly this line: "
        f"{_WAKE_PROOF_NONCE_LINE} {wake_nonce} — then read your memento at {memento_path} and resume "
        f"your board. IF YOU DID NOT — you still hold the session in memory — write NO proof; instead "
        f"put the evidence in {_DISPUTE_PREFIX}<your-full-session-id>.md and tell your manager the "
        f"wake fired without a clear."
    )


def build_guarded_clear_argv(
    tmux_session, fire_token_path, delay, text="/clear",
    *, wake_text=None, bridge_path=None, keys_sent_path=None,
    ready_timeout_polls=DEFAULT_READY_TIMEOUT_POLLS,
    poll_interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
):
    """
    Build the detached Popen argv that types `text` into a pane AFTER consuming a
    one-shot fire token — the double-fire guard sits where the keystrokes land.

    Requires:
        - tmux_session is the target pane's tmux session name
        - fire_token_path is the one-shot token the FIRST fire rm's
        - delay is seconds the detached process sleeps before firing
        - wake_text (optional): when given, a rehydrate prompt typed AFTER the /clear
          is PROVEN to have reset; bridge_path must also be given
        - bridge_path (optional): the seat's bridge file; the injector waits for ITS
          mtime to change (SessionStart rewrites it on the /clear path) before typing
          the wake — the readiness proof (John's ruling 1), never a send-keys exit code

    Ensures:
        - DEFAULT (wake_text is None): returns the original single-chain argv
          `sleep $1 && rm $4 && tmux send-keys -t $2 -l -- $3 && sleep 0.25 && tmux send-keys -t $2 Enter`
          — `rm $4` (no -f) SHORT-CIRCUITS send-keys when the token is already gone,
          so a second detached fire after rehydrate no-ops
        - WAKE (wake_text given): returns ONE bash script (ruling 3 — no second Popen)
          that, in the SAME chain, fires the guarded /clear, then captures the bridge
          mtime, polls it (bounded by ready_timeout_polls × poll_interval_seconds) until
          it CHANGES, then types the wake with `-l` (literal); on timeout it writes a
          loud stderr line and types nothing (a mute seat is left for the observer to
          alarm, never a wake into the old context)
        - the injector writes NO ARRIVAL receipt: a receipt written HERE would prove
          only that the injector reached the line, never that the pane ingested the
          keystrokes (`tmux send-keys` has no ingestion feedback). Proof of a real wake
          is CONSUMER-side — the wake text (built by build_wake_text) instructs the
          rehydrated seat to write a nonce-echoing proof artifact, which the observer
          keys RETURNED on. This function only delivers the wake behind the readiness gate.
        - `keys_sent_path` (optional) is the ONE thing the injector does stamp, and it is
          NOT an exception to the rule above (row 855e4dd0, Mr Radio's ruling 2026-08-17).
          It records WHEN WE TRIED — a fact about this chain's own action, the only thing
          it genuinely knows — by creating an empty file whose MTIME is the timestamp.
          The observer measures its DEAD_NO_RETURN window from that instead of from the
          schedule, because a busy pane buffers `/clear` until its next turn boundary and
          would otherwise be called dead while merely queued.
          WHY THIS IS NOT THE FORBIDDEN RECEIPT: anchoring on ARRIVAL would be circular —
          DEAD_NO_RETURN exists precisely to fire when no proof of arrival EVER shows up,
          so a clock started at arrival could never start in the one case the alarm exists
          to catch. The deadline has to measure how long since we tried.
          Failing to write it is NEVER fatal: the chain proceeds, and a missing stamp
          simply leaves the observer on its old schedule-time anchor, which still alarms.
        - `text` (and the wake) are passed VERBATIM as positional args — never wrapped
          by the speakerphone rider (a wrapped "/clear" would never fire as a slash cmd)
    """
    if wake_text is None:
        bash = (
            'sleep "$1" && rm "$4" && tmux send-keys -t "$2" -l -- "$3" '
            # The stamp hangs off the SAME && chain, so a short-circuited fire (the
            # one-shot token already gone) never stamps a send that did not happen.
            # `[ -z "$5" ] ||` skips it when no path was given, and the trailing
            # `|| true` swallows ONLY a failed redirect — it must never wrap the whole
            # chain, or a short-circuited fire would report success.
            '&& sleep 0.25 && tmux send-keys -t "$2" Enter '
            '&& { [ -z "$5" ] || : > "$5" || true; }'
        )
        return [ "bash", "-c", bash,
                 "_",                       # $0 placeholder
                 str( delay ),             # $1
                 tmux_session,             # $2
                 text,                     # $3  (verbatim "/clear" — NOT wrapped)
                 fire_token_path,          # $4  (the one-shot, rm'd at the fire point)
                 keys_sent_path or "" ]    # $5  (send stamp; mtime IS the timestamp)

    # Wake path — ONE chain: guarded /clear, then a bridge-SESSION-ID readiness gate,
    # then the wake. `rm "$4" || exit 0` keeps the one-shot guard (a second fire finds
    # the token gone and does nothing).
    #
    # 🔴 THE GATE READS THE BRIDGE'S session_id VALUE, NOT ITS MTIME (bug e88ebfae).
    # It used to poll the mtime and break on any bump. That gate cannot tell a rehydrate
    # from ordinary work, because `touch_bridge_mtime()` — session_bridge.py, REDLINE C1
    # — is called from the PostToolUse hook on EVERY tool call of EVERY session. A seat
    # still running its turn (exactly the seat whose `/clear` is buffered until the next
    # turn boundary) bumps its own bridge mtime within milliseconds, the gate opens on
    # that bump, and the wake is typed into the UN-cleared pane. That is how Cheech's
    # 2026-08-17 run got a wake at 519,378 tokens / 51.9% of window. It is intermittent
    # for exactly this reason: on a QUIET seat no tool call intervenes, so the first
    # bump really is SessionStart's rewrite and the gate is accidentally right.
    #
    # The transient `session_id` is immune to that confusion. C1 makes
    # touch_bridge_mtime a BARE `os.utime()` with no content write, so no amount of
    # tool-call activity can change the value; only a SessionStart re-registration
    # rewrites it, and on a clear the transient id diverges from stable_session_id
    # (register_session.py: "On subsequent lifecycle events (compact, clear), they
    # diverge"). Honest limit: a COMPACT also mints a new transient id, so this proves
    # "a new session began", not "a clear specifically" — which is why the wake text it
    # gates asks the seat to confirm rather than asserting the rehydrate outright.
    #
    # `^ *"session_id"` anchors past the leading indent of json.dump(indent=2) so it
    # cannot match the `"stable_session_id"` line, whose key merely CONTAINS the same
    # substring. An empty read (bridge briefly absent or unreadable) is NOT a change:
    # the `[ -n "$s" ]` guard keeps a failed read from opening the gate, so the failure
    # direction stays mute-and-alarm rather than wake-into-the-old-context.
    _sid = 'grep -o \'^ *"session_id"[[:space:]]*:[[:space:]]*"[^"]*"\' "$6" 2>/dev/null | head -1'
    bash = (
        'sleep "$1" || exit 0\n'
        'rm "$4" || exit 0\n'
        f's0=$({_sid})\n'
        'tmux send-keys -t "$2" -l -- "$3" || exit 0\n'
        'sleep 0.25\n'
        'tmux send-keys -t "$2" Enter || exit 0\n'
        '[ -n "$9" ] && : > "$9"\n'
        'polls=0\n'
        'while :; do\n'
        f'  s=$({_sid})\n'
        '  if [ -n "$s" ] && [ "$s" != "$s0" ]; then break; fi\n'
        '  polls=$((polls + 1))\n'
        '  if [ "$polls" -ge "$7" ]; then\n'
        '    echo "self-respin wake: bridge $6 still reports the same session_id after $7 polls — reset not proven; NOT sending wake (seat may be mute; the observer will alarm)" >&2\n'
        '    exit 3\n'
        '  fi\n'
        '  sleep "$8"\n'
        'done\n'
        'tmux send-keys -t "$2" -l -- "$5"\n'
        'sleep 0.25\n'
        'tmux send-keys -t "$2" Enter\n'
    )
    return [ "bash", "-c", bash,
             "_",                              # $0 placeholder
             str( delay ),                    # $1
             tmux_session,                    # $2
             text,                            # $3  (verbatim "/clear" — NOT wrapped)
             fire_token_path,                 # $4  (the one-shot, rm'd at the fire point)
             wake_text,                       # $5  (the rehydrate prompt — typed -l)
             bridge_path,                     # $6  (readiness oracle: mtime must change)
             str( ready_timeout_polls ),      # $7  (bounded poll count)
             str( poll_interval_seconds ),    # $8  (seconds between polls)
             keys_sent_path or "" ]           # $9  (send stamp; mtime IS the timestamp)


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


def _default_resolve_bridge_path( session_id ):   # pragma: no cover - live bridge-path read
    """
    Ensures: returns the seat's bridge file path (str) for `session_id`, or None. The
    path is `cc-{pid}.json` and the pid SURVIVES /clear, so the same path's mtime is
    what SessionStart bumps on rehydrate — the wake readiness oracle keys on it.
    Resolved by EXACT full-id match (exact=True), the SAME guard the tmux resolver
    uses: an 8-char-prefix collision would poll another live seat's bridge and type
    the wake into the un-cleared pane (row 275cb0b9).
    """
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_path_by_id
    p = find_session_path_by_id( session_id, exact=True )
    return str( p ) if p else None


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
    wake_nonce           = None,
    ready_timeout_polls  = DEFAULT_READY_TIMEOUT_POLLS,
    poll_interval_seconds = DEFAULT_POLL_INTERVAL_SECONDS,
    base_dir             = None,
    now                  = None,
    resolve_tmux_fn      = None,
    resolve_bridge_path_fn = None,
    ask_fn               = None,
    schedule_fn          = None,
    read_text_fn         = None,
    write_json_fn        = None,
):
    """
    Run the full self-re-spin decision + (on a go) schedule the detached /clear.

    ORDER (each guard is a hard gate; a failure returns without scheduling):
      1. resolve the seat's tmux session          — no session ⇒ aborted
      2. prove OVER-BUDGET grounds to clear        — status != "over_budget" ⇒ aborted
         (row 275cb0b9, John's ruling 2: the ONLY justification for an irreversible
         clear is a real over_budget reading. A failed pressure fetch degrades to
         "unknown"; forging or defaulting it turns a visible unknown into an invisible
         lie, and a non-over_budget marker can NEVER be classified RETURNED anyway.)
      3. verify the memento (nonce + freshness)    — fail ⇒ aborted (clear into nothing averted)
      4. fire the confirmation ask, always         — real "no"/"neither" ⇒ declined
      5. write the persistent OBSERVER marker + read it back for durability
         AND write the one-shot FIRE token         — read-back fail ⇒ aborted
      6. schedule the guarded, fire-point-consuming detached /clear (+ the wake that
         rides the SAME chain once the rehydrate bridge write proves the reset)

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
    resolve_bridge_path_fn = resolve_bridge_path_fn if resolve_bridge_path_fn is not None else _default_resolve_bridge_path
    # The seam stays ZERO-ARG — sixteen injected doubles are `lambda: "yes"`, and
    # widening the seam to carry the persona would break every one of them. The
    # persona rides in on a closure instead, so only the default path changes.
    ask_fn          = ask_fn          if ask_fn          is not None else ( lambda: _default_ask( persona ) )
    schedule_fn     = schedule_fn     if schedule_fn     is not None else _default_schedule
    read_text_fn    = read_text_fn    if read_text_fn    is not None else _default_read_text
    write_json_fn   = write_json_fn   if write_json_fn   is not None else _write_json_atomic

    # 1. resolve tmux session
    tmux_session = resolve_tmux_fn( session_id )
    if not tmux_session:
        return SelfRespinResult( status="aborted", reason="no tmux session in the bridge for this seat" )

    # 2. prove over-budget grounds to clear (ruling 2) — a fetch failure reads as
    # "unknown"; without a REAL over_budget reading the irreversible clear has no
    # justification, so abort rather than fire (and rather than record a marker the
    # RETURNED oracle could never satisfy).
    if pre_clear_status != "over_budget":
        return SelfRespinResult(
            status="aborted",
            reason=f"pre-clear status is {pre_clear_status!r}, not a proven 'over_budget' reading — no grounds to clear",
        )

    # 3. memento verify — BEFORE the ask (no point asking to clear into nothing)
    ok, reason = verify_memento_content(
        read_text_fn( memento_path ), memento_nonce, now, cycle_window_seconds=cycle_window_seconds
    )
    if not ok:
        return SelfRespinResult( status="aborted", reason=f"memento verify failed: {reason}" )

    # 4. confirmation ask — ALWAYS runs on this path; no skip kwarg exists
    proceed, gate_reason = gate_proceed( ask_fn() )
    if not proceed:
        return SelfRespinResult( status="declined", reason=gate_reason )

    # 5. resolve the wake BEFORE the marker so the marker records the wake_nonce the
    # seat must echo. The wake rides the SAME chain (ruling 3) behind the bridge-mtime
    # readiness gate; if the bridge can't be resolved we fall back to a plain clear
    # (still a valid re-spin — the seat is left for the observer to wake/alarm). The
    # wake TEXT (not the injector) carries the proof instruction: proof is CONSUMER-side.
    base            = base_dir if base_dir is not None else _resolve_base_dir()
    bridge_path     = resolve_bridge_path_fn( session_id ) if wake_nonce else None
    do_wake         = bool( wake_nonce and bridge_path )
    wake_proof_path = os.path.join( base, f"{_WAKE_PROOF_PREFIX}{session_id}.marker" ) if do_wake else None
    # A stale proof from a PRIOR cycle must not pre-satisfy this cycle's oracle; remove
    # it so only the seat's THIS-cycle proof (mtime >= this fired_at) can confirm RETURNED.
    if wake_proof_path:
        _best_effort_remove( wake_proof_path )
    wake_text = build_wake_text( memento_path, wake_nonce, wake_proof_path ) if do_wake else None

    # persistent observer marker (durability read-back) + one-shot fire token
    marker = build_marker_dict(
        session_id=session_id, persona=persona, tmux_session=tmux_session,
        fired_at=now, delay_seconds=delay_seconds,
        pre_clear_status=pre_clear_status, pre_clear_pct=pre_clear_pct,
        memento_path=memento_path, memento_verified=True,
        wake_nonce=wake_nonce if do_wake else None,   # only require a proof when we actually wake
        **( { "grace_seconds": grace_seconds } if grace_seconds is not None else {} ),
    )
    marker_path     = os.path.join( base, f"{_MARKER_PREFIX}{session_id}.json" )
    fire_token_path = os.path.join( base, f"{FIRE_TOKEN_PREFIX}{session_id}.token" )
    # The send stamp the fire point creates (row 855e4dd0). A stamp left over from a
    # PRIOR cycle would anchor this cycle's window on a send that already happened —
    # a deadline in the past — so it is cleared here, exactly as the wake proof is.
    keys_sent_path  = os.path.join( base, f"{KEYS_SENT_PREFIX}{session_id}.marker" )
    _best_effort_remove( keys_sent_path )

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

    # 6. schedule the guarded, fire-point-consuming detached /clear (+ the readiness-
    # gated wake built above).
    schedule_fn( build_guarded_clear_argv(
        tmux_session, fire_token_path, delay_seconds,
        wake_text             = wake_text,
        bridge_path           = bridge_path,
        keys_sent_path        = keys_sent_path,
        ready_timeout_polls   = ready_timeout_polls,
        poll_interval_seconds = poll_interval_seconds,
    ) )

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
    wake_nonce_fn        = None,
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
    wake_nonce = ( wake_nonce_fn or ( lambda: str( uuid.uuid4() ) ) )()   # mint the proof nonce THIS cycle
    return perform_fn(
        session_id,
        persona              = persona,
        memento_path         = memento_path,
        memento_nonce        = memento_nonce,
        pre_clear_status     = pre_clear_status,
        pre_clear_pct        = pre_clear_pct,
        delay_seconds        = delay_seconds,
        cycle_window_seconds = cycle_window_seconds,
        wake_nonce           = wake_nonce,   # the seat must echo this in its wake proof (GAP 1 + consumer proof)
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


def parse_own_pressure( section, persona ):
    """
    Extract ( status, consumption_pct_of_window ) for `persona` from a
    context-pressure section dict — PURE, so both arms are unit-covered (this is
    the logic that held a wrong default for a day under a pragma; R1 lifts it out).

    Requires:
        - section is the context-pressure section ({ "personas": { name: record } })
          or anything defensively; persona is the seat's persona name

    Ensures:
        - a present persona record carrying a `status` ⇒ ( status, pct )
        - an absent persona, a missing/blank `status`, a non-dict `personas`, or a
          non-dict `section` ⇒ ( "unknown", None ) — a missed reading is recorded
          as unknown, NEVER a manufactured "over_budget" (Krishna condition #3). A
          forged status would be a CLAIM that a reading happened; unknown is honest.
        - never raises
    """
    personas = section.get( "personas" ) if isinstance( section, dict ) else None
    record   = ( personas.get( persona ) if isinstance( personas, dict ) else None ) or {}
    status   = record.get( "status" ) or "unknown"
    return status, record.get( "consumption_pct_of_window" )


def _live_own_pressure( persona ):   # pragma: no cover - live :8001 httpx fetch ONLY; parse covered by parse_own_pressure
    """
    Read THIS persona's own context-pressure record for the pre-clear stamp.

    Only the live httpx fetch (+ its failure fallback to {}) lives here under the
    pragma; the parse/default logic is `parse_own_pressure` (unit-covered). A fetch
    failure yields {} ⇒ parse returns ( "unknown", None ), never a forged status.
    """
    try:
        from cosa.agents.heartbeat_arbiter.self_respin_observer import _fetch_live_pressure
        section = _fetch_live_pressure() or {}
    except Exception:
        section = {}
    return parse_own_pressure( section, persona )


UNNAMED_SEAT = "This seat"


def confirmation_text( persona ):
    """
    The words the human hears when a seat asks to re-spin itself — THIRD PERSON,
    naming the persona.

    ⚠️ WHY NOT SECOND PERSON. This ask lands on a SHARED voice surface that several
    sessions speak into. "You are at your context ceiling" reads as if the HUMAN is
    at a ceiling, and in chorus mode it does not say which of the running seats is
    asking — so the one question the human must answer ("who am I clearing?") is the
    one the wording withholds. Naming the persona answers it in the first three words.

    Pronouns: they/them. A persona name does not tell us anyone's pronouns, and this
    string is read aloud.

    Requires:
        - persona is the seat's persona name, or None/blank/"unknown" when unresolved

    Ensures:
        - returns ( question, abstract ), both naming the persona
        - degrades to UNNAMED_SEAT rather than saying "unknown is at their ceiling",
          which reads worse than not naming anyone
        - the question is one short line; the detail lives in the abstract

    Raises:
        - nothing
    """
    name = ( persona or "" ).strip()
    if not name or name.lower() == "unknown": name = UNNAMED_SEAT

    question = f"{name} is at their context ceiling. Re-spin {name} now?"
    abstract = (
        f"Self-re-spin for {name}: {name} will write their memento, verify it on disk, and type "
        f"/clear into their own pane, rehydrating as the same seat at low context. "
        f"Defaults to YES if you are away."
    )
    return question, abstract


def confirmation_kwargs( persona ):
    """
    EVERY argument the confirmation ask is fired with — pure, so all of it is pinnable.

    ⚠️ WHY THIS IS SEPARATE FROM `_default_ask`. That function is
    `# pragma: no cover`, because it is a live MCP boundary. Anything left inside it
    is, by construction, the part of this feature no test can see — and three of
    these values are behaviour, not decoration:

      · `default="yes"` — the OFFLINE SAFETY NET. A seat at its ceiling with the
        human away must still re-spin; flipping this to "no" would strand it silently.
      · `human_only=True` — LOAD-BEARING (row 804afce6). The auto-answer proxy must
        NOT veto a manager's own re-spin; only a real human "no", or the offline
        default-yes, decides. Drop this and a proxy can quietly block every re-spin
        in the fleet.
      · `timeout_seconds=120` — how long "away" takes to mean away.

    None of the values change here; they are lifted verbatim so they can be pinned.

    Requires:
        - persona is the seat's persona name, or None/blank/"unknown"

    Ensures:
        - returns the complete kwargs dict for `ask_yes_no.fn`
        - question and abstract come from `confirmation_text`, so the wording has
          exactly one definition

    Raises:
        - nothing
    """
    question, abstract = confirmation_text( persona )
    return {
        "question"        : question,
        "default"         : "yes",
        "timeout_seconds" : 120,
        "priority"        : "high",
        "abstract"        : abstract,
        "human_only"      : True,
    }


def _default_ask( persona ):   # pragma: no cover - live MCP ask boundary (tests inject ask_fn)
    """
    Fire the confirmation ask on the human surface and return the raw ask_yes_no
    string. Imported lazily so this module never pulls the MCP server in at import
    time. Everything decidable — the wording AND every argument — comes from the
    pure functions above, so this boundary carries no untested behaviour of its own.
    """
    from lupin_mcp.cosa_voice_mcp import ask_yes_no, DEFAULT_USED_MARKER as _M   # noqa: F401
    return ask_yes_no.fn( **confirmation_kwargs( persona ) )


# The observer's marker + wake-proof + send-stamp names — imported by name so the two
# files agree on the ONE shape each: the marker filename (MARKER_PREFIX), the wake-proof
# artifact filename (WAKE_PROOF_PREFIX), the proof's nonce line (WAKE_PROOF_NONCE_LINE)
# the seat echoes and the observer reads back, and the send-stamp filename
# (KEYS_SENT_PREFIX) this injector creates and the observer times its window from.
from cosa.agents.heartbeat_arbiter.self_respin_observer import (
    MARKER_PREFIX as _MARKER_PREFIX,
    WAKE_PROOF_PREFIX as _WAKE_PROOF_PREFIX,
    WAKE_PROOF_NONCE_LINE as _WAKE_PROOF_NONCE_LINE,
    DISPUTE_PREFIX as _DISPUTE_PREFIX,
    KEYS_SENT_PREFIX,
)
