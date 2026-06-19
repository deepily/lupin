#!/usr/bin/env python3
"""
Heartbeat Hook v2 — per-session Task* state replay (work-owed source).

The §0.3 (corrected) authoritative work-owed source: the session's OWN `Task*`
state, reconstructed from its transcript JSONL (`Stop`-hook `transcript_path`).
`owned_by_me` is TRUE BY CONSTRUCTION — every `Task*` call in that transcript
belongs to that session, so there is zero cross-session attribution.

**Replay model (empirically confirmed — spike in 04 §2, live impl-spike
2026-06-05):**
    - `TaskCreate` assigns a SEQUENTIAL ordinal `taskId` ("1", "2", …) in
      creation order; a created task starts at status `pending` (the tool's
      own contract: "All tasks are created with status pending"). So the Nth
      `TaskCreate` tool_use in the transcript ⇒ `taskId = str(N)`, initial
      status `pending`.
    - `TaskUpdate{taskId, status}` sets that task's status; last write wins.
    - `work_owed = any task whose LATEST status ∈ {in_progress, pending}`;
      `completed` / `deleted` ⇒ not owed.

This feeds the already-100%-covered pure oracle
`heartbeat_work_owed.evaluate_work_owed( todo_items=… )` — the Task* statuses
`in_progress` / `pending` map 1:1 onto its `TODO_IN_PROGRESS` / `TODO_PENDING`.

**Invariant:** pure + never-raises (reads via transcript_reader, which never
raises). A missing/empty transcript ⇒ empty state ⇒ no owed work ⇒
conservative (no false poke). `:7999`-free.

Design authority: planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0.3.
"""
from lupin_cli.claude_code.hooks.lib.transcript_reader import iter_tool_uses
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import (
    TODO_IN_PROGRESS, TODO_PENDING,
)


TASK_CREATE      = "TaskCreate"
TASK_UPDATE      = "TaskUpdate"
CREATED_STATUS   = "pending"               # TaskCreate default (tool contract)
OWED_STATUSES    = ( TODO_IN_PROGRESS, TODO_PENDING )   # in_progress | pending


def replay_task_state( transcript_path, _iter=iter_tool_uses ):
    """
    Replay the session's Task* tool calls into current per-task status.

    Requires:
        - transcript_path is a path-like / string / None
        - _iter is the tool-use iterator (injectable for tests)

    Ensures:
        - Returns a dict { taskId(str): latest_status(str) } in creation order
        - TaskCreate → new task at the next ordinal id, status "pending"
        - TaskUpdate{taskId,status} → overwrites that task's status (last wins)
        - A TaskUpdate with a missing/blank status is ignored (keeps prior)
        - A TaskUpdate for an unknown taskId is recorded defensively (the task
          exists with that status) — never raises on foreign/partial data
        - Empty / missing transcript → {}
        - NEVER raises
    """
    state    = { }
    next_ord = 0
    for name, inp, _id in _iter( transcript_path, names={ TASK_CREATE, TASK_UPDATE } ):
        if name == TASK_CREATE:
            next_ord += 1
            state[ str( next_ord ) ] = CREATED_STATUS
        elif name == TASK_UPDATE:
            task_id = inp.get( "taskId" )
            status  = inp.get( "status" )
            if task_id is None or not status:
                continue
            state[ str( task_id ) ] = status
    return state


def replay_task_subjects( transcript_path, _iter=iter_tool_uses ):
    """
    Replay the session's TaskCreate calls into { taskId(str): subject(str) }.

    PURE — no I/O beyond the injected iterator (which never raises). Additive
    companion to replay_task_state: same SEQUENTIAL-ordinal model (the Nth
    TaskCreate ⇒ taskId str(N)), so the ids returned here align 1:1 with
    replay_task_state's keys. Lets the Stop-hook poke breadcrumb name the OWED
    task items by subject without changing replay_task_state's shape (and thus
    without touching its consumers / the pure oracle).

    Requires:
        - transcript_path is a path-like / string / None
        - _iter is the tool-use iterator (injectable for tests)

    Ensures:
        - Returns { taskId(str): subject(str) } for every TaskCreate that
          carried a non-empty `subject` (the tool's required title field)
        - A TaskCreate with a missing/blank subject is skipped (its ordinal is
          still consumed, so later ids stay aligned with replay_task_state)
        - Empty / missing transcript → {}
        - NEVER raises
    """
    subjects = { }
    next_ord = 0
    for name, inp, _id in _iter( transcript_path, names={ TASK_CREATE } ):
        next_ord += 1
        subject = inp.get( "subject" )
        if subject:
            subjects[ str( next_ord ) ] = subject
    return subjects


