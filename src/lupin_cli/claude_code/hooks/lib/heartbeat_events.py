#!/usr/bin/env python3
"""
Heartbeat Hook: poke-outcome event emitter ("emit now, consume later").

The Stop-hook decision path writes a fire-and-forget JSON Lines record per session for each meaningful heartbeat outcome.
The v2 fleet arbiter (deferred) is a pure consumer that globs the fleet dir, so it needs no hook retrofit.
An emit must never raise into or block the poke path: a failed emission leaves the poke proceeding unchanged.

Design: /mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md section 0.2 (canonical schema).
See: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md

Location is fleet-wide, a deliberate divergence from the hold artifact.
The consumer is the cross-fleet arbiter, so files live in one dir, `~/.claude/heartbeat-events/<session_id>.jsonl`.
That gives the arbiter a single glob across all sessions and projects, durable across reboots.
This is the one place the `cu.get_project_root()` path mandate does not apply, because the consumer is fleet-wide.
The per-session filename keeps writers safe from append contention.
`base_dir` is injectable for tests; production uses the fleet dir.

Record fields (schema_version 1), one line per emitted heartbeat decision.
    Fields: schema_version, session_id, persona, ts (ISO-8601 UTC).
    Outcome    : "poked", "honored" or "cap_reached" (raw decide_heartbeat outcome).
    Poke_count : per-session heartbeat count after this event, plus cap.
    Work_owed  : bool, null in v1 (oracle_verdict=None); a real bool at v2 with zero schema change.
    Awaiting   : str or null (from the hold artifact, else null).
    Reason     : str, present only when outcome is "poked".

Emit policy: only poked, honored and cap_reached, plus the v2 "idle" beacon.
`not_owed` is skipped: a Stop hook fires after every ordinary turn, so it would be constant noise, not fleet signal.
Disabled or malformed-config sessions never reach the emit, because they have no decide_heartbeat outcome.

The `OUTCOME_POKE` value is "poked", one name everywhere; consumers reference the constant.
There is no compatibility shim: old on-disk records with the pre-rename outcome value age out of the read windows.

Deferred to v2, not built: JSONL rotation or a line cap, so the file cannot grow unbounded.
"""
import os
import json
import datetime
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED,
)


SCHEMA_VERSION           = 1
EVENTS_FILENAME_TEMPLATE = "{session_id}.jsonl"

# Fleet-wide events dir (NOT project root — see module docstring).
FLEET_EVENTS_DIR = Path( os.path.expanduser( "~/.claude/heartbeat-events" ) )

# v2 genuine-idle DECLARATION beacon value (arbiter design §6.2). The caller
# (Rachel's adapter) passes outcome="idle" ONLY on the TRANSITION into
# genuine-idle (gate via is_idle_transition) — never per-turn. A
# backward-compatible additive outcome VALUE (no field change) → schema_version
# stays 1.
EVENT_IDLE = "idle"

# Outcome values emit_outcome will write. v1 = {poked, honored, cap_reached}
# (not_owed is per-turn noise, skipped); v2 ADDS the explicit "idle" beacon.
EMITTED_OUTCOMES = ( OUTCOME_POKE, OUTCOME_HONORED, OUTCOME_CAP_REACHED, EVENT_IDLE )

# Fleet liveness 4th-signal discriminator (arbiter liveness fix, Part 7 / Step
# 1.3). The Notification hook's idle_prompt branch emits a record carrying
# `kind="idle_prompt"` — a passive recency INPUT, NOT a poke-outcome. The
# discriminator is LOAD-BEARING: build_fleet_view filters kind=idle_prompt OUT
# of the ACTIVITY axis (last/state) and the stop_event age, and feeds it into
# idle_prompt_age_s ONLY. The record deliberately carries NO `outcome` key so it
# can never map through _STATE_BY_OUTCOME even if a filter were missed.
EVENT_KIND_IDLE_PROMPT = "idle_prompt"

