"""
Fleet context-pressure assessment — pure-logic leaf.

Reads each Claude Code worker's transcript JSONL out-of-band and estimates how
full its context window is, so the fleet can WARN/CRITICAL on a worker *before*
it silently autocompacts mid-task.

Design provenance + the expert review that shaped every number here:
    src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.08-context-pressure-revised-plan.md

PURITY GUARDRAIL (Tiberius's architectural call): this module is a pure leaf in
`heartbeat_arbiter` (the shared engine both arbiter hosts import from). It imports
stdlib only on the hot path. `session_bridge` and `ConfigurationManager` are
imported LAZILY, inside the fleet helper only — never at module scope — so the
leaf never reaches up into any host / cosa.rest / HTTP layer.

The pressure number (per expert review, Decision 2 ruled 2026-06-08):

    last_prompt_size      = input + cache_creation + cache_read           # the auditable A1 sum
    pending_input_estimate = Σ ceil( len(content)/4 )  for msgs after the last assistant turn
    next_prompt_estimate  = last_prompt_size + last_output + pending_input_estimate   # thresholds ride THIS

Thresholds ride `next_prompt_estimate / effective_ceiling`, where
    effective_ceiling = window_size - autocompact_reserve - max_response_tokens
and `window_size` is read from the bridge (pinned at spawn), never inferred.
"""

import json
import math
import os
import time

from dataclasses import dataclass, field
from enum        import Enum


# ---------------------------------------------------------------------------
# Defaults (the fleet helper / CLI override these from lupin-app.ini)
# ---------------------------------------------------------------------------
DEFAULT_WINDOW_TOKENS       = 1_000_000     # fleet [1m] fallback ONLY; bridge window_size wins
# CALIBRATED 2026-06-08 against a live /context (María's session: 218.3k used / 1M = 22%, used+free
# ≈ a flat 1M). Finding: /context's percentage is measured against the RAW window, NOT an effective
# ceiling minus an autocompact reserve. This REFUTES the pre-build A4 assumption. So the reserve/
# max-response carve-outs are 0 in the denominator (pct = next_prompt_estimate / raw window → matches
# what an operator sees in /context). They remain configurable for a FUTURE "autocompact-imminent"
# overlay flag, but they do NOT reduce the pct ceiling. CRITICAL 85% of raw still sits safely below
# where autocompact fires near the top of the window.
DEFAULT_RESERVE_TOKENS      = 0             # overlay-reserved; 0 in the pct denominator (see calibration note)
DEFAULT_MAX_RESPONSE_TOKENS = 0             # overlay-reserved; 0 in the pct denominator (see calibration note)
DEFAULT_WARN_PCT            = 70.0
DEFAULT_CRITICAL_PCT        = 85.0
DEFAULT_IDLE_MTIME_SECONDS  = 1_800         # ACTIVE vs IDLE boundary
DEFAULT_TAIL_BYTES          = 512 * 1024    # bounded tail read; generous enough for last turn + pending


class PressureState( str, Enum ):
    OK       = "OK"
    WARN     = "WARN"
    CRITICAL = "CRITICAL"
    UNKNOWN  = "UNKNOWN"


class Liveness( str, Enum ):
    ACTIVE = "ACTIVE"     # process alive + mtime fresh  → compute pressure
    IDLE   = "IDLE"       # process alive + mtime stale  → skip pressure, flag age
    DEAD   = "DEAD"       # process gone                 → sweep bridge


@dataclass
class Usage:
    """The token partition of one assistant turn's prompt (+ its output)."""
    input          : int
    cache_creation : int
    cache_read     : int
    output         : int

    @property
    def last_prompt_size( self ):
        """
        The authoritative A1 sum — the prompt actually sent that turn.

        Ensures:
            - returns input + cache_creation + cache_read (output EXCLUDED)
        """
        return self.input + self.cache_creation + self.cache_read


