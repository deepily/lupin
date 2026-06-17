"""
Task-store mirror — Phase-2 write-path orchestrator (PostToolUse seam).

Mirrors the session's harness task list (Task* tool family) into the unified
task store: "use the harness task list as you always have; the store follows
you" (task-store-discipline.md §1). One entry point,
`mirror_task_tool_event`, called by post_tool_use.py for TaskCreate /
TaskUpdate events only.

Pipeline per invocation (plan §1.6 / §3):

    gate (settings enabled + F4 manager-figure)
      → opportunistic spool drain (C8 replay)
        → map the harness event to a store op (plan §2 mapping table)
          → execute → update the correlation map
            → transport-failure ⇒ spool + flag-once (I4)
            → 4xx server verdict ⇒ drop + flag-once (will never succeed)

Status mapping (ruled, Tiberius qid b312b0f1):

    TaskCreate                     → POST /api/tasks (store status queued)
    TaskCreate w/ metadata.task_store_id → POST /api/tasks/{id}/correlate (respawn adoption)
    TaskUpdate pending             → ->queued
    TaskUpdate in_progress         → ->in_progress
    TaskUpdate completed           → ->review   (NEVER ->done: the hook cannot
                                      fabricate receipts; receipted closes
                                      stay explicit — ruling #1)
    TaskUpdate deleted             → ->dropped, reason="harness-deleted (TaskUpdate)"

The mirror NEVER writes ->blocked / ->done / ->claimed — those semantics ride
explicit MCP/REST transitions only, so the arbiter-oracle `blocked_by
{kind:user}` contract (design §2.1) is untouched by construction.

INVARIANTS: never raises; never blocks the hook beyond the client's bounded
timeout; a session that cannot write FLAGS ONCE (I4) and never fakes.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md.
"""

import time

from lupin_cli.claude_code.hooks.lib.hook_common import log_to_stream
from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona, resolve_project_name
from lupin_cli.claude_code.hooks.lib.manager_figure import is_manager_figure
from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
from lupin_cli.claude_code.hooks.lib import task_store_client as client
from lupin_cli.claude_code.hooks.lib import task_store_map as task_map
from lupin_cli.claude_code.hooks.lib import task_store_spool as spool


TASK_CREATE = "TaskCreate"
TASK_UPDATE = "TaskUpdate"

# Harness status → store to_status (plan §2). completed→review is ruling #1;
# done/blocked/claimed are deliberately ABSENT — never hook-written.
STATUS_TRANSITIONS = {
    "pending"     : "queued",
    "in_progress" : "in_progress",
    "completed"   : "review",
    "deleted"     : "dropped",
}
DROPPED_REASON = "harness-deleted (TaskUpdate)"


def build_correlation_key( stable_session_id, generation, harness_id ):
    """
    Build the C1 precedence-(a) correlation key for a harness task.

    Requires:
        - stable_session_id / harness_id are non-empty strings
        - generation is an int (the session's map generation for this task)

    Ensures:
        - Returns "cc-task:<stable_session_id>:g<generation>:<harness_id>" —
          scoped to the STABLE session id AND the generation (bug 9b23d5bc).
          Harness counters restart after /clear, so the generation segment is
          what makes the post-clear counter "1" yield a DISTINCT key from the
          pre-clear counter "1" — the server-side idempotency probe then never
          adopts the stale prior-generation row.
    """
    return f"cc-task:{stable_session_id}:g{generation}:{harness_id}"


def _entry_key( entry ):
    """
    Compose the generation-scoped map key for a spool-shaped op/entry.

    Requires:
        - entry carries "harness_id"; "generation" is present on every op built
          by _build_op (legacy pre-fix spool lines may lack it ⇒ treated as 0)

    Ensures:
        - Returns "<generation>:<harness_id>" so order-preservation compares two
          ops by the SAME identity the correlation map keys them under (a
          post-clear counter never aliases a pre-clear spooled op)
    """
    return task_map.map_key( entry.get( "generation", 0 ), entry.get( "harness_id" ) )