# Fleet roster TOMBSTONE discriminator (reap-tombstone roster-eviction fix,
# 2026-06-15). A manager-reaped session has its bridge DELETED before the
# arbiter can read its PID, so the fast kill-0 death path (find_dead_sessions)
# structurally can't fire — the row lingers "stale" for ~60 min until its event
# ages out. The reaper appends ONE authoritative `kind="reaped"` record on the
# event rail the arbiter already polls; the arbiter force-offlines the row and
# reuses the existing publish-prune machinery. Like idle_prompt, the record
# carries NO `outcome` key (never maps through _STATE_BY_OUTCOME) and is handled
# OFF the activity axis. It is authoritative (written only by the host-side
# reap), so a force-offline can only follow a REAL reap — no false-death risk.
EVENT_KIND_REAPED = "reaped"

# Fleet PROGRESS discriminator (arbiter signs-of-life fix, 2026-06-16, Fix 2). A
# task-store WRITE — harness TaskCreate/TaskUpdate OR MCP task_create/
# task_transition — is unambiguous coordination work-advancement (a manager
# moving/creating task items). The PostToolUse hook appends ONE
# `kind="task_transition"` record per task-store write so the arbiter can fold a
# per-session last_task_transition_ts into _fleet_progress_signature: a working
# manager who creates/moves task items now registers as PROGRESS, fixing the
# false WHOLE-FLEET-STALL on an actively-coordinating fleet. Unlike commons
# chatter / idle DMs, a task write CANNOT be idle noise, so counting it as
# progress does NOT re-open the chatty-but-stuck blind spot. Like idle_prompt /
# reaped, the record carries NO `outcome` key (never maps through
# _STATE_BY_OUTCOME) and build_fleet_view keeps it OFF the activity axis
# (never `state` / never `last_event_ts`) — it feeds last_task_transition_ts ONLY.
EVENT_KIND_TASK_TRANSITION = "task_transition"


def _resolve_base_dir( base_dir ):
    """
    Return the events directory: base_dir when given, else the fleet dir.

    Ensures:
        - base_dir provided: Path( base_dir )
        - base_dir is None: the fleet dir (~/.claude/heartbeat-events), intentionally not
          cu.get_project_root(), because the consumer is the cross-fleet arbiter, not a project-local reader.
    """
    if base_dir is not None:
        return Path( base_dir )
    return FLEET_EVENTS_DIR


def events_path( session_id, base_dir=None ):
    """
    Return the per-session events file path under the chosen events directory.

    Ensures:
        - Returns <base_dir-or-fleet-dir>/<session_id>.jsonl
        - Empty session_id collapses to the literal suffix "unknown".
    """
    suffix = session_id if session_id else "unknown"
    return _resolve_base_dir( base_dir ) / EVENTS_FILENAME_TEMPLATE.format( session_id=suffix )


def _now_iso():
    """
    Return the current UTC instant as an ISO-8601 string with seconds precision.

    Ensures:
        - returns the current UTC instant as an ISO-8601 string (seconds)
    """
    return datetime.datetime.now( datetime.timezone.utc ).isoformat( timespec="seconds" )


