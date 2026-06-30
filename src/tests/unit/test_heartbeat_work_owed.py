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


# ── needs_verification signal (inward twin, 6929f4ac §3-§5) ───────────────────

def test_needs_verification_true_owes_work():
    v = o.evaluate_work_owed( needs_verification=True )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [ "needs_verification" ]
    assert "worker-verification overdue" in v[ "specifics" ]
    assert "last_looked_in_on_workers_ts" in v[ "specifics" ]   # guard: stamp instruction present


def test_needs_verification_false_owes_nothing():
    assert o.evaluate_work_owed( needs_verification=False )[ "work_owed" ] is False
    # default (omitted) is also off
    assert o.evaluate_work_owed()[ "signals" ] == [ ]


# ── outstanding_user_gate signal (outward twin, 6929f4ac §9) ──────────────────

def test_open_user_gate_owes_work():
    v = o.evaluate_work_owed( open_user_gates=[ { "id": "g1" } ] )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [ "outstanding_user_gate" ]
    assert "awaiting Rick" in v[ "specifics" ]
    assert "last_asked_ts" in v[ "specifics" ]                  # guard: stamp instruction present
    # Face-B canonical wording (manager-autonomy.md §9.2 v1.7 / role-goals.md v1.2,
    # Rick-locked) — applied VERBATIM, must not drift. The "AND mint the typed
    # operator gate" clause in particular must never be dropped (96d1b8ca).
    assert "the manager MUST fire a dedicated HIGH-PRIORITY 'action-required' notification (a targeted ask_*) to the user the moment it's raised — NOT a line buried in a status notify — AND mint the typed operator gate" in v[ "specifics" ]


def test_open_user_gate_counts_multiple():
    v = o.evaluate_work_owed( open_user_gates=[ { "id": "g1" }, { "id": "g2" } ] )
    assert "2 open user-gate(s)" in v[ "specifics" ]


def test_falsy_user_gate_entries_dropped():
    v = o.evaluate_work_owed( open_user_gates=[ { }, None, 0 ] )
    assert v[ "work_owed" ] is False


def test_empty_user_gates_owes_nothing():
    assert o.evaluate_work_owed( open_user_gates=[ ] )[ "work_owed" ] is False


# ── manager_needs_verification — the pure debounce predicate ──────────────────

def test_manager_needs_verification_no_workers_is_false():
    # No worker out ⇒ nothing to verify ⇒ never a verification debt (gate).
    assert o.manager_needs_verification( [ ], None, _NOW ) is False
    assert o.manager_needs_verification( None, None, _NOW ) is False
    assert o.manager_needs_verification( [ None, { } ], None, _NOW ) is False   # all falsy filtered


def test_manager_needs_verification_never_looked_in_is_true():
    # Workers out + no prior look-in ⇒ owe a first look (bias-to-owe).
    assert o.manager_needs_verification( [ { "session_name": "w" } ], None, _NOW ) is True


def test_manager_needs_verification_unparseable_ts_is_true():
    # Workers out + undateable stamp ⇒ bias-to-owe (poke cap bounds cost).
    assert o.manager_needs_verification( [ { "session_name": "w" } ], "not-a-ts", _NOW ) is True


def test_manager_needs_verification_fresh_look_in_is_false():
    # Looked in 1 min ago (< 10 min debounce) ⇒ not yet due.
    assert o.manager_needs_verification( [ { "session_name": "w" } ], _ago( 60 ), _NOW ) is False


def test_manager_needs_verification_stale_look_in_is_true():
    # Looked in 11 min ago (> 10 min debounce) ⇒ due to verify again.
    assert o.manager_needs_verification( [ { "session_name": "w" } ], _ago( 660 ), _NOW ) is True


def test_manager_needs_verification_boundary_equal_is_true():
    # Exactly at the threshold owes (>=) — a 10-min-old look-in is due.
    assert o.manager_needs_verification(
        [ { "session_name": "w" } ], _ago( o.VERIFICATION_DEBOUNCE_SECONDS ), _NOW ) is True


