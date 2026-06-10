#!/usr/bin/env python3
"""
Unit tests for the v2 Task*-replay work-owed source (heartbeat_task_state.py).

Covers replay_task_state (create→pending ordinal ids, update last-wins,
unknown-id defensive, missing-status ignored, empty), fetch_task_work_owed
(owed filter + owned_by_me True), and is_task_set_empty. The tool-use iterator
is INJECTED (no real transcript needed) — pure replay logic.

Venue: :7999-eligible / local — pure module, sub-second.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import heartbeat_task_state as ts


def _iter_from( events ):
    """Build an injectable iter_tool_uses stub from a list of (name, input, id)."""
    def _it( _path, names=None ):
        for e in events:
            if names is None or e[ 0 ] in names:
                yield e
    return _it


# ── replay_task_subjects (poke-abstract receipts, 2026-06-10) ──────────────────

def test_subjects_captured_by_creation_ordinal():
    it = _iter_from( [
        ( "TaskCreate", { "subject": "Wire the pane" }, "c1" ),
        ( "TaskCreate", { "subject": "Add the splitter" }, "c2" ),
    ] )
    assert ts.replay_task_subjects( "x", _iter=it ) == {
        "1": "Wire the pane", "2": "Add the splitter",
    }


def test_subjects_blank_or_missing_skipped_but_ordinal_consumed():
    # Task #1 has no subject (skipped); #2's subject still keys to ordinal "2"
    # — alignment with replay_task_state's ids is preserved.
    it = _iter_from( [
        ( "TaskCreate", { }, "c1" ),
        ( "TaskCreate", { "subject": "Second" }, "c2" ),
        ( "TaskCreate", { "subject": "" }, "c3" ),
    ] )
    assert ts.replay_task_subjects( "x", _iter=it ) == { "2": "Second" }


def test_subjects_empty_transcript_empty_dict():
    assert ts.replay_task_subjects( "x", _iter=_iter_from( [ ] ) ) == { }


# ── replay_task_state ─────────────────────────────────────────────────────────

def test_create_assigns_sequential_pending_ids():
    it = _iter_from( [
        ( "TaskCreate", { "subject": "a" }, "c1" ),
        ( "TaskCreate", { "subject": "b" }, "c2" ),
    ] )
    assert ts.replay_task_state( "x", _iter=it ) == { "1": "pending", "2": "pending" }


def test_update_sets_status_last_wins():
    it = _iter_from( [
        ( "TaskCreate", {}, "c1" ),
        ( "TaskUpdate", { "taskId": "1", "status": "in_progress" }, "u1" ),
        ( "TaskUpdate", { "taskId": "1", "status": "completed" }, "u2" ),
    ] )
    assert ts.replay_task_state( "x", _iter=it ) == { "1": "completed" }


def test_update_unknown_id_recorded_defensively():
    it = _iter_from( [
        ( "TaskUpdate", { "taskId": "7", "status": "deleted" }, "u1" ),
    ] )
    assert ts.replay_task_state( "x", _iter=it ) == { "7": "deleted" }


def test_update_missing_or_blank_status_ignored():
    it = _iter_from( [
        ( "TaskCreate", {}, "c1" ),
        ( "TaskUpdate", { "taskId": "1" }, "u1" ),                 # no status
        ( "TaskUpdate", { "taskId": "1", "status": "" }, "u2" ),   # blank status
        ( "TaskUpdate", { "status": "in_progress" }, "u3" ),       # no taskId
    ] )
    assert ts.replay_task_state( "x", _iter=it ) == { "1": "pending" }


def test_update_numeric_taskid_coerced_to_str():
    it = _iter_from( [
        ( "TaskCreate", {}, "c1" ),
        ( "TaskUpdate", { "taskId": 1, "status": "completed" }, "u1" ),   # int taskId
    ] )
    assert ts.replay_task_state( "x", _iter=it ) == { "1": "completed" }


def test_empty_transcript_empty_state():
    assert ts.replay_task_state( "x", _iter=_iter_from( [ ] ) ) == { }


def test_replay_ignores_non_task_tools():
    """Defensive: a non-Task* tool slipping past the name filter is skipped."""
    # Stub iterator that ignores the names filter and yields a foreign tool
    def leaky_iter( _path, names=None ):
        yield ( "TaskCreate", {}, "c1" )
        yield ( "Bash", { "command": "ls" }, "b1" )      # not create/update → elif False → skipped
        yield ( "TaskUpdate", { "taskId": "1", "status": "in_progress" }, "u1" )
    assert ts.replay_task_state( "x", _iter=leaky_iter ) == { "1": "in_progress" }


# ── fetch_task_work_owed ──────────────────────────────────────────────────────

def test_fetch_owed_filters_to_in_progress_and_pending():
    it = _iter_from( [
        ( "TaskCreate", {}, "c1" ), ( "TaskCreate", {}, "c2" ),
        ( "TaskCreate", {}, "c3" ), ( "TaskCreate", {}, "c4" ),
        ( "TaskUpdate", { "taskId": "1", "status": "completed" }, "u1" ),
        ( "TaskUpdate", { "taskId": "2", "status": "in_progress" }, "u2" ),
        ( "TaskUpdate", { "taskId": "4", "status": "deleted" }, "u4" ),
        # task 3 stays pending
    ] )
    owed = ts.fetch_task_work_owed( "x", _iter=it )
    assert len( owed ) == 2
    assert all( i[ "owned_by_me" ] is True for i in owed )
    assert sorted( i[ "status" ] for i in owed ) == [ "in_progress", "pending" ]


def test_fetch_no_owed_when_all_terminal():
    it = _iter_from( [
        ( "TaskCreate", {}, "c1" ),
        ( "TaskUpdate", { "taskId": "1", "status": "completed" }, "u1" ),
    ] )
    assert ts.fetch_task_work_owed( "x", _iter=it ) == [ ]


def test_fetch_empty_transcript_empty_list():
    assert ts.fetch_task_work_owed( "x", _iter=_iter_from( [ ] ) ) == [ ]


# ── is_task_set_empty ─────────────────────────────────────────────────────────

def test_idle_set_empty_true_when_no_tasks():
    assert ts.is_task_set_empty( "x", _iter=_iter_from( [ ] ) ) is True


def test_idle_set_empty_false_when_any_task_exists():
    # even an all-completed set is NON-empty (tasks exist) → not genuinely idle
    it = _iter_from( [
        ( "TaskCreate", {}, "c1" ),
        ( "TaskUpdate", { "taskId": "1", "status": "completed" }, "u1" ),
    ] )
    assert ts.is_task_set_empty( "x", _iter=it ) is False


# ── smoke entrypoint ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert ts.quick_smoke_test() is True