def _identity( session_id ):
    """
    Resolve the bridge-stamped identity fields for this session.

    Requires:
        - session_id is the stable session id string

    Ensures:
        - Returns ( actor, persona_lower ) — actor is
          "<persona_lower> <sid8>" per the MCP-wrapper identity convention
          (spec §2.1); persona falls back to "unknown" when the bridge has
          no allocation (server still gets a truthful, non-spoofed stamp)
        - Never raises
    """
    persona       = get_voice_persona( session_id )
    persona_lower = ( persona.get( "name" ) or "unknown" ).lower() if isinstance( persona, dict ) else "unknown"
    return f"{persona_lower} {session_id[:8]}", persona_lower


def _log( session_id, phase, **extra ):
    """
    Emit one mirror stream-log line (greppable: phase=task_store_mirror_*).

    Ensures:
        - never raises (log_to_stream's own belt)
    """
    log_to_stream( "post_tool_use", {}, extra={ "phase": phase, "session_id": session_id[:8], **extra } )


def _flag_once( session_id, base_dir, detail ):
    """
    I4 flag-once: record + announce the FIRST write failure since the last
    success; subsequent failures stay silent (no per-event noise).

    Ensures:
        - flagged_at set iff it was previously None (one flag per outage)
        - the flag itself never raises (an unwritable map dir cannot break
          the hook — the log line still fires)
    """
    try:
        data = task_map.read_map( session_id, base_dir )
        if data[ "flagged_at" ] is None:
            task_map.set_flagged( session_id, time.strftime( "%Y-%m-%dT%H:%M:%S%z" ), base_dir )
            _log( session_id, "task_store_mirror_write_failing", detail=detail )
    except Exception:
        _log( session_id, "task_store_mirror_write_failing", detail=detail )


def _clear_flag( session_id, base_dir ):
    """
    Clear the I4 marker on a successful write (so the NEXT outage flags again).

    Ensures:
        - flagged_at cleared iff it was set; never raises
    """
    try:
        data = task_map.read_map( session_id, base_dir )
        if data[ "flagged_at" ] is not None:
            task_map.set_flagged( session_id, None, base_dir )
            _log( session_id, "task_store_mirror_recovered" )
    except Exception:
        pass


def _is_transport_or_5xx( status_code ):
    """
    Is this outcome spool-able (retryable later) per plan §3?

    Ensures:
        - True for transport loss (None) and 5xx; False for received 2xx-4xx
    """
    return status_code is None or status_code >= 500


def _execute_create( settings, api_key, session_id, entry, base_dir ):
    """
    Execute one create op (live or replayed), with the C8 idempotency probe.

    The probe guards the lost-response case: a spooled create whose original
    POST actually landed must ADOPT the existing item, not duplicate it.
    Probe failures are treated as transport (spool-able) — never replay blind.

    Requires:
        - entry is the spool-shaped create dict (op/ts/harness_id/
          correlation_key/payload)

    Ensures:
        - Returns ( outcome, status_code ) where outcome ∈
          { "ok", "spool", "drop" }
        - "ok": the correlation map records harness_id → item_id
        - Never raises (client never raises; map write failure → "spool")
    """
    harness_id = entry[ "harness_id" ]
    generation = entry.get( "generation", 0 )
    ck         = entry[ "correlation_key" ]

    ok, status, body = client.query_by_correlation_key( settings, api_key, ck )
    if not ok and _is_transport_or_5xx( status ):
        return "spool", status
    existing = body.get( "tasks", [ ] ) if ok else [ ]
    item_id  = None
    if existing:
        candidate = existing[ 0 ]
        # COLLISION GUARD (bug 9b23d5bc): adopt the probed row ONLY when it is
        # the SAME task — its title matches the create's. A title MISMATCH means
        # the correlation key landed on an UNRELATED row (a residual collision
        # the generation key did not catch — e.g. a never-recorded spooled
        # create); refuse adoption and insert a FRESH item rather than mutate
        # the stranger. A title match is the legit C8 lost-response replay.
        if candidate.get( "title" ) == entry[ "payload" ].get( "title" ):
            item_id = candidate.get( "id" )
    if item_id is None:
        ok, status, body = client.create_task( settings, api_key, entry[ "payload" ] )
        if not ok:
            return ( "spool" if _is_transport_or_5xx( status ) else "drop" ), status
        item_id = body.get( "id" )

    try:
        task_map.record_task( session_id, generation, harness_id, item_id, entry[ "harness_status" ], base_dir )
    except OSError:
        return "spool", None
    return "ok", status