def test_manager_needs_verification_custom_threshold():
    # Looked in 5 min ago, threshold 4 min ⇒ due.
    assert o.manager_needs_verification(
        [ { "session_name": "w" } ], _ago( 300 ), _NOW, threshold_seconds=240 ) is True
    assert o.manager_needs_verification(
        [ { "session_name": "w" } ], _ago( 300 ), _NOW, threshold_seconds=600 ) is False


def test_iso_age_seconds_shared_helper():
    # The extracted single-source age helper underlies both inbound + verification.
    assert abs( o._iso_age_seconds( _ago( 120 ), _NOW ) - 120 ) < 1
    assert o._iso_age_seconds( None, _NOW )   is None
    assert o._iso_age_seconds( 123, _NOW )    is None
    assert o._iso_age_seconds( "nope", _NOW ) is None


# ── Face A: manager_needs_spinup_check — the spin-up nudge debounce predicate ──

def test_spinup_no_idle_capacity_is_false():
    # No room under the cap ⇒ never nudge, regardless of backlog / elapsed.
    assert o.manager_needs_spinup_check( 99, False, None, _NOW ) is False


def test_spinup_backlog_below_floor_is_false():
    # Backlog < N ⇒ never nudge (the manager judges small backlogs itself).
    assert o.manager_needs_spinup_check( o.SPINUP_BACKLOG_MIN_N - 1, True, None, _NOW ) is False


def test_spinup_bool_backlog_rejected():
    # bool is an int subclass — True must NOT slip through as backlog 1.
    assert o.manager_needs_spinup_check( True, True, None, _NOW ) is False


def test_spinup_non_int_backlog_rejected():
    # Foreign/garbage backlog value ⇒ never nudge (never raises).
    assert o.manager_needs_spinup_check( "5", True, None, _NOW ) is False


def test_spinup_backlog_and_capacity_never_checked_is_true():
    # Backlog ≥ N + idle capacity + no prior check ⇒ bias-to-nudge a first check.
    assert o.manager_needs_spinup_check( o.SPINUP_BACKLOG_MIN_N, True, None, _NOW ) is True


def test_spinup_unparseable_ts_is_true():
    assert o.manager_needs_spinup_check( 5, True, "not-a-ts", _NOW ) is True


def test_spinup_fresh_check_is_false():
    # Checked 1 min ago (< 10 min debounce) ⇒ not yet due.
    assert o.manager_needs_spinup_check( 5, True, _ago( 60 ), _NOW ) is False


def test_spinup_stale_check_is_true():
    # Checked 11 min ago (> 10 min debounce) ⇒ due to re-nudge.
    assert o.manager_needs_spinup_check( 5, True, _ago( 660 ), _NOW ) is True


def test_spinup_boundary_equal_is_true():
    assert o.manager_needs_spinup_check(
        5, True, _ago( o.SPINUP_CHECK_DEBOUNCE_SECONDS ), _NOW ) is True


def test_spinup_custom_thresholds():
    # Custom debounce + custom backlog floor both honored.
    assert o.manager_needs_spinup_check( 5, True, _ago( 300 ), _NOW, threshold_seconds=240 ) is True
    assert o.manager_needs_spinup_check( 5, True, _ago( 300 ), _NOW, threshold_seconds=600 ) is False
    assert o.manager_needs_spinup_check( 2, True, None, _NOW, backlog_min_n=2 ) is True


def test_spinup_nudge_signal_routes():
    v = o.evaluate_work_owed( needs_spinup_check=True )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "spinup_nudge" ]
    assert o.evaluate_work_owed( needs_spinup_check=False )[ "work_owed" ] is False


# ── Face B: manager_needs_question_surface — the re-surface debounce predicate ──

