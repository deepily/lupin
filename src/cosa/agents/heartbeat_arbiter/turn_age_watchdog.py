"""
Turn-age watchdog — the generalized held-turn DETECTOR (wedge fix f1a21917
lever (ii), design §3).

A fire-and-forget cosa-voice notify() held session 25c7441c's CC turn 54m47s
(tool_use 01:52:53Z → tool_result 02:47:39Z, released only by process death).
While the turn was open the Stop phase could not run, so tmux-injected messages
sat undrained and the wedge forced a manager re-spin. Lever (i-a) (MCP_TOOL_TIMEOUT
in the fleet spawn env) PREVENTS the unbounded hang; this watchdog is the
arbiter-side DETECTION complement that would have surfaced the wedge ~10 min in
instead of 55 min + a re-spin — and it catches EVERY variant of the held-turn
class (in-turn tool hang, stop-phase hold), not just notify.

**Signature of a held turn** (interim-mitigation §6, made continuous): a live CC
session whose transcript's LAST `tool_use` has no matching `tool_result` for longer
than the threshold, while its tmux pane shows no active stream. → ONE operator
advisory (detection-only, NO auto-kill; advisory tier, never a poke → LOW blast).

**Flood-guard (fresh lesson from re-announce flood e1bbe011).** The advisory is
ONE-SHOT per unique `(session_id, tool_use_id)` dangling turn: a still-dangling
turn across sweeps fires NOTHING, and the `_advised` marker set is intersect-cleared
against the live dangling set each pass (mirrors the arbiter's `_escalated &= live`
idiom) so a resolved wedge drops its marker and only a genuinely NEW dangling
tool_use can advise again. No fresh forensic row per sweep.

**Disabled by default.** Gated on `arbiter turn age watchdog enabled` (default
False, [Lupin: Baseline]) — a defense-in-depth rollout gate sibling to
`follow through escalation enabled`. With the flag off, `sweep_once` is a no-op
(no transcript/pane IO) and `start()` refuses to spawn the daemon. Activation
(and the :8001 arbiter restart it needs) is manager/Rick territory.

The session lister, transcript reader, pane-activity oracle, advisory sink, and
clock are ALL injectable, so the detection logic + flood-guard are 100% unit-tested
with fakes; only the literal external IO readers (the `_default_*` boundaries) are
pragma'd — the same convention as the arbiter's other `_default_*` seams.

Canonical design: src/rnd/v0.1.9/2026.07.03-notify-turn-hold-fix-design.md §3.
"""

import json
import threading
from datetime import datetime, timezone

import cosa.utils.util as du


ADVISORY_ACTOR = "turn-age-watchdog"   # the system actor naming the advisory source


# ── pure transcript analysis (no IO — 100% unit-testable) ────────────────────

def _iter_content_blocks( entry ):
    """
    Yield the content blocks of a transcript entry, tolerant of shape.

    Requires:
        - entry is a parsed transcript object (dict) or anything else

    Ensures:
        - yields each dict block under entry["message"]["content"] when that is a
          list; yields nothing for any other shape (never raises)
    """
    if not isinstance( entry, dict ):
        return
    message = entry.get( "message" )
    if not isinstance( message, dict ):
        return
    content = message.get( "content" )
    if not isinstance( content, list ):
        return
    for block in content:
        if isinstance( block, dict ):
            yield block


def find_dangling_tool_use( entries ):
    """
    Find the LAST tool_use in a transcript that has no matching tool_result — the
    held-turn signature (interim-mitigation §6: "the last tool_use id with no
    tool_result").

    Requires:
        - entries is an iterable of parsed transcript objects in chronological
          (append) order

    Ensures:
        - returns ( tool_use_id, timestamp ) of the FINAL tool_use block when its
          id never appears as a tool_result's tool_use_id anywhere in the
          transcript (the turn is still waiting on it)
        - returns None when there is no tool_use at all, or when the final tool_use
          DID receive a result (the turn proceeded)
        - keying on the FINAL tool_use (not any-dangling) avoids false positives:
          a normal transcript never starts a later tool_use until the prior one
          returns, so an un-resulted EARLIER tool_use with a resulted later one is
          an artifact, not a held turn. (Conservative bias: in a rare parallel-call
          final message where a sibling is held but the last-listed block resolved,
          this under-reports rather than floods — the safer error for an advisory.)
        - never raises on malformed entries/blocks (skipped)

    Returns:
        tuple( str, Optional[str] ) or None
    """
    last_tool_use = None                               # ( id, timestamp )
    result_ids    = set()
    for entry in entries:
        ts = entry.get( "timestamp" ) if isinstance( entry, dict ) else None
        for block in _iter_content_blocks( entry ):
            btype = block.get( "type" )
            if btype == "tool_use":
                tid = block.get( "id" )
                if tid:
                    last_tool_use = ( tid, ts )
            elif btype == "tool_result":
                rid = block.get( "tool_use_id" )
                if rid:
                    result_ids.add( rid )
    if last_tool_use is None:
        return None
    tool_use_id, ts = last_tool_use
    if tool_use_id in result_ids:
        return None
    return ( tool_use_id, ts )