def _execute_transition( settings, api_key, session_id, entry, base_dir ):
    """
    Execute one transition op (live or replayed).

    Requires:
        - entry carries harness_id / harness_status / payload (sans item id —
          the item id is resolved HERE from the correlation map, so a
          replayed transition picks up the id its replayed create just won)

    Ensures:
        - Returns ( outcome, status_code ), outcome ∈ { "ok", "spool", "drop" }
        - "drop" when the map has no item for harness_id (orphan: its create
          was dropped as a 4xx, or predates mirror enablement)
        - Never raises
    """
    harness_id = entry[ "harness_id" ]
    generation = entry.get( "generation", 0 )
    task_entry = task_map.lookup_task( session_id, generation, harness_id, base_dir )
    if not task_entry or not task_entry.get( "item_id" ):
        return "drop", None

    ok, status, body = client.transition_task( settings, api_key, task_entry[ "item_id" ], entry[ "payload" ] )
    if not ok:
        return ( "spool" if _is_transport_or_5xx( status ) else "drop" ), status

    try:
        task_map.record_task( session_id, generation, harness_id, task_entry[ "item_id" ], entry[ "harness_status" ], base_dir )
    except OSError:
        pass  # state advanced server-side; a stale last_status only costs one redundant (422-rejected) retry
    return "ok", status


def _execute_correlate( settings, api_key, session_id, entry, base_dir ):
    """
    Execute one correlate op — the respawn-adoption seam (ruling #4).

    Requires:
        - entry carries harness_id / item_id (the inherited store item uuid
          from TaskCreate metadata.task_store_id) / correlation_key / payload

    Ensures:
        - Returns ( outcome, status_code ), outcome ∈ { "ok", "spool", "drop" }
        - "ok": the map records harness_id → the ADOPTED item id
        - Never raises
    """
    generation = entry.get( "generation", 0 )
    ok, status, body = client.correlate_task( settings, api_key, entry[ "item_id" ], entry[ "payload" ] )
    if not ok:
        return ( "spool" if _is_transport_or_5xx( status ) else "drop" ), status

    try:
        task_map.record_task( session_id, generation, entry[ "harness_id" ], entry[ "item_id" ], entry[ "harness_status" ], base_dir )
    except OSError:
        return "spool", None
    return "ok", status


_EXECUTORS = {
    "create"     : _execute_create,
    "transition" : _execute_transition,
    "correlate"  : _execute_correlate,
}


def _drain_spool( settings, api_key, session_id, base_dir, now_epoch ):
    """
    Opportunistic C8 replay: one bounded FIFO pass over the spool.

    Requires:
        - settings/api_key resolved by the caller (one read per invocation)

    Ensures:
        - TTL-expired entries dropped (counted + logged — no silent cap)
        - Entries replayed FIFO; the FIRST spool-able failure stops the pass
          (everything from there stays spooled, order preserved — a
          transition never jumps its create)
        - 4xx verdicts drop the entry + flag (will never succeed)
        - Returns the number of entries successfully replayed
        - Never raises
    """
    entries = spool.read_entries( session_id, base_dir )
    if not entries:
        return 0

    live, expired = spool.partition_expired( entries, now_epoch, settings[ "spool_ttl_seconds" ] )
    if expired:
        _log( session_id, "task_store_mirror_spool_expired", dropped=len( expired ) )

    survivors = [ ]
    replayed  = 0
    for i, entry in enumerate( live ):
        executor = _EXECUTORS.get( entry.get( "op" ) )
        if executor is None:
            _log( session_id, "task_store_mirror_spool_unknown_op", op=entry.get( "op" ) )
            continue
        outcome, status = executor( settings, api_key, session_id, entry, base_dir )
        if outcome == "ok":
            replayed += 1
        elif outcome == "spool":
            survivors = live[ i: ]   # stop the pass; keep this + everything behind it
            break
        else:
            _flag_once( session_id, base_dir, f"spool replay dropped op={entry.get('op')} status={status}" )

    try:
        spool.rewrite_entries( session_id, survivors, base_dir )
    except OSError:
        pass  # next invocation re-reads the original file; replays are idempotent (probe + server rules)
    return replayed