@dataclass
class ContextPressure:
    """Per-worker pressure assessment (the §2 return shape)."""
    last_prompt_size       : int
    last_output_tokens     : int
    pending_input_estimate : int
    next_prompt_estimate   : int
    window_size            : int
    effective_ceiling      : int
    pct                    : float
    state                  : PressureState
    model                  : "str | None"     = None
    last_turn_ts           : "str | None"     = None
    parse_failures         : int              = 0


@dataclass
class WorkerContextPressure:
    """A fleet member: its identity + liveness + pressure + recommendation."""
    session_id   : str
    persona      : str
    tmux_session : "str | None"
    liveness     : Liveness
    pressure     : "ContextPressure | None"
    last_turn_age: "float | None" = None
    recommendation: str           = ""


# ---------------------------------------------------------------------------
# Bounded tail reader — both readers below operate on the same tail window
# ---------------------------------------------------------------------------
def _read_tail_lines( transcript_path, max_bytes=DEFAULT_TAIL_BYTES ):
    """
    Read up to `max_bytes` from the END of the transcript and return whole lines.

    Requires:
        - transcript_path points at a readable file

    Ensures:
        - returns a list of non-empty line strings from the tail window
        - drops a leading partial line when the window does not start at byte 0
        - returns [] if the file is missing/empty or unreadable
    """
    try:
        size = os.path.getsize( transcript_path )
    except OSError:
        return []

    if size == 0:
        return []

    start = max( 0, size - max_bytes )
    try:
        with open( transcript_path, "rb" ) as f:
            f.seek( start )
            chunk = f.read()
    except OSError:
        return []

    lines = chunk.decode( "utf-8", errors="replace" ).split( "\n" )
    if start > 0 and lines:
        lines = lines[ 1: ]                       # first line is likely partial — drop it
    return [ ln for ln in lines if ln.strip() ]


def _coerce_cache_creation( usage ):
    """
    Read cache-creation tokens, hardened against the nested-dict format drift.

    The live `usage` carries BOTH a flat `cache_creation_input_tokens` and a
    nested `cache_creation` breakdown (ephemeral_5m/1h). The flat field is the
    sum of the nested one today; if it is ever dropped, fall back to the nested
    values rather than crashing on None.

    Ensures:
        - returns an int (0 when neither form is present)
    """
    flat = usage.get( "cache_creation_input_tokens" )
    if isinstance( flat, int ):
        return flat
    nested = usage.get( "cache_creation" )
    if isinstance( nested, dict ):
        return sum( v for v in nested.values() if isinstance( v, int ) )
    return 0


def read_last_usage( transcript_path, max_bytes=DEFAULT_TAIL_BYTES ):
    """
    Tail-read the newest assistant turn's usage.

    NOTE: `server_tool_use` tokens are DELIBERATELY ignored — they are consumed
    server-side (web_search/web_fetch) and are NOT in the context window.

    Requires:
        - transcript_path is a path-like to a Claude Code transcript JSONL

    Ensures:
        - returns ( Usage | None, parse_failures: int, last_turn_ts: str | None )
        - Usage is the newest assistant message carrying a usage dict
        - returns None for the Usage on a cold worker (no assistant turn yet)
        - never raises; malformed JSONL lines are counted, not propagated
    """
    lines          = _read_tail_lines( transcript_path, max_bytes )
    parse_failures = 0
    last_usage     = None
    last_ts        = None

    for line in lines:
        try:
            obj = json.loads( line )
        except ( ValueError, TypeError ):
            parse_failures += 1
            continue
        message = obj.get( "message" ) if isinstance( obj, dict ) else None
        if not isinstance( message, dict ):
            continue
        if message.get( "role" ) != "assistant":
            continue
        usage = message.get( "usage" )
        if not isinstance( usage, dict ):
            continue
        last_usage = Usage(
            input          = usage.get( "input_tokens", 0 ) or 0,
            cache_creation = _coerce_cache_creation( usage ),
            cache_read     = usage.get( "cache_read_input_tokens", 0 ) or 0,
            output         = usage.get( "output_tokens", 0 ) or 0,
        )
        ts_candidate = obj.get( "timestamp" )
        if ts_candidate is not None:
            last_ts = ts_candidate

    return last_usage, parse_failures, last_ts