def age_seconds( timestamp, now ):
    """
    Age (seconds) of an ISO-8601 transcript timestamp relative to `now`.

    Requires:
        - timestamp is an ISO-8601 string (trailing "Z" or an explicit offset), or
          None
        - now is a tz-aware datetime

    Ensures:
        - returns ( now - parsed ).total_seconds() for a parseable timestamp; a
          naive parse is coerced to UTC defensively
        - returns None for a None / non-string / unparseable timestamp (the caller
          treats un-ageable turns as non-candidates — never a false advisory)
        - never raises

    Returns:
        float or None
    """
    if not isinstance( timestamp, str ) or not timestamp:
        return None
    text = timestamp.strip()
    if text.endswith( "Z" ):
        text = text[ :-1 ] + "+00:00"
    try:
        parsed = datetime.fromisoformat( text )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace( tzinfo=timezone.utc )
    return ( now - parsed ).total_seconds()


class TurnAgeWatchdog:
    """
    Standalone held-turn detector daemon. Inert unless `arbiter turn age watchdog
    enabled` is True. Mirrors the FollowThroughEscalationWatcher shape (INI-gate,
    sweep_once, one-shot markers, daemon lifecycle) but has NO dependency on the
    ArbiterConsumerJob — it reads transcripts + panes directly — so it runs as its
    own daemon rather than riding the job poll (zero arbiter_job.py coupling).
    """

    def __init__(
        self,
        config_mgr,
        *,
        session_lister_fn    = None,
        transcript_reader_fn = None,
        pane_active_fn       = None,
        advisory_fn          = None,
        now_fn               = None,
    ):
        """
        Initialize the turn-age watchdog.

        Requires:
            - config_mgr exposes .get( key, default=, return_type= )
            - session_lister_fn() -> iterable of dicts, each with keys session_id,
              persona, tmux_session, transcript_path (default: scan the live
              persona'd session bridges); injected for tests
            - transcript_reader_fn( transcript_path ) -> list of parsed transcript
              objects in chronological order (default: parse the JSONL file,
              swallow IO/parse errors to []); injected for tests
            - pane_active_fn( tmux_session ) -> bool answering "is this pane showing
              an active stream right now?" (default: capture the pane twice and
              compare — changed == active); injected for tests
            - advisory_fn( message ) -> None emits ONE operator advisory on the
              throttled outreach rail (default: a structured banner log); injected
              so production supplies the durable-commons hop and tests assert it
            - now_fn() -> tz-aware datetime (default: datetime.now(utc)); injected
              so tests pin the clock

        Ensures:
            - no thread is started at construction (call start() explicitly)
            - the one-shot `_advised` marker set starts empty
        """
        self._config_mgr           = config_mgr
        self._session_lister_fn    = session_lister_fn    if session_lister_fn    is not None else self._default_session_lister
        self._transcript_reader_fn = transcript_reader_fn if transcript_reader_fn is not None else self._default_transcript_reader
        self._pane_active_fn       = pane_active_fn       if pane_active_fn       is not None else self._default_pane_active
        self._advisory_fn          = advisory_fn          if advisory_fn          is not None else self._default_advisory_signal
        self._now_fn               = now_fn               if now_fn               is not None else ( lambda: datetime.now( timezone.utc ) )
        self._advised              = set()                # (session_id, tool_use_id) advised once — flood-guard one-shot
        self._stop_event           = threading.Event()
        self._thread               = None

    # -- config accessors -----------------------------------------------------

    def _enabled( self ) -> bool:
        return self._config_mgr.get( "arbiter turn age watchdog enabled", default=False, return_type="boolean" )

    def _threshold_seconds( self ) -> int:
        return self._config_mgr.get( "arbiter turn age watchdog threshold seconds", default=600, return_type="int" )

    def _tick_seconds( self ) -> int:
        # the daemon nap — the SAME live tick the :8001 fleet-arbiter loop polls on,
        # so a crossed threshold surfaces within one tick (no separate cadence knob).
        return self._config_mgr.get( "arbiter poll seconds", default=60, return_type="int" )

    # -- core (unit-testable, no thread) --------------------------------------

    def sweep_once( self ) -> dict:
        """
        Run one held-turn detection pass over the live CC sessions.

        Ensures:
            - flag OFF -> no IO at all; returns {enabled:False, advised:0, candidates:0}
            - flag ON  -> for each live session with a transcript:
                * find_dangling_tool_use over its transcript; skip if none
                * skip if the dangling tool_use's age <= threshold (or un-ageable)
                * a dangling+aged turn's (session, tool_use) key is recorded LIVE so
                  its one-shot marker persists while it stays dangling+aged
                * a pane that is actively streaming is SKIPPED (not yet a stuck turn;
                  no advisory, no candidate — it may advise later if the stream stops)
                * a dangling+aged+not-streaming turn is a held-turn candidate; it
                  fires ONE advisory_fn(...) and is marked advised UNLESS already
                  advised (one-shot per unique tool_use)
            - after the pass, `_advised` is intersected with the live dangling set so
              markers clear when a wedge resolves (its key leaves the live set) —
              one-shot-THEN-cleared, never a per-sweep re-fire
            - swallow-safe per session: a transcript-reader / pane blow-up on ONE
              session is demoted to a skip, never kills the sweep

        Returns:
            dict summary { "enabled": bool, "advised": int, "candidates": int }
        """
        if not self._enabled():
            return { "enabled": False, "advised": 0, "candidates": 0 }

        now       = self._now_fn()
        threshold = self._threshold_seconds()
        advised   = 0
        candidates = 0
        live      = set()                              # (session, tool_use) still dangling+aged this pass
        for session in self._session_lister_fn():
            try:
                sid          = session.get( "session_id" )
                transcript   = session.get( "transcript_path" )
                if not sid or not transcript:
                    continue
                entries = self._transcript_reader_fn( transcript )
                dangling = find_dangling_tool_use( entries )
                if dangling is None:
                    continue
                tool_use_id, ts = dangling
                age = age_seconds( ts, now )
                if age is None or age <= threshold:
                    continue
                key = ( sid, tool_use_id )
                live.add( key )                        # hold the marker while dangling+aged
                if self._pane_active_fn( session.get( "tmux_session" ) ):
                    continue                           # streaming -> not (yet) stuck; may advise if it later goes quiet
                candidates += 1
                if key in self._advised:
                    continue                           # one-shot — already advised this tool_use
                self._emit_advisory( session, tool_use_id, age, threshold )
                self._advised.add( key )
                advised += 1
            except Exception as e:                     # per-session swallow (observer invariant)
                du.print_banner( f"Turn-age watchdog skipped a session on error (continuing): {e!r}", prepend_nl=True )

        # flood-guard clear: a key no longer dangling+aged (wedge resolved) drops its
        # one-shot marker, so a genuinely NEW dangling tool_use can advise later.
        self._advised &= live
        return { "enabled": True, "advised": advised, "candidates": candidates }

    def _emit_advisory( self, session, tool_use_id, age, threshold ) -> None:
        """
        Compose + fire the ONE operator advisory for a detected held turn.

        Ensures:
            - builds a human-readable advisory naming the session/persona, the
              dangling tool_use, the observed age vs threshold (both in minutes),
              and that this is detection-only (no action taken)
            - delegates delivery to the injected advisory_fn (the throttled rail);
              never raises here (the sweep's per-session guard is the backstop)
        """
        persona   = session.get( "persona" ) or "unknown"
        sid       = session.get( "session_id" )
        age_min   = int( age // 60 )
        thr_min   = int( threshold // 60 )
        message = (
            f"TURN-AGE WATCHDOG — session {sid} (persona {persona}) has a HELD TURN: "
            f"its last tool_use ({tool_use_id}) has had no tool_result for ~{age_min}m "
            f"(threshold {thr_min}m) and its pane shows no active stream. Likely a wedge "
            f"(cf incident 25c7441c). Detection-only advisory — NO action taken; if a live "
            f"session is truly wedged, the runbook §4 mitigation is to kill that session's "
            f"cosa_voice_mcp.py child (the turn errors out and the queue drains)."
        )
        self._advisory_fn( message )

    # -- default IO boundaries (pragma'd — injected fakes exercise the logic) --

    def _default_session_lister( self ):   # pragma: no cover - live bridge-scan IO boundary
        """
        Default session lister: scan the live persona'd session bridges and project
        the fields the sweep needs. Skips buffer/listener bridges + dead PIDs. Never
        raises (a malformed bridge is skipped). Unit tests inject a fake; exercised
        at the :8001 integration tier like the arbiter's other `_default_*` readers.
        """
        from lupin_cli.claude_code.hooks.lib.session_bridge import (
            SESSION_DIR, _extract_pid_from_filename, _is_pid_alive,
        )
        results = [ ]
        if not SESSION_DIR.exists():
            return results
        for path in SESSION_DIR.glob( "cc-*.json" ):
            if "buffer" in path.name or "listener" in path.name:
                continue
            file_pid = _extract_pid_from_filename( path.name )
            if file_pid is not None and not _is_pid_alive( file_pid ):
                continue
            try:
                with open( path ) as f:
                    data = json.load( f )
            except ( json.JSONDecodeError, OSError ):
                continue
            if not isinstance( data, dict ):
                continue
            persona = ( data.get( "voice_persona" ) or { } ).get( "name" )
            results.append( {
                "session_id"      : data.get( "session_id" ) or data.get( "stable_session_id" ),
                "persona"         : persona,
                "tmux_session"    : data.get( "tmux_session" ),
                "transcript_path" : data.get( "transcript_path" ),
            } )
        return results

    def _default_transcript_reader( self, transcript_path ):   # pragma: no cover - transcript file IO boundary
        """
        Default transcript reader: parse a JSONL transcript into a list of objects,
        chronological order preserved. Swallows IO/parse errors to an empty list
        (an unreadable transcript is a non-candidate, never a false advisory).
        """
        entries = [ ]
        try:
            with open( transcript_path ) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append( json.loads( line ) )
                    except ValueError:
                        continue
        except OSError:
            return [ ]
        return entries

    def _default_pane_active( self, tmux_session ):   # pragma: no cover - tmux capture IO boundary
        """
        Default pane-activity oracle: capture the pane twice ~0.4s apart; a CHANGED
        capture == an active stream. A pane that can't be resolved/captured reads as
        NOT active (False) so the dangling-age governs — biased toward surfacing a
        genuinely stuck turn (advisory is low-blast). Never raises.
        """
        import subprocess
        import time
        if not tmux_session:
            return False
        def _cap():
            try:
                r = subprocess.run(
                    [ "tmux", "capture-pane", "-p", "-t", tmux_session ],
                    capture_output=True, text=True, timeout=5,
                )
                return r.stdout if r.returncode == 0 else None
            except Exception:
                return None
        first = _cap()
        if first is None:
            return False
        time.sleep( 0.4 )
        second = _cap()
        if second is None:
            return False
        return first != second

    def _default_advisory_signal( self, message ) -> None:
        """Default advisory sink: a structured banner (production injects the durable-commons rail)."""
        du.print_banner( f"[{ADVISORY_ACTOR}] {message}", prepend_nl=True )

    # -- daemon lifecycle -----------------------------------------------------

    def _loop( self ) -> None:
        """
        Daemon loop until stop(); Event.wait(timeout) so shutdown interrupts the nap
        immediately. Each sweep is exception-guarded so a transient IO error never
        kills the daemon. Naps the LIVE arbiter tick (sweeps every tick).
        """
        while not self._stop_event.is_set():
            try:
                self.sweep_once()
            except Exception as e:
                du.print_banner( f"Turn-age watchdog loop caught exception (continuing): {e!r}", prepend_nl=True )
            self._stop_event.wait( timeout=self._tick_seconds() )

    def start( self ) -> bool:
        """
        Spawn the daemon thread — ONLY if the flag is enabled and no thread is
        already running. Returns True if a thread was started, else False (the
        no-op rollout gate: a disabled watchdog never spawns).
        """
        if not self._enabled():
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread( target=self._loop, daemon=True, name="TurnAgeWatchdog" )
        self._thread.start()
        return True

    def stop( self, timeout: float = 5.0 ) -> None:
        """Signal the daemon to exit and join it (idempotent — safe if never started)."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join( timeout=timeout )