def emit_outcome( session_id, persona, outcome, poke_count, cap,
                  work_owed=None, awaiting=None, reason=None, ts=None, base_dir=None ):
    """
    Append one fire-and-forget poke-outcome record; never raises.

    Requires:
        - session_id is a string
        - persona is a string or None (from the session, known even with no hold)
        - outcome is a decide_heartbeat `OUTCOME_*` string
        - poke_count (after this event's increment) and cap are ints
        - work_owed is a bool or None (None in v1)
        - awaiting is a string or None (caller passes the hold's awaiting, else None)
        - reason is the poke text (included only when outcome == "poked")

    Ensures:
        - Emits for {poked, honored, cap_reached, idle}; any other outcome
          (including not_owed and unknown) returns False and writes nothing
        - Creates the fleet dir if missing (parents, idempotent)
        - Appends exactly one JSON line (schema_version 1 record)
        - reason key present only for the poke outcome (omitted otherwise)
        - Returns True on a successful append; False on a skipped outcome or
          any write / serialization failure, and never raises into the caller
    """
    try:
        if outcome not in EMITTED_OUTCOMES:
            return False

        record = {
            "schema_version" : SCHEMA_VERSION,
            "session_id"     : session_id,
            "persona"        : persona,
            "ts"             : ts if ts is not None else _now_iso(),
            "outcome"        : outcome,
            "poke_count"     : poke_count,
            "cap"            : cap,
            "work_owed"      : work_owed,
            "awaiting"       : awaiting,
        }
        if outcome == OUTCOME_POKE and reason is not None:
            record[ "reason" ] = reason

        path = events_path( session_id, base_dir=base_dir )
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "a" ) as f:
            f.write( json.dumps( record ) + "\n" )
        return True
    except ( OSError, TypeError, ValueError ):
        return False


def emit_idle_prompt( session_id, persona=None, ts=None, base_dir=None ):
    """
    Append one kind-tagged `idle_prompt` recency event; never raises.

    Emitted from the Notification hook's idle_prompt branch, so the arbiter counts an idling session as alive by idle.
    It is the fourth union signal, an edge recency input fired when Claude Code presents the idle prompt.
    The record omits `outcome`; consumers filter on `kind`, so it feeds `idle_prompt_age_s` only, never `state` or `stop_event_age_s`.

    Requires:
        - session_id is a string
        - persona is a string or None (the session's voice-persona name, when
          cheaply resolvable; None is fine, the union backfills from bridges)

    Ensures:
        - Appends exactly one JSON line: schema_version, session_id, persona,
          ts (ISO-8601 UTC), kind="idle_prompt" (no `outcome` key)
        - Creates the fleet dir if missing (parents, idempotent)
        - Returns True on a successful append; False on any write/serialization
          failure, and never raises into the caller (fire-and-forget; TTS unaffected)
        - The event is the strongest cc-native passive liveness beacon
    """
    try:
        record = {
            "schema_version" : SCHEMA_VERSION,
            "session_id"     : session_id,
            "persona"        : persona,
            "ts"             : ts if ts is not None else _now_iso(),
            "kind"           : EVENT_KIND_IDLE_PROMPT,
        }
        path = events_path( session_id, base_dir=base_dir )
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "a" ) as f:
            f.write( json.dumps( record ) + "\n" )
        return True
    except ( OSError, TypeError, ValueError ):
        return False


def emit_reaped( session_id, persona=None, ts=None, base_dir=None ):
    """
    Append one kind-tagged `reaped` tombstone event; never raises.

    The host-side reaper (`session_spawner.dismiss_sessions`) emits it per torn-down session, so the arbiter force-offlines the row in one poll.
    Otherwise the row waits about 60 minutes for its event age to cross `stale_seconds`.
    The reap deletes the bridge first, destroying the PID the kill-0 death path needs; the record omits `outcome`, so consumers filter on `kind`.

    Requires:
        - session_id is a string
        - persona is a string or None (the reaped worker's voice-persona name,
          already captured by `_capture_reap_identity`; None is fine, the union
          backfills from any surviving signal)

    Ensures:
        - Appends exactly one JSON line: schema_version, session_id, persona,
          ts (ISO-8601 UTC), kind="reaped" (no `outcome` key). It stays off the
          activity axis (`state`, `last_event_ts`) and is a membership and verdict signal only.
        - Creates the fleet dir if missing (parents, idempotent)
        - Returns True on a successful append; False on any write/serialization
          failure, and never raises into the caller (best-effort; a write failure
          must never break the reap)
    """
    try:
        record = {
            "schema_version" : SCHEMA_VERSION,
            "session_id"     : session_id,
            "persona"        : persona,
            "ts"             : ts if ts is not None else _now_iso(),
            "kind"           : EVENT_KIND_REAPED,
        }
        path = events_path( session_id, base_dir=base_dir )
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "a" ) as f:
            f.write( json.dumps( record ) + "\n" )
        return True
    except ( OSError, TypeError, ValueError ):
        return False


