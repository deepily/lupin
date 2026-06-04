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


# ── ordering + composition ────────────────────────────────────────────────────

def test_all_signals_fire_strongest_first():
    v = o.evaluate_work_owed(
        todo_items = [
            { "status": o.TODO_IN_PROGRESS, "owned_by_me": True },
            { "status": o.TODO_PENDING,     "owned_by_me": True },
        ],
        pending_decisions            = [ { "blocked_on_user": False } ],
        unanswered_inbound_questions = [ { "question_id": "q1" } ],
    )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [
        "todo_in_progress", "todo_unstarted", "pending_decision", "unanswered_inbound_question"
    ]
    # specifics carries all four counts
    assert v[ "specifics" ].count( ";" ) == 3


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


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert o.quick_smoke_test() is True