def test_surface_no_open_gate_is_false():
    # No open operator gate ⇒ nothing to surface (gates the whole predicate).
    assert o.manager_needs_question_surface( [ ], None, _NOW ) is False
    assert o.manager_needs_question_surface( None, None, _NOW ) is False
    assert o.manager_needs_question_surface( [ None, 0 ], None, _NOW ) is False   # falsy entries filtered


def test_surface_open_gate_never_surfaced_is_true():
    assert o.manager_needs_question_surface( [ { "id": "og1" } ], None, _NOW ) is True


def test_surface_unparseable_ts_is_true():
    assert o.manager_needs_question_surface( [ { "id": "og1" } ], "not-a-ts", _NOW ) is True


def test_surface_fresh_is_false():
    assert o.manager_needs_question_surface( [ { "id": "og1" } ], _ago( 60 ), _NOW ) is False


def test_surface_stale_is_true():
    assert o.manager_needs_question_surface( [ { "id": "og1" } ], _ago( 660 ), _NOW ) is True


def test_surface_boundary_equal_is_true():
    assert o.manager_needs_question_surface(
        [ { "id": "og1" } ], _ago( o.SURFACE_QUESTIONS_DEBOUNCE_SECONDS ), _NOW ) is True


def test_surface_custom_threshold():
    assert o.manager_needs_question_surface( [ { "id": "og1" } ], _ago( 300 ), _NOW, threshold_seconds=240 ) is True
    assert o.manager_needs_question_surface( [ { "id": "og1" } ], _ago( 300 ), _NOW, threshold_seconds=600 ) is False


def test_surface_operator_gates_signal_routes():
    v = o.evaluate_work_owed( needs_question_surface=True )
    assert v[ "work_owed" ] is True and v[ "signals" ] == [ "surface_operator_gates" ]
    assert o.evaluate_work_owed( needs_question_surface=False )[ "work_owed" ] is False
    # Face-B canonical wording, applied VERBATIM (Rick-locked; manager-autonomy.md
    # §9.2 v1.7 / role-goals.md v1.2) — the mint-the-typed-gate clause must persist
    # (96d1b8ca). Distinct from outstanding_user_gate: this is the re-surface site.
    assert "the manager MUST fire a dedicated HIGH-PRIORITY 'action-required' notification (a targeted ask_*) to the user the moment it's raised — NOT a line buried in a status notify — AND mint the typed operator gate" in v[ "specifics" ]
    assert "last_surfaced_questions_ts" in v[ "specifics" ]      # guard: stamp instruction present


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
        needs_verification           = True,
        open_user_gates              = [ { "id": "g1" } ],
    )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [
        "todo_in_progress", "todo_unstarted", "pending_decision",
        "unanswered_inbound_question", "outstanding_delegation",
        "needs_verification", "outstanding_user_gate",
    ]
    # specifics carries all seven counts (6 separators)
    assert v[ "specifics" ].count( ";" ) == 6


def test_all_nine_signals_fire_strongest_first():
    # The two proactive-manager signals (surface_operator_gates, spinup_nudge)
    # append AFTER outstanding_user_gate, strongest-first order preserved.
    v = o.evaluate_work_owed(
        todo_items = [
            { "status": o.TODO_IN_PROGRESS, "owned_by_me": True },
            { "status": o.TODO_PENDING,     "owned_by_me": True },
        ],
        pending_decisions            = [ { "blocked_on_user": False } ],
        unanswered_inbound_questions = [ { "question_id": "q1" } ],
        outstanding_delegations      = [ { "session_name": "cc-reviewer-x-1" } ],
        needs_verification           = True,
        open_user_gates              = [ { "id": "g1" } ],
        needs_question_surface       = True,
        needs_spinup_check           = True,
    )
    assert v[ "work_owed" ] is True
    assert v[ "signals" ] == [
        "todo_in_progress", "todo_unstarted", "pending_decision",
        "unanswered_inbound_question", "outstanding_delegation",
        "needs_verification", "outstanding_user_gate",
        "surface_operator_gates", "spinup_nudge",
    ]
    assert v[ "specifics" ].count( ";" ) == 8


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