def estimate_pending_input( transcript_path, max_bytes=DEFAULT_TAIL_BYTES ):
    """
    Estimate unread tokens accumulated AFTER the last assistant turn.

    Between assistant turns, tool_results (multi-KB stdout/file views) and user
    messages pile up that the last-turn usage never sees. A worker can read 60%
    while sitting on 40k of queued output that lands the moment it speaks again.
    We sum a conservative `ceil(len(content)/4)` Latin-char heuristic (Decision 4,
    zero-dep, pure leaf).

    Ensures:
        - returns ( pending_tokens: int, parse_failures: int )
        - 0 when there are no messages after the last assistant turn
        - never raises
    """
    lines          = _read_tail_lines( transcript_path, max_bytes )
    parse_failures = 0
    parsed         = []
    last_assistant = -1

    for idx, line in enumerate( lines ):
        try:
            obj = json.loads( line )
        except ( ValueError, TypeError ):
            parse_failures += 1
            parsed.append( None )
            continue
        parsed.append( obj )
        message = obj.get( "message" ) if isinstance( obj, dict ) else None
        if isinstance( message, dict ) and message.get( "role" ) == "assistant" \
                and isinstance( message.get( "usage" ), dict ):
            last_assistant = idx

    pending = 0
    for obj in parsed[ last_assistant + 1: ]:
        if obj is None:
            continue
        pending += _estimate_message_tokens( obj )

    return pending, parse_failures


def _estimate_message_tokens( obj ):
    """
    Conservative token estimate for one transcript message (ceil(len/4)).

    Ensures:
        - returns ceil( len(serialized content) / 4 ), >= 0
        - strings counted directly; structured content serialized first
    """
    if not isinstance( obj, dict ):
        return 0
    message = obj.get( "message" )
    content = message.get( "content" ) if isinstance( message, dict ) else obj.get( "content" )
    if content is None:
        return 0
    text = content if isinstance( content, str ) else json.dumps( content, default=str )
    return math.ceil( len( text ) / 4 )


# ---------------------------------------------------------------------------
# Liveness (Decision: 3-state, kill -0 AND-gate)
# ---------------------------------------------------------------------------
def _pid_alive( pid ):
    """
    True iff a process with `pid` exists (the worker that produces next turns).

    Ensures:
        - returns False for None / non-int / dead pid
        - returns True when the pid exists (incl. EPERM = exists-but-not-ours)
    """
    if not isinstance( pid, int ):
        return False
    try:
        os.kill( pid, 0 )
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def assess_liveness( listener_pid, mtime, *, now, cc_pid=None, idle_mtime_seconds=DEFAULT_IDLE_MTIME_SECONDS ):
    """
    Three-state liveness: process-alive OR-gate, then mtime freshness.

    Process-alive is the OR of TWO pids — the listener pid AND the claude-CLI
    pid (`cc_pid`, pinned in the bridge at spawn). Either one passing `kill -0`
    proves the worker exists. The OR (vs the prior single-pid AND) protects the
    false-DEAD case, which is the worse error under the arbiter's bias-to-alive
    liveness (Decision #2, 2026-06-08): a session is DEAD only when NO recent
    signal exists, so we must not declare it dead while a pid still answers.

    Requires:
        - listener_pid is an int pid or None (None / non-int ⇒ not-alive)
        - cc_pid is an int pid or None (None / non-int ⇒ not-alive; falls back
          to listener_pid alone, e.g. a pre-rename bridge with no cc_pid field)
        - now is an epoch-seconds float; mtime is the bridge-file mtime

    Ensures:
        - DEAD   when BOTH pids are gone/None (definitive phantom signal)
        - ACTIVE when EITHER pid is alive AND mtime within idle_mtime_seconds
        - IDLE   when EITHER pid is alive but mtime stale (skip pressure, age)
        - a PermissionError on either pid counts as alive (exists, not ours)
        - pure (stdlib only); never raises
    """
    if not ( _pid_alive( listener_pid ) or _pid_alive( cc_pid ) ):
        return Liveness.DEAD
    if ( now - mtime ) <= idle_mtime_seconds:
        return Liveness.ACTIVE
    return Liveness.IDLE


