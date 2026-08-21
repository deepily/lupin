#!/usr/bin/env python3
"""
Unit tests for CJ Flow v2 unit C — the executor seam, StageTrace, and
PendingRequests (`src/cosa/rest/v2/{executor,trace,pending}.py`).

Everything here is pure and duck-typed: fake snapshots/agents stand in for the
real SolutionSnapshot / AgentBase surfaces so the executor's control logic is
pinned without importing any heavy machinery — which is exactly the property the
seam exists to have. A deterministic FakeClock removes wall-clock reads from the
trace and TTL assertions.

Venue: :7999 (pure logic, no server, no state). Run:
    PYTHONPATH=src pytest src/tests/unit/test_v2_executor_seam.py -v
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import cosa.rest.v2.executor as executor_module
from cosa.rest.v2.executor import (
    Executor,
    InlineExecutor,
    Outcome,
    QueuedExecutor,
    Work,
    make_executor,
)
from cosa.rest.v2.pending import PendingEntry, PendingRequests
from cosa.rest.v2.trace import StageTrace


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeClock:
    """A monotonic nanosecond clock the test drives by hand."""

    def __init__( self, start: int=0 ) -> None:
        self.now = start

    def __call__( self ) -> int:
        return self.now

    def advance( self, ns: int ) -> int:
        self.now += ns
        return self.now


class FakeSnapshot:
    """Duck-typed SolutionSnapshot: for_current_user copy + run_code/run_formatter."""

    def __init__( self, id_hash: str="id-1", answer: str="raw", conversational: str="pretty" ) -> None:
        self.id_hash               = id_hash
        self.answer                = answer
        self.answer_conversational = None
        self._conversational       = conversational
        self.is_copy               = False

    def for_current_user( self, user_id: str, session_id: str ) -> "FakeSnapshot":
        copy_snap                          = type( self )( self.id_hash, self.answer, self._conversational )
        copy_snap.user_id                  = user_id
        copy_snap.session_id               = session_id
        copy_snap.is_copy                  = True
        return copy_snap

    def run_code( self ) -> dict:
        self.answer = "computed"          # mutation lands on the COPY, never the original
        return { "return_code": 0, "output": self.answer }

    def run_formatter( self ) -> str:
        self.answer_conversational = self._conversational
        return self._conversational


class BrokenReplaySnapshot( FakeSnapshot ):
    """A snapshot whose run_code throws — exercises the replay failure path."""

    def run_code( self ) -> dict:
        raise ValueError( "replay blew up" )


class FakeAgent:
    """Duck-typed AgentBase: do_all() sets answer_conversational and returns it."""

    def __init__( self, answer: str="agent-raw", conversational: str="agent-pretty", boom: bool=False ) -> None:
        self.answer                = answer
        self.answer_conversational = None
        self._conversational       = conversational
        self._boom                 = boom

    def do_all( self ) -> str:
        if self._boom:
            raise RuntimeError( "agent boom" )
        self.answer_conversational = self._conversational
        return self._conversational


def _work( kind: str, job: object, snapshotable: bool=True ) -> Work:
    return Work(
        kind         = kind,
        job          = job,
        user_id      = "u-1",
        user_email   = "u@example.com",
        session_id   = "s-1",
        snapshotable = snapshotable,
    )


# --------------------------------------------------------------------------- #
# StageTrace
# --------------------------------------------------------------------------- #
class TestStageTrace:

    def test_marks_and_has_mark( self ) -> None:
        clock = FakeClock( 1000 )
        trace = StageTrace( trace_id="t-1", trace_dir="/tmp/unused", clock=clock )
        assert trace.trace_id == "t-1"
        assert not trace.has_mark( "t_recv" )
        assert trace.mark( "t_recv" ) == 1000
        assert trace.has_mark( "t_recv" )

    def test_default_trace_id_and_dir( self, monkeypatch ) -> None:
        # trace_id None -> uuid hex; trace_dir None -> project_root/io/v2-flow.
        monkeypatch.setenv( "LUPIN_ROOT", "/opt/lupin-root" )
        trace = StageTrace()
        assert len( trace.trace_id ) == 32
        assert trace.trace_dir == "/opt/lupin-root/io/v2-flow"

    def test_set_copies_containers_and_keeps_scalars( self ) -> None:
        trace  = StageTrace( trace_dir="/tmp/unused" )
        payload = { "a": 1 }
        trace.set( "meta", payload )
        trace.set( "path", "replay" )
        payload[ "a" ] = 999                       # mutate the caller's dict AFTER recording
        assert trace.fields[ "meta" ] == { "a": 1 }   # record is isolated
        assert trace.fields[ "path" ] == "replay"

    def test_update_records_many( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        trace.update( path="agent", route_reason="ok", best_score=91.5 )
        assert trace.fields == { "path": "agent", "route_reason": "ok", "best_score": 91.5 }

    def test_elapsed_ms_present_and_absent( self ) -> None:
        clock = FakeClock( 0 )
        trace = StageTrace( trace_dir="/tmp/unused", clock=clock )
        trace.mark( "a" )
        clock.advance( 2_500_000 )                  # 2.5 ms
        trace.mark( "b" )
        assert trace.elapsed_ms( "a", "b" ) == 2.5
        assert trace.elapsed_ms( "missing", "b" ) is None    # start absent
        assert trace.elapsed_ms( "a", "missing" ) is None    # end absent

    def test_timings_ms_empty( self ) -> None:
        assert StageTrace( trace_dir="/tmp/unused" ).timings_ms() == {}

    def test_timings_ms_anchor_present( self ) -> None:
        clock = FakeClock( 0 )
        trace = StageTrace( trace_dir="/tmp/unused", anchor="t_recv", clock=clock )
        trace.mark( "t_recv" )
        clock.advance( 1_000_000 )
        trace.mark( "t_router" )
        assert trace.timings_ms() == { "t_recv": 0.0, "t_router": 1.0 }

    def test_timings_ms_anchor_absent_uses_earliest( self ) -> None:
        clock = FakeClock( 5_000_000 )
        trace = StageTrace( trace_dir="/tmp/unused", anchor="t_recv", clock=clock )
        trace.mark( "t_router" )                    # earliest = 5ms
        clock.advance( 3_000_000 )
        trace.mark( "t_agent" )
        # anchor "t_recv" not marked -> base is the earliest mark (t_router)
        assert trace.timings_ms() == { "t_router": 0.0, "t_agent": 3.0 }

    def test_to_record_shape( self ) -> None:
        trace = StageTrace( trace_id="t-9", trace_dir="/tmp/unused" )
        trace.mark( "t_recv" )
        trace.set( "path", "receptionist" )
        record = trace.to_record()
        assert record[ "trace_id" ] == "t-9"
        assert record[ "path" ] == "receptionist"
        assert "ts" in record and "timings_ms" in record

    def test_write_default_day( self, tmp_path ) -> None:
        trace = StageTrace( trace_id="t-w", trace_dir=str( tmp_path ) )
        trace.mark( "t_recv" )
        trace.set( "path", "agent" )
        path = trace.write()                         # today None -> strftime
        with open( path ) as handle:
            line = handle.readline()
        assert json.loads( line )[ "trace_id" ] == "t-w"

    def test_write_explicit_day_appends( self, tmp_path ) -> None:
        trace = StageTrace( trace_id="t-a", trace_dir=str( tmp_path ) )
        trace.set( "path", "replay" )
        p1 = trace.write( today="2026-08-14" )
        p2 = trace.write( today="2026-08-14" )
        assert p1 == p2
        with open( p1 ) as handle:
            lines = handle.readlines()
        assert len( lines ) == 2                     # appended, not overwritten


# --------------------------------------------------------------------------- #
# Work / Outcome / Executor protocol
# --------------------------------------------------------------------------- #
class TestWorkAndOutcome:

    def test_work_is_frozen( self ) -> None:
        # GUARD: Work must be immutable so no field (and no shared dict) can be
        # rewritten after handoff. Breaking `frozen=True` makes this assignment
        # succeed and turns this test red — see the report's red receipt.
        work = _work( "agent", FakeAgent() )
        with pytest.raises( dataclasses.FrozenInstanceError ):
            work.kind = "replay"

    def test_outcome_defaults( self ) -> None:
        outcome = Outcome( status="done" )
        assert outcome.answer is None
        assert outcome.answer_raw is None
        assert outcome.job_id is None
        assert outcome.error is None

    def test_executors_satisfy_protocol( self ) -> None:
        assert isinstance( InlineExecutor(), Executor )
        assert isinstance( QueuedExecutor(), Executor )


# --------------------------------------------------------------------------- #
# InlineExecutor
# --------------------------------------------------------------------------- #
class TestInlineExecutor:

    def test_replay_success_and_marks( self ) -> None:
        clock = FakeClock( 0 )
        trace = StageTrace( trace_dir="/tmp/unused", clock=clock )
        snap  = FakeSnapshot( id_hash="id-42", answer="raw", conversational="It is 4." )
        out   = InlineExecutor().submit( _work( "replay", snap ), trace )
        assert out.status == "done"
        assert out.answer == "It is 4."
        assert out.answer_raw == "computed"          # snap.answer after run_code, from the COPY
        assert out.job_id == "id-42"
        assert trace.has_mark( "t_replay_code" )
        assert trace.has_mark( "t_replay_format" )

    def test_replay_does_not_mutate_original_snapshot( self ) -> None:
        # GUARD (risk 3): replay runs on a for_current_user() COPY, so the shared
        # cached snapshot is never mutated. Breaking the copy (running on
        # work.job directly) leaves original.answer == "computed" and turns this
        # red — see the report's red receipt.
        trace    = StageTrace( trace_dir="/tmp/unused" )
        original = FakeSnapshot( answer="raw", conversational="pretty" )
        InlineExecutor().submit( _work( "replay", original ), trace )
        assert original.answer == "raw"              # untouched
        assert original.answer_conversational is None
        assert original.is_copy is False

    def test_replay_failure_is_captured_not_raised( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        out   = InlineExecutor().submit( _work( "replay", BrokenReplaySnapshot() ), trace )
        assert out.status == "failed"
        assert "replay blew up" in out.error

    def test_agent_success( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        agent = FakeAgent( answer="agent-raw", conversational="Sunny." )
        out   = InlineExecutor().submit( _work( "agent", agent ), trace )
        assert out.status == "done"
        assert out.answer == "Sunny."
        assert out.answer_raw == "agent-raw"
        assert trace.has_mark( "t_agent" )

    def test_receptionist_routes_through_agent_path( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        out   = InlineExecutor().submit( _work( "receptionist", FakeAgent( conversational="Hello." ) ), trace )
        assert out.status == "done"
        assert out.answer == "Hello."

    def test_agent_failure_is_captured_not_raised( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        out   = InlineExecutor().submit( _work( "agent", FakeAgent( boom=True ) ), trace )
        assert out.status == "failed"
        assert "agent boom" in out.error

    def test_unknown_kind_raises( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        with pytest.raises( ValueError, match="cannot handle work.kind" ):
            InlineExecutor().submit( _work( "sideways", FakeAgent() ), trace )


# --------------------------------------------------------------------------- #
# QueuedExecutor + make_executor
# --------------------------------------------------------------------------- #
class TestQueuedAndFactory:

    def test_queued_stub_raises( self ) -> None:
        trace = StageTrace( trace_dir="/tmp/unused" )
        with pytest.raises( NotImplementedError, match="phase-2 stub" ):
            QueuedExecutor().submit( _work( "agent", FakeAgent() ), trace )

    def test_make_executor_inline( self ) -> None:
        assert isinstance( make_executor( "inline" ), InlineExecutor )
        assert isinstance( make_executor(), InlineExecutor )        # default

    def test_make_executor_queued( self ) -> None:
        assert isinstance( make_executor( "queued" ), QueuedExecutor )

    def test_make_executor_unknown_raises( self ) -> None:
        with pytest.raises( ValueError, match="Unknown v2 executor" ):
            make_executor( "magic" )


# --------------------------------------------------------------------------- #
# PendingRequests
# --------------------------------------------------------------------------- #
class TestPendingRequests:

    def test_put_generates_id_and_get_returns_entry( self ) -> None:
        pend = PendingRequests()
        pid  = pend.put( extraction={ "location": None }, user_email="u@x.com", session_id="s", user_id="u" )
        assert len( pid ) == 32
        entry = pend.get( pid )
        assert isinstance( entry, PendingEntry )
        assert entry.status == "pending"
        assert entry.user_email == "u@x.com"

    def test_put_supplied_id_and_copies_container_extraction( self ) -> None:
        pend       = PendingRequests()
        extraction = { "location": None }
        pid        = pend.put( extraction=extraction, user_email="u", session_id="s", user_id="u", pending_id="fixed" )
        assert pid == "fixed"
        extraction[ "location" ] = "Tokyo"                 # mutate caller's dict after parking
        assert pend.get( "fixed" ).extraction == { "location": None }   # stored copy is isolated

    def test_put_keeps_non_container_extraction_by_identity( self ) -> None:
        pend      = PendingRequests()
        sentinel  = object()
        pid       = pend.put( extraction=sentinel, user_email="u", session_id="s", user_id="u" )
        assert pend.get( pid ).extraction is sentinel

    def test_get_missing_returns_none( self ) -> None:
        assert PendingRequests().get( "nope" ) is None

    def test_get_evicts_expired( self ) -> None:
        clock = FakeClock( 0 )
        pend  = PendingRequests( ttl_seconds=1.0, clock=clock )
        pid   = pend.put( extraction=None, user_email="u", session_id="s", user_id="u" )
        clock.advance( 2_000_000_000 )                     # 2s > 1s TTL
        assert pend.get( pid ) is None
        assert len( pend ) == 0                            # evicted, not merely hidden

    def test_set_status_advances_and_records_answer( self ) -> None:
        pend = PendingRequests()
        pid  = pend.put( extraction=None, user_email="u", session_id="s", user_id="u" )
        assert pend.set_status( pid, "running" ) is True
        assert pend.get( pid ).status == "running"
        assert pend.set_status( pid, "done", answer="It is sunny." ) is True
        entry = pend.get( pid )
        assert entry.status == "done"
        assert entry.answer == "It is sunny."
        assert entry.error is None

    def test_set_status_records_error( self ) -> None:
        pend = PendingRequests()
        pid  = pend.put( extraction=None, user_email="u", session_id="s", user_id="u" )
        assert pend.set_status( pid, "failed", error="router died" ) is True
        assert pend.get( pid ).error == "router died"

    def test_set_status_absent_returns_false( self ) -> None:
        assert PendingRequests().set_status( "ghost", "running" ) is False

    def test_sweep_evicts_only_expired( self ) -> None:
        clock = FakeClock( 0 )
        pend  = PendingRequests( ttl_seconds=1.0, clock=clock )
        old   = pend.put( extraction=None, user_email="u", session_id="s", user_id="u" )
        clock.advance( 2_000_000_000 )
        fresh = pend.put( extraction=None, user_email="u", session_id="s", user_id="u" )
        removed = pend.sweep()
        assert removed == 1
        assert pend.get( old ) is None
        assert pend.get( fresh ) is not None

    def test_contains_true_and_false( self ) -> None:
        pend = PendingRequests()
        pid  = pend.put( extraction=None, user_email="u", session_id="s", user_id="u" )
        assert pid in pend
        assert "absent" not in pend

    def test_entry_defaults( self ) -> None:
        entry = PendingEntry(
            pending_id="p", extraction=None, user_email="u", session_id="s", user_id="u", created_ns=0,
        )
        assert entry.status == "pending"
        assert entry.answer is None
        assert entry.error is None


class TestOutcomeStatusVocabulary:
    """
    Step 1 of the brain-integration plan: `Outcome.status` says "waiting", not
    "parked", for a queued hand-off.

    Rick's ruling: a queued job is waiting its turn, not paused. "parked" stays
    for the flow's needs-input path, which is a genuine suspension — a request
    held pending an answer from the user. The two situations were reading as one
    word, and the word described only one of them.

    Nothing emits the queued value yet (`QueuedExecutor.submit` still raises;
    the executor is built in step 2), so the field's declared vocabulary is the
    only surface a test can hold. That is enough: the rename exists to stop the
    wrong word entering the type in the first place.
    """

    def _status_options( self ):
        """The declared member set of Outcome.status, read off the dataclass."""
        import typing
        hints = typing.get_type_hints( Outcome )
        return set( typing.get_args( hints[ "status" ] ) )

    def test_waiting_is_a_member( self ) -> None:
        """
        RED ON REVERT: put "parked" back in the Literal in place of "waiting"
        and this fails.
        """
        assert "waiting" in self._status_options()

    def test_parked_is_not_a_member( self ) -> None:
        """
        The other half of the rename. Without this, a Literal listing BOTH words
        passes the test above while leaving the ambiguity exactly where it was.
        """
        assert "parked" not in self._status_options()

    def test_the_rest_of_the_vocabulary_is_unchanged( self ) -> None:
        """
        Ensures the rename touched one member and not the others — this fails if
        someone rewrites the whole Literal while renaming.
        """
        assert self._status_options() == { "done", "waiting", "failed" }

    def test_no_outcome_is_built_with_a_status_outside_the_literal( self ) -> None:
        """
        The reviewer's falsifier, made executable.

        Pocholo's step-1 finding was that narrowing this Literal would make the
        type lie, because the flow emits "parked". It does not: the flow passes
        "parked" as a plain string to `_emit( status: str )`, and no Outcome is
        ever constructed with it. But "no Outcome is built with a value outside
        the Literal" is the right thing to hold, and holding it by hand means
        re-deriving it every time someone adds a branch.

        So this reads every `Outcome( status="..." )` in the v2 package and
        checks each against the Literal ITSELF, not a copy of it. If someone adds
        an executor that returns "parked" — the thing that would genuinely make
        the narrow Literal a lie — this fails and names the value.

        RED ON REVERT: add `Outcome( status="parked" )` anywhere under
        cosa/rest/v2 and this fails.
        """
        import pathlib
        import re

        allowed = self._status_options()
        v2_dir  = pathlib.Path( executor_module.__file__ ).parent
        built   = []
        for path in sorted( v2_dir.glob( "*.py" ) ):
            for found in re.findall( r'Outcome\(\s*status\s*=\s*"([^"]+)"', path.read_text() ):
                built.append( ( path.name, found ) )

        assert built, "found no Outcome constructions at all — this test has gone vacuous"
        offenders = [ ( name, value ) for name, value in built if value not in allowed ]
        assert not offenders, (
            f"Outcome built with a status outside the Literal {sorted( allowed )}: {offenders}. "
            f"Either the executor is wrong or the Literal needs widening — but they must agree."
        )

    def test_the_needs_input_path_still_says_parked( self ) -> None:
        """
        The rename must NOT reach the flow. `flow.py` uses "parked" as the
        RESPONSE status when a request is suspended awaiting the user, which is
        the one place the word is accurate.

        RED ON REVERT: rename those too, and this fails — which is the point,
        because a blanket search-and-replace is the likely way to get step 1
        wrong.
        """
        import inspect
        from cosa.rest.v2 import flow as flow_module
        source = inspect.getsource( flow_module )
        assert 'status="parked"' in source