def emit_task_transition( session_id, persona=None, ts=None, base_dir=None ):
    """
    Append one kind-tagged `task_transition` progress event; never raises.

    The PostToolUse hook emits it on every task-store write (TaskCreate, TaskUpdate, task_create or task_transition).
    A task write is unambiguous work advancement and can never be idle noise, unlike commons chatter or idle DMs.
    So the arbiter counts it as progress without reopening the chatty-but-stuck blind spot the progress signature guards.

    Requires:
        - session_id is a string
        - persona is a string or None (the session's voice-persona name, when
          cheaply resolvable; None is fine, the union backfills from bridges)

    Ensures:
        - Appends exactly one JSON line: schema_version, session_id, persona,
          ts (ISO-8601 UTC), kind="task_transition" (no `outcome` key). Mirrors emit_idle_prompt
          and emit_reaped: consumers filter on `kind`, so it feeds `last_task_transition_ts` only,
          never `state` or `stop_event_age_s`.
        - Creates the fleet dir if missing (parents, idempotent)
        - Returns True on a successful append; False on any write/serialization
          failure, and never raises into the caller (fire-and-forget; the task tool
          call is unaffected)
    """
    try:
        record = {
            "schema_version" : SCHEMA_VERSION,
            "session_id"     : session_id,
            "persona"        : persona,
            "ts"             : ts if ts is not None else _now_iso(),
            "kind"           : EVENT_KIND_TASK_TRANSITION,
        }
        path = events_path( session_id, base_dir=base_dir )
        path.parent.mkdir( parents=True, exist_ok=True )
        with open( path, "a" ) as f:
            f.write( json.dumps( record ) + "\n" )
        return True
    except ( OSError, TypeError, ValueError ):
        return False


def read_events( session_id, base_dir=None ):
    """
    Read this session's event records (for the v2 arbiter + tests).

    Requires:
        - session_id is a string

    Ensures:
        - Returns a list of record dicts in append order
        - Missing file → [] ; unreadable file → [] (never raises)
        - Blank / malformed / non-object JSON lines are skipped (resilient tail)
    """
    path = events_path( session_id, base_dir=base_dir )
    records = [ ]
    try:
        if not path.exists():
            return records
        with open( path ) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads( line )
                except ValueError:
                    continue
                if isinstance( obj, dict ):
                    records.append( obj )
    except OSError:
        return records
    return records


def last_emitted_outcome( session_id, base_dir=None ):
    """
    Return the session's most recent emitted outcome value, or None if none exists.

    Kind-tagged records (idle_prompt, task_transition, reaped) omit `outcome`; consumers must ignore them on the outcome axis.
    A trailing idle_prompt masked a real `idle` outcome, so a parked worker's peer DM buffered instead of waking the pane.
    So the scan runs from the tail and returns the first record that carries an `outcome`.

    Requires:
        - session_id is a string

    Ensures:
        - Returns the `outcome` of the most recent record that has one, skipping
          any trailing kind-tagged records that omit it; None when no emitted
          outcome exists, and never raises (read_events is total). A naive records[-1] read returned None
          here and made `cc_notification_listener._recipient_is_injectable()` False for a parked worker.
    """
    records = read_events( session_id, base_dir=base_dir )
    for record in reversed( records ):
        if "outcome" in record:
            return record[ "outcome" ]
    return None