# ---------------------------------------------------------------------------
# Core assessment
# ---------------------------------------------------------------------------
def assess_context_pressure(
    transcript_path,
    *,
    window_size   = DEFAULT_WINDOW_TOKENS,
    reserve       = DEFAULT_RESERVE_TOKENS,
    max_response  = DEFAULT_MAX_RESPONSE_TOKENS,
    warn_pct      = DEFAULT_WARN_PCT,
    critical_pct  = DEFAULT_CRITICAL_PCT,
    model         = None,
    max_bytes     = DEFAULT_TAIL_BYTES,
):
    """
    Assess one worker's context pressure from its transcript.

    Requires:
        - window_size, reserve, max_response are non-negative ints
        - 0 <= warn_pct <= critical_pct <= 100

    Ensures:
        - returns a ContextPressure
        - state == UNKNOWN (no crash) when the transcript has no assistant turn
        - pct rides next_prompt_estimate / effective_ceiling (Decision 2 + A4)
        - effective_ceiling is floored at 1 to avoid division by zero
    """
    usage, uf, last_ts = read_last_usage( transcript_path, max_bytes )
    pending, pf        = estimate_pending_input( transcript_path, max_bytes )
    parse_failures     = uf + pf
    effective_ceiling  = max( 1, window_size - reserve - max_response )

    if usage is None:
        return ContextPressure(
            last_prompt_size       = 0,
            last_output_tokens     = 0,
            pending_input_estimate = pending,
            next_prompt_estimate   = 0,
            window_size            = window_size,
            effective_ceiling      = effective_ceiling,
            pct                    = 0.0,
            state                  = PressureState.UNKNOWN,
            model                  = model,
            last_turn_ts           = last_ts,
            parse_failures         = parse_failures,
        )

    last_prompt_size = usage.last_prompt_size
    next_prompt      = last_prompt_size + usage.output + pending
    pct              = 100.0 * next_prompt / effective_ceiling

    if pct >= critical_pct:
        state = PressureState.CRITICAL
    elif pct >= warn_pct:
        state = PressureState.WARN
    else:
        state = PressureState.OK

    return ContextPressure(
        last_prompt_size       = last_prompt_size,
        last_output_tokens     = usage.output,
        pending_input_estimate = pending,
        next_prompt_estimate   = next_prompt,
        window_size            = window_size,
        effective_ceiling      = effective_ceiling,
        pct                    = pct,
        state                  = state,
        model                  = model,
        last_turn_ts           = last_ts,
        parse_failures         = parse_failures,
    )


def recommend( liveness, state ):
    """
    Map (liveness, pressure state) → a one-line manager recommendation.

    Ensures:
        - DEAD → sweep; IDLE → defer; CRITICAL → harvest; WARN → compact soon; else none
    """
    if liveness == Liveness.DEAD:
        return "sweep dead bridge"
    if liveness == Liveness.IDLE:
        return "idle — skip (stale transcript)"
    if state == PressureState.CRITICAL:
        return "harvest+respawn with memento (or compact now if mid-turn)"
    if state == PressureState.WARN:
        return "compact soon"
    if state == PressureState.UNKNOWN:
        return "unknown — no assistant turn yet"
    return ""