# ── MANAGE-not-BUILD owed-work message wording (apply-spec §2, 2026-06-29) ─────
#
# §2.2 forks step 1 (managers delegate, don't build); §2-NEW inserts a
# blocked-on-USER option 3 (fire an ask_* directly, never bury it in a hold);
# the old "nothing to do" option renumbers to 4. These pin the new POKE_REASON
# template text so a silent regression is caught.

def test_poke_reason_step1_tells_managers_to_delegate_not_build():
    v      = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] )
    reason = o.build_poke_reason( v )
    assert "1. Owe work? Resume and drive it now" in reason
    assert "assign/delegate it to a worker" in reason
    assert "do NOT build it yourself" in reason


def test_poke_reason_has_blocked_on_user_option_three():
    v      = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] )
    reason = o.build_poke_reason( v )
    assert "3. Blocked on the USER" in reason
    assert "ask_yes_no" in reason and "ask_multiple_choice" in reason and "converse" in reason
    assert "re-ask until answered" in reason
    # the old nothing-to-do branch renumbered to 4
    assert "4. Truly nothing to do? Declare it — write a hold with work_owed: false." in reason
    assert "3. Truly nothing to do" not in reason


def test_poke_reason_options_numbered_one_through_four():
    v      = o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] )
    reason = o.build_poke_reason( v )
    for n in ( "1. ", "2. ", "3. ", "4. " ):
        assert "\n" + n in reason or reason.lstrip().startswith( n )


def test_spinup_nudge_specifics_owes_a_staff_up_this_tick():
    v = o.evaluate_work_owed( needs_spinup_check=True )
    assert "more open tasks than active workers" in v[ "specifics" ]
    assert "OWE a staff-up THIS tick" in v[ "specifics" ]
    assert "redline" in v[ "specifics" ]
    assert "last_spinup_check_ts" in v[ "specifics" ]        # stamp instruction preserved


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


# ── inbound age-out partition (acked-inbound ledger spec part (e)) ─────────────

import datetime as _dt

_T0  = _dt.datetime( 2026, 6, 10, 12, 0, 0, tzinfo=_dt.timezone.utc )
_NOW = _T0.timestamp()


def _ago( seconds ):
    """ISO-8601 string for `seconds` before the fixed _NOW reference."""
    return ( _T0 - _dt.timedelta( seconds=seconds ) ).isoformat()


def test_inbound_age_seconds_parses_offset():
    age = o._inbound_age_seconds( { "ts": _ago( 60 ) }, _NOW )
    assert abs( age - 60 ) < 1


def test_inbound_age_seconds_normalizes_z_suffix():
    # Trailing "Z" must parse (3.10 fromisoformat rejects it without the fix).
    age = o._inbound_age_seconds( { "ts": "2026-06-10T11:00:00Z" }, _NOW )
    assert abs( age - 3600 ) < 1


def test_inbound_age_seconds_undateable_returns_none():
    assert o._inbound_age_seconds( { },                _NOW ) is None   # missing ts
    assert o._inbound_age_seconds( { "ts": 123 },      _NOW ) is None   # non-string ts
    assert o._inbound_age_seconds( { "ts": "nope" },   _NOW ) is None   # unparseable
    assert o._inbound_age_seconds( "not-a-dict",       _NOW ) is None   # non-dict entry


def test_partition_fresh_vs_stale():
    fresh, stale = o.partition_inbound_by_age(
        [ { "question_id": "f", "ts": _ago( 3600 ) },      # 1h → fresh
          { "question_id": "s", "ts": _ago( 90000 ) } ],   # 25h → stale (>24h default)
        _NOW )
    assert [ e[ "question_id" ] for e in fresh ] == [ "f" ]
    assert [ e[ "question_id" ] for e in stale ] == [ "s" ]