def should_emit_idle( last_outcome ):
    """
    Return whether the idle beacon should fire, given the last emitted outcome.

    Pure edge-trigger predicate: emit only on the transition into idle, when the last outcome was not already "idle".
    It is sticky until superseded: repeated idle stops do not re-emit.
    A poked, honored or cap_reached outcome supersedes, so the next idle is a fresh transition.

    Requires:
        - last_outcome is the prior emitted outcome string, or None (no prior)

    Ensures:
        - Returns True iff last_outcome != "idle" (None gives True: the first idle
          is a transition from nothing).
    """
    return last_outcome != EVENT_IDLE


def is_idle_transition( session_id, base_dir=None ):
    """
    Return whether an idle beacon should be emitted for this session now (the de-dup gate).

    Composes last_emitted_outcome and should_emit_idle so the caller can gate the emit on the transition:
        if is_idle_transition(session_id): emit_outcome(..., EVENT_IDLE, ...)

    Ensures:
        - Returns True on the transition into idle; False if already idle.
        - Never raises.
    """
    return should_emit_idle( last_emitted_outcome( session_id, base_dir=base_dir ) )


def quick_smoke_test():
    """
    Self-contained smoke test (temp dir — never touches the real fleet dir).

    Ensures:
        - Returns True if emit → read round-trips for the emitted outcomes,
          not_owed is skipped, and reason rides only the poke; raises otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sid = "smoke321"

        assert emit_outcome( sid, "Tiffany 💍", OUTCOME_POKE, 1, 3,
                             awaiting="peer:Rachel", reason="poke text", base_dir=tmp ) is True
        assert emit_outcome( sid, "Tiffany 💍", OUTCOME_HONORED, 0, 3,
                             awaiting="peer:Rachel", reason="ignored", base_dir=tmp ) is True
        # not_owed is skipped — no line, returns False (caller emits "idle" instead)
        assert emit_outcome( sid, "Tiffany 💍", "not_owed", 0, 3, base_dir=tmp ) is False

        # v2 idle beacon — edge-triggered (last was "honored" → a transition)
        assert is_idle_transition( sid, base_dir=tmp ) is True
        assert emit_outcome( sid, "Tiffany 💍", EVENT_IDLE, 0, 3, work_owed=False, base_dir=tmp ) is True
        assert is_idle_transition( sid, base_dir=tmp ) is False   # already idle → de-dup

        events = read_events( sid, base_dir=tmp )
        assert len( events ) == 3,                      "poked + honored + idle expected"
        assert events[ 0 ][ "outcome" ] == OUTCOME_POKE == "poked"
        assert events[ 0 ][ "reason" ] == "poke text"
        assert events[ 0 ][ "work_owed" ] is None,      "v1 work_owed is null"
        assert events[ 0 ][ "awaiting" ] == "peer:Rachel"
        assert events[ 1 ][ "outcome" ] == "honored"
        assert "reason" not in events[ 1 ],             "reason rides ONLY the poke"
        assert events[ 2 ][ "outcome" ] == "idle"
        assert events[ 2 ][ "work_owed" ] is False
        assert "reason" not in events[ 2 ]

        # Step 1.3 — kind-tagged idle_prompt recency event (NO `outcome` key, so
        # it never maps through _STATE_BY_OUTCOME; consumers filter on `kind`).
        assert emit_idle_prompt( sid, persona="Tiffany 💍", base_dir=tmp ) is True
        ip = read_events( sid, base_dir=tmp )[ -1 ]
        assert ip[ "kind" ] == EVENT_KIND_IDLE_PROMPT and "outcome" not in ip

        # Reap tombstone — kind-tagged terminal marker (NO `outcome` key); the
        # arbiter force-offlines the row on the next poll.
        assert emit_reaped( sid, persona="Tiffany 💍", base_dir=tmp ) is True
        rp = read_events( sid, base_dir=tmp )[ -1 ]
        assert rp[ "kind" ] == EVENT_KIND_REAPED == "reaped" and "outcome" not in rp
        assert rp[ "persona" ] == "Tiffany 💍"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_events smoke: {'PASS' if ok else 'FAIL'}" )