# ---------------------------------------------------------------------------
# Fleet helper — the ONLY place that reaches outside stdlib (lazy imports)
# ---------------------------------------------------------------------------
def assess_fleet_context_pressure(
    *,
    reserve            = DEFAULT_RESERVE_TOKENS,
    max_response       = DEFAULT_MAX_RESPONSE_TOKENS,
    warn_pct           = DEFAULT_WARN_PCT,
    critical_pct       = DEFAULT_CRITICAL_PCT,
    idle_mtime_seconds = DEFAULT_IDLE_MTIME_SECONDS,
    default_window     = DEFAULT_WINDOW_TOKENS,
    stale_threshold_seconds = 43_200,
):
    """
    Assess every active fleet worker.

    Lazily imports `session_bridge` to enumerate live persona sessions, reads each
    bridge's transcript_path / listener_pid / tmux_session / window_size, gates on
    liveness, and assesses pressure for ACTIVE workers.

    Ensures:
        - returns a list[ WorkerContextPressure ]
        - window_size is read from the bridge (pinned at spawn); falls back to
          default_window when the key is absent
        - DEAD/IDLE workers get pressure=None + an explanatory recommendation
        - never raises on a single bad bridge (skips it)
    """
    from lupin_cli.claude_code.hooks.lib import session_bridge   # lazy: keep the leaf pure

    now     = time.time()
    results = []

    for bridge_path, session_id, persona in session_bridge.find_active_voice_persona_sessions(
            stale_threshold_seconds=stale_threshold_seconds ):
        try:
            with open( bridge_path, "r" ) as f:
                bridge = json.load( f )
            mtime = os.path.getmtime( bridge_path )
        except ( OSError, ValueError ):
            continue

        persona_name = persona.get( "name", "unknown" ) if isinstance( persona, dict ) else str( persona )
        tmux_session = bridge.get( "tmux_session" )
        listener_pid = bridge.get( "listener_pid" )
        cc_pid       = bridge.get( "cc_pid" )                 # claude-CLI pid (None on a pre-rename bridge)
        transcript   = bridge.get( "transcript_path" )
        window_size  = bridge.get( "window_size", default_window )

        liveness = assess_liveness(
            listener_pid, mtime, now=now, cc_pid=cc_pid, idle_mtime_seconds=idle_mtime_seconds
        )

        pressure = None
        if liveness == Liveness.ACTIVE and transcript:
            pressure = assess_context_pressure(
                transcript,
                window_size  = window_size,
                reserve      = reserve,
                max_response = max_response,
                warn_pct     = warn_pct,
                critical_pct = critical_pct,
                model        = bridge.get( "model" ),
            )

        results.append( WorkerContextPressure(
            session_id    = session_id,
            persona       = persona_name,
            tmux_session  = tmux_session,
            liveness      = liveness,
            pressure      = pressure,
            last_turn_age = ( now - mtime ),
            recommendation= recommend( liveness, pressure.state if pressure else PressureState.UNKNOWN ),
        ) )

    return results


def render_fleet_table( workers ):
    """
    Render the on-the-fly fleet pressure table (persona · pct · state · rec).

    Ensures:
        - returns a multi-line string; one header + one row per worker
    """
    header = f"{'PERSONA':<12} {'LIVE':<7} {'PCT':>6}  {'STATE':<9} {'PENDING':>8}  RECOMMENDATION"
    rows   = [ header, "-" * len( header ) ]
    for w in workers:
        if w.pressure is not None:
            pct     = f"{w.pressure.pct:5.1f}%"
            state   = w.pressure.state.value
            pending = f"{w.pressure.pending_input_estimate:>8,}"
        else:
            pct, state, pending = "   —  ", w.liveness.value, "       —"
        rows.append( f"{w.persona:<12} {w.liveness.value:<7} {pct:>6}  {state:<9} {pending:>8}  {w.recommendation}" )
    return "\n".join( rows )


def quick_smoke_test():
    """Print the live fleet pressure table (read-only, :7999-safe)."""
    print( "Assessing live fleet context pressure...\n" )
    workers = assess_fleet_context_pressure()
    if not workers:
        print( "  (no active persona sessions found)" )
        return
    print( render_fleet_table( workers ) )


if __name__ == "__main__":   # pragma: no cover - CLI entry point, exercised via quick_smoke_test() in tests
    quick_smoke_test()