def test_partition_boundary_equal_is_fresh():
    # Exactly at the threshold is FRESH (strict ">" defines stale).
    fresh, stale = o.partition_inbound_by_age(
        [ { "question_id": "edge", "ts": _ago( o.INBOUND_STALE_AFTER_SECONDS ) } ], _NOW )
    assert [ e[ "question_id" ] for e in fresh ] == [ "edge" ] and stale == [ ]


def test_partition_undateable_is_fresh_bias_to_owed():
    fresh, stale = o.partition_inbound_by_age( [ { "question_id": "x" } ], _NOW )
    assert [ e[ "question_id" ] for e in fresh ] == [ "x" ] and stale == [ ]


def test_partition_custom_threshold():
    fresh, stale = o.partition_inbound_by_age(
        [ { "question_id": "h", "ts": _ago( 3600 ) } ], _NOW, stale_after_seconds=1800 )
    assert fresh == [ ] and [ e[ "question_id" ] for e in stale ] == [ "h" ]


def test_partition_preserves_order_within_buckets():
    items = [ { "question_id": "a", "ts": _ago( 10 ) },
              { "question_id": "b", "ts": _ago( 99999 ) },
              { "question_id": "c", "ts": _ago( 20 ) },
              { "question_id": "d", "ts": _ago( 99998 ) } ]
    fresh, stale = o.partition_inbound_by_age( items, _NOW )
    assert [ e[ "question_id" ] for e in fresh ] == [ "a", "c" ]
    assert [ e[ "question_id" ] for e in stale ] == [ "b", "d" ]


# ── is_heartbeat_poke_prompt — c121037b facet 1 (self-poke vs user re-engagement) ─
#
# The self-poke rides the Stop-hook `reason` field and is re-submitted as a prompt
# via tmux send-keys; UserPromptSubmit must recognize it so it does NOT reset the
# poke-cap on the heartbeat's OWN poke (that reset every turn was the FM that
# defeated the cap — poke_count stuck at 1 across 23 pokes). Both poke reasons open
# with POKE_PROMPT_SENTINEL.

def test_sentinel_prefixes_both_poke_reasons():
    """One-name rule: the oracle-owed AND self-declared reasons both open with it."""
    from lupin_cli.claude_code.hooks.lib.heartbeat_decision import DECLARED_OWED_REASON
    owed_reason = o.build_poke_reason(
        o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] ) )
    assert owed_reason.startswith( o.POKE_PROMPT_SENTINEL )
    assert DECLARED_OWED_REASON.startswith( o.POKE_PROMPT_SENTINEL )


def test_detects_oracle_owed_poke_reason():
    reason = o.build_poke_reason(
        o.evaluate_work_owed( todo_items=[ { "status": o.TODO_IN_PROGRESS, "owned_by_me": True } ] ) )
    assert o.is_heartbeat_poke_prompt( reason ) is True


def test_detects_declared_owed_poke_reason():
    from lupin_cli.claude_code.hooks.lib.heartbeat_decision import DECLARED_OWED_REASON
    assert o.is_heartbeat_poke_prompt( DECLARED_OWED_REASON ) is True


def test_detects_poke_with_leading_whitespace():
    # tmux/console may prepend whitespace; lstrip before the prefix match.
    assert o.is_heartbeat_poke_prompt( "\n  " + o.POKE_PROMPT_SENTINEL + " (x) and no fresh hold." ) is True


def test_genuine_user_prompt_is_not_a_poke():
    assert o.is_heartbeat_poke_prompt( "please fix the failing test" ) is False
    assert o.is_heartbeat_poke_prompt( "Do not stop — but this is the user talking" ) is False


def test_non_string_and_empty_are_not_pokes():
    assert o.is_heartbeat_poke_prompt( None )      is False
    assert o.is_heartbeat_poke_prompt( "" )        is False
    assert o.is_heartbeat_poke_prompt( "   " )     is False
    assert o.is_heartbeat_poke_prompt( 12345 )     is False   # non-string foreign payload
    assert o.is_heartbeat_poke_prompt( [ "x" ] )   is False