def _build_op( payload, session_id, actor, persona_lower, base_dir ):
    """
    Map one Task* hook payload onto a spool-shaped store op (plan §2 table).

    Resolves the GENERATION for the op (bug 9b23d5bc) — this is the one place
    that may MUTATE the map (a generation bump on reset detection); every other
    skip/idempotence decision still lives in the caller. Returns None for events
    that mirror to nothing (metadata-only TaskUpdate, missing ids, unknown
    statuses — each logged by the caller via the second tuple slot).

    Generation rules:
        - CREATE: read the current generation; if this harness counter is
          ALREADY live in that generation (lookup_task hit), the harness counter
          has restarted (post-/clear) ⇒ bump to a fresh generation. Sequential
          NEW counters (2, 3, …) never hit, so they never false-bump.
        - UPDATE: use the current generation as-is (the create that re-seeded the
          generation already bumped it; the update resolves the live slot).

    Requires:
        - payload is the PostToolUse hook input dict
        - actor / persona_lower from _identity
        - base_dir is the per-session runtime-artifact dir (for the map)

    Ensures:
        - Returns ( op_dict_or_None, skip_reason_or_None )
        - op_dict carries: op, ts, generation, harness_id, harness_status,
          correlation_key, payload (+ item_id for correlate)
    """
    tool_name  = payload.get( "tool_name" )
    tool_input = payload.get( "tool_input" ) or { }

    if tool_name == TASK_CREATE:
        response   = payload.get( "tool_response" ) or { }
        task_resp  = response.get( "task" ) if isinstance( response, dict ) else None
        harness_id = task_resp.get( "id" ) if isinstance( task_resp, dict ) else None
        if not harness_id:
            return None, "create_missing_harness_id"
        subject = tool_input.get( "subject" )
        if not subject:
            return None, "create_missing_subject"

        # Generation + RESET DETECTION (bug 9b23d5bc).
        generation = task_map.current_generation( session_id, base_dir )
        if task_map.lookup_task( session_id, generation, str( harness_id ), base_dir ) is not None:
            generation = task_map.bump_generation( session_id, base_dir )

        ck       = build_correlation_key( session_id, generation, str( harness_id ) )
        metadata = tool_input.get( "metadata" )
        adopt_id = metadata.get( "task_store_id" ) if isinstance( metadata, dict ) else None
        if adopt_id:
            return {
                "op"             : "correlate",
                "ts"             : time.time(),
                "generation"     : generation,
                "harness_id"     : str( harness_id ),
                "harness_status" : "pending",
                "item_id"        : str( adopt_id ),
                "correlation_key": ck,
                "payload"        : { "correlation_key": ck, "actor": actor, "authority": "standing" },
            }, None
        return {
            "op"             : "create",
            "ts"             : time.time(),
            "generation"     : generation,
            "harness_id"     : str( harness_id ),
            "harness_status" : "pending",
            "correlation_key": ck,
            "payload"        : {
                "item_class"          : "task",
                "title"               : subject,
                "body"                : tool_input.get( "description" ),
                "project"             : resolve_project_name(),
                "created_by"          : actor,
                "owner_persona"       : persona_lower,
                "accountable_manager" : persona_lower,
                "authority"           : "standing",
                "correlation_key"     : ck,
            },
        }, None

    # TaskUpdate
    harness_id = tool_input.get( "taskId" )
    status     = tool_input.get( "status" )
    if harness_id is None:
        return None, "update_missing_task_id"
    if not status:
        return None, "update_no_status_change"
    to_status = STATUS_TRANSITIONS.get( status )
    if to_status is None:
        return None, f"update_unknown_status:{status}"

    generation         = task_map.current_generation( session_id, base_dir )
    transition_payload = { "to_status": to_status, "actor": actor, "authority": "standing" }
    if to_status == "dropped":
        transition_payload[ "reason" ] = DROPPED_REASON
    return {
        "op"             : "transition",
        "ts"             : time.time(),
        "generation"     : generation,
        "harness_id"     : str( harness_id ),
        "harness_status" : status,
        "correlation_key": build_correlation_key( session_id, generation, str( harness_id ) ),
        "payload"        : transition_payload,
    }, None