def owed_items_from_state( state ):
    """
    Derive the work-owed `todo_items` list from an already-replayed task state.

    PURE — no I/O. Lets the caller replay the transcript ONCE (perf: the Stop
    hook fires every turn) and derive both the owed-items AND the empty-set
    signal from the single state dict, instead of replaying twice.

    Requires:
        - state is a { taskId: status } dict (replay_task_state output)

    Ensures:
        - Returns a list of { "status": <status>, "owned_by_me": True } — one
          per task whose status ∈ {in_progress, pending}
        - owned_by_me is always True (by construction — same transcript =
          same session)
        - No owed tasks → []
    """
    return [
        { "status": status, "owned_by_me": True }
        for status in state.values()
        if status in OWED_STATUSES
    ]


def is_empty_state( state ):
    """
    Is the (already-replayed) Task* state genuinely empty (no tasks at all)?

    PURE companion to owed_items_from_state for the single-replay path.

    Requires:
        - state is a { taskId: status } dict

    Ensures:
        - Returns True iff the state has zero tasks
    """
    return len( state ) == 0


def fetch_task_work_owed( transcript_path, _iter=iter_tool_uses ):
    """
    Convenience wrapper: replay the transcript + derive the work-owed list.

    Requires:
        - transcript_path is a path-like / string / None
        - _iter is the tool-use iterator (injectable for tests)

    Ensures:
        - Returns owed_items_from_state( replay_task_state( transcript_path ) )
        - No owed tasks (or empty transcript) → []
        - NEVER raises

    (The single-replay hot path in stop.py calls replay_task_state +
    owed_items_from_state + is_empty_state directly to avoid replaying twice.)
    """
    return owed_items_from_state( replay_task_state( transcript_path, _iter=_iter ) )


def is_task_set_empty( transcript_path, _iter=iter_tool_uses ):
    """
    Convenience wrapper: replay the transcript + report the empty-set signal.

    Used by the §6.2 genuine-idle declaration beacon (Rick Option B): a
    genuine-idle signal requires BOTH no owed work AND an empty task set.

    Requires:
        - transcript_path is a path-like / string / None

    Ensures:
        - Returns is_empty_state( replay_task_state( transcript_path ) )
        - NEVER raises
    """
    return is_empty_state( replay_task_state( transcript_path, _iter=_iter ) )


def quick_smoke_test():
    """
    Self-contained smoke test of the replay + owed mapping.

    Ensures:
        - Returns True if create/update/last-wins/owed-filter behave as
          designed; raises AssertionError otherwise.
    """
    def fake_iter( _path, names=None ):
        # 3 creates → ids "1","2","3" (all pending); then updates. The Bash
        # event exercises the names-filter SKIP branch (a non-Task* tool the
        # name filter drops) so this stub is branch-complete.
        events = [
            ( "TaskCreate", { "subject": "a" }, "c1" ),
            ( "TaskCreate", { "subject": "b" }, "c2" ),
            ( "TaskCreate", { "subject": "c" }, "c3" ),
            ( "Bash",       { "command": "ls" }, "bx" ),   # filtered out by names → skip branch
            ( "TaskUpdate", { "taskId": "1", "status": "completed" }, "u1" ),
            ( "TaskUpdate", { "taskId": "2", "status": "in_progress" }, "u2" ),
            ( "TaskUpdate", { "taskId": "2", "status": "in_progress" }, "u2b" ),  # idempotent
            ( "TaskUpdate", { "taskId": "9", "status": "deleted" }, "u3" ),       # unknown id, defensive
            ( "TaskUpdate", { "taskId": "3" }, "u4" ),                            # no status → ignored
        ]
        for e in events:
            if names is None or e[ 0 ] in names:
                yield e

    state = replay_task_state( "x", _iter=fake_iter )
    assert state == { "1": "completed", "2": "in_progress", "3": "pending", "9": "deleted" }, state

    owed = fetch_task_work_owed( "x", _iter=fake_iter )
    # owed = task 2 (in_progress) + task 3 (pending) ; 1 completed, 9 deleted excluded
    assert len( owed ) == 2, owed
    assert all( i[ "owned_by_me" ] is True for i in owed )
    assert sorted( i[ "status" ] for i in owed ) == [ "in_progress", "pending" ]

    # Empty transcript → no state, not owed, idle-set empty
    empty_iter = lambda _p, names=None: iter( () )
    assert replay_task_state( "x", _iter=empty_iter ) == { }
    assert fetch_task_work_owed( "x", _iter=empty_iter ) == [ ]
    assert is_task_set_empty( "x", _iter=empty_iter ) is True
    assert is_task_set_empty( "x", _iter=fake_iter ) is False

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_task_state smoke: {'PASS' if ok else 'FAIL'}" )
