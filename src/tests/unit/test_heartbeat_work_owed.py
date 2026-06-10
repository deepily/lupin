#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Hook work-owed oracle.

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_work_owed.py

The oracle is a PURE decision function — every test injects parsed state
(no live commons / TODO / transcript access). Exhaustive decision matrix
per §0 #3 / §4 of the canonical design.
"""
from lupin_cli.claude_code.hooks.lib import heartbeat_work_owed as o


# ── empty / None inputs ───────────────────────────────────────────────────────

def test_no_inputs_owes_nothing():
    v = o.evaluate_work_owed()
    assert v[ "work_owed" ] is False
    assert v[ "signals" ]   == [ ]
    assert v[ "specifics" ] == o.NO_WORK_SPECIFICS


def test_explicit_empty_lists_owe_nothing():
    v = o.evaluate_work_owed( todo_items=[ ], pending_decisions=[ ], unanswered_inbound_questions=[ ] )
    assert v[ "work_owed" ] is False


# ── TODO signal ───────────────────────────────────────────────────────────────

def test_in_progress_owned_todo_owes_work():
    v = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [ "todo_in_progress" ]
    assert "in-progress" in v[ "specifics" ]


def test_unstarted_owned_todo_owes_work():
    v = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_PENDING, "owned_by_me": True } ] )
    assert v[ "signals" ] == [ "todo_unstarted" ]


def test_completed_owned_todo_owes_nothing():
    v = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_COMPLETED, "owned_by_me": True } ] )
    assert v[ "work_owed" ] is False


def test_unowned_todo_ignored():
    v = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": False } ] )
    assert v[ "work_owed" ] is False


def test_todo_missing_owned_flag_defaults_to_unowned():
    v = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS } ] )
    assert v[ "work_owed" ] is False


def test_non_dict_todo_entry_skipped():
    v = o.evaluate_work_owed( todo_items=[ "not-a-dict", None, 42 ] )
    assert v[ "work_owed" ] is False


def test_unknown_todo_status_ignored():
    v = o.evaluate_work_owed( todo_items=[ { "status": "blocked", "owned_by_me": True } ] )
    assert v[ "work_owed" ] is False


# ── Pending-Decision signal ───────────────────────────────────────────────────

def test_pending_decision_not_blocked_owes_work():
    v = o.evaluate_work_owed( pending_decisions=[ { "blocked_on_user": False } ] )
    assert v[ "signals" ] == [ "pending_decision" ]
    assert "not blocked on the user" in v[ "specifics" ]


def test_pending_decision_blocked_on_user_owes_nothing():
    v = o.evaluate_work_owed( pending_decisions=[ { "blocked_on_user": True } ] )
    assert v[ "work_owed" ] is False


def test_pending_decision_missing_flag_defaults_actionable():
    # blocked_on_user absent ⇒ falsy ⇒ actionable (you own the decision)
    v = o.evaluate_work_owed( pending_decisions=[ { "title": "pick A or B" } ] )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [ "pending_decision" ]


def test_non_dict_pending_decision_skipped():
    v = o.evaluate_work_owed( pending_decisions=[ "nope", None ] )
    assert v[ "work_owed" ] is False


# ── Unanswered inbound question signal ────────────────────────────────────────

def test_unanswered_inbound_question_owes_work():
    v = o.evaluate_work_owed( unanswered_inbound_questions=[ { "question_id": "q1" } ] )
    assert v[ "signals" ] == [ "unanswered_inbound_question" ]
    assert "awaiting your reply" in v[ "specifics" ]


def test_falsy_inbound_question_entries_dropped():
    v = o.evaluate_work_owed( unanswered_inbound_questions=[ { }, None, 0 ] )
    assert v[ "work_owed" ] is False


# ── outstanding-delegation signal (manager side, 2026-06-09) ──────────────────

def test_outstanding_delegation_owes_work():
    # The bug fix: a manager with NO Task* items but one live spawned worker
    # still owes work (review/reap duty) — must never idle-announce.
    v = o.evaluate_work_owed( outstanding_delegations=[ { "session_name": "cc-reviewer-x-1" } ] )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [ "outstanding_delegation" ]
    assert "1 live worker(s) still out" in v[ "specifics" ]


def test_outstanding_delegation_counts_multiple_workers():
    v = o.evaluate_work_owed( outstanding_delegations=[
        { "session_name": "cc-reviewer-x-1" }, { "session_name": "cc-tester-x-1" } ] )
    assert "2 live worker(s) still out" in v[ "specifics" ]


def test_all_workers_reaped_owes_nothing():
    # Empty list = every spawned worker dead/reaped → idle allowed.
    v = o.evaluate_work_owed( outstanding_delegations=[ ] )
    assert v[ "work_owed" ] is False


def test_falsy_delegation_entries_dropped():
    v = o.evaluate_work_owed( outstanding_delegations=[ { }, None, 0 ] )
    assert v[ "work_owed" ] is False


# ── ordering + composition ────────────────────────────────────────────────────

def test_all_signals_fire_strongest_first():
    v = o.evaluate_work_owed(
        todo_items = [
            { "status": o.TODO_IN_PROGRESS, "owned_by_me": True },
            { "status": o.TODO_PENDING,     "owned_by_me": True },
        ],
        pending_decisions            = [ { "blocked_on_user": False } ],
        unanswered_inbound_questions = [ { "question_id": "q1" } ],
        outstanding_delegations      = [ { "session_name": "cc-reviewer-x-1" } ],
    )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [
        "todo_in_progress", "todo_unstarted", "pending_decision",
        "unanswered_inbound_question", "outstanding_delegation"
    ]
    # specifics carries all five counts
    assert v[ "specifics" ].count( ";" ) == 4


# ── build_poke_reason ─────────────────────────────────────────────────────────

def test_build_poke_reason_includes_specifics():
    v      = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] )
    reason = o.build_poke_reason( v )
    assert reason.startswith( "Do not stop yet" )
    assert "in-progress TODO" in reason
    assert "declare a fresh hold" in reason


def test_build_poke_reason_with_no_work_uses_placeholder():
    v      = o.evaluate_work_owed()
    reason = o.build_poke_reason( v )
    assert o.NO_WORK_SPECIFICS in reason


# ── v2 — Task*-replay shape contract (María §0.3 / doc 04 §4) ──────────────────

def test_v2_task_replay_shape_maps_1to1():
    # Rachel's fetch_task_work_owed yields {status, owned_by_me:True} for tasks
    # whose LATEST Task* status ∈ {in_progress, pending}. Confirm evaluate_work_owed
    # consumes that shape UNCHANGED — Task* status vocab == the oracle's constants.
    task_items = [
        { "status": "in_progress", "owned_by_me": True },
        { "status": "pending",     "owned_by_me": True },
    ]
    v = o.evaluate_work_owed( todo_items=task_items )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [ "todo_in_progress", "todo_unstarted" ]
    # status literals equal the oracle constants → genuine 1:1, no leaf change.
    assert ( o.TODO_IN_PROGRESS, o.TODO_PENDING ) == ( "in_progress", "pending" )


def test_v2_task_replay_empty_owed_set_is_idle():
    # All-completed/deleted dropped by the replay → empty owed set → not owed
    # (→ the adapter emits the genuine-idle beacon).
    assert o.evaluate_work_owed( todo_items=[ ] )[ "work_owed" ] is False


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert o.quick_smoke_test() is True