def mirror_task_tool_event( payload, session_id, base_dir=None, environ=None ):
    """
    The PostToolUse entry point: mirror one TaskCreate/TaskUpdate event.

    Requires:
        - payload is the hook input dict (tool_name ∈ {TaskCreate, TaskUpdate})
        - session_id is the resolved STABLE session id

    Ensures:
        - Returns a summary dict { "action": ... } (for tests/logs):
          disabled | not_manager | skipped:<reason> | mirrored:<op> |
          spooled:<op> | dropped:<op>
        - settings malformed (ValueError) → fail SAFE: action=disabled, logged
        - F4: non-manager-figure sessions NEVER write (fail-closed gate)
        - C8: spool drained opportunistically BEFORE the new op; transport/5xx
          failures spool the new op; 4xx verdicts drop + flag-once (I4)
        - NEVER raises — any unexpected error is caught, logged, and the hook
          proceeds untouched
    """
    try:
        try:
            settings = load_task_store_settings()
        except ValueError as e:
            _log( session_id, "task_store_mirror_settings_invalid", error=str( e ) )
            return { "action": "disabled" }

        if not settings[ "enabled" ]:
            return { "action": "disabled" }
        if not is_manager_figure( session_id, environ=environ ):
            return { "action": "not_manager" }

        actor, persona_lower = _identity( session_id )
        api_key              = client.read_api_key( environ )

        replayed = _drain_spool( settings, api_key, session_id, base_dir, time.time() )
        if replayed:
            _log( session_id, "task_store_mirror_spool_replayed", count=replayed )

        op, skip_reason = _build_op( payload, session_id, actor, persona_lower, base_dir )
        if op is None:
            if skip_reason != "update_no_status_change":
                _log( session_id, "task_store_mirror_skip", reason=skip_reason )
            return { "action": f"skipped:{skip_reason}" }

        # Idempotence + terminal lockout, locally (no 422 noise): skip when
        # this harness status was already mirrored, or the item is locally
        # known terminal (a dropped item never transitions again). Resolve the
        # entry by the GENERATION-scoped key (bug 9b23d5bc) so a post-/clear
        # counter never reads the prior generation's last_status.
        task_entry = task_map.lookup_task( session_id, op[ "generation" ], op[ "harness_id" ], base_dir )
        if op[ "op" ] == "transition" and task_entry:
            if task_entry.get( "last_status" ) == op[ "harness_status" ]:
                return { "action": "skipped:status_unchanged" }
            if task_entry.get( "last_status" ) == "deleted":
                return { "action": "skipped:terminal" }

        # Order preservation: if anything is still spooled for THIS task (its
        # create, or an earlier transition), the new op must queue behind it.
        # Compared by the generation-scoped key so a reused counter in a NEW
        # generation does not falsely queue behind the old generation's op.
        pending = spool.read_entries( session_id, base_dir )
        op_key  = _entry_key( op )
        if any( _entry_key( e ) == op_key for e in pending ):
            spool.append_entry( session_id, op, base_dir )
            return { "action": f"spooled:{op['op']}" }

        outcome, status = _EXECUTORS[ op[ "op" ] ]( settings, api_key, session_id, op, base_dir )
        if outcome == "ok":
            _clear_flag( session_id, base_dir )
            return { "action": f"mirrored:{op['op']}" }
        if outcome == "spool":
            spool.append_entry( session_id, op, base_dir )
            _flag_once( session_id, base_dir, f"op={op['op']} status={status}" )
            return { "action": f"spooled:{op['op']}" }
        _flag_once( session_id, base_dir, f"op={op['op']} status={status} (verdict — dropped)" )
        return { "action": f"dropped:{op['op']}" }

    except Exception as e:
        # The hook must NEVER break on the mirror — belt over every suspender.
        try:
            _log( session_id, "task_store_mirror_error", error=f"{type( e ).__name__}: {e}" )
        except Exception:
            pass
        return { "action": "error" }
