#!/usr/bin/env python3
"""
Unit tests for CJ Flow v2's branch logic (unit D) — src/cosa/rest/v2/flow.py.

Hermetic: every collaborator (cache, router, expeditor, executor, pending,
notifier) is a fake, and `resolve` / `JOB_ARG_CONTRACTS` are patched at the flow
module boundary, so the four branches + every degradation are exercised with NO
live Postgres, NO model server, and NO TTS network call. :7999-eligible.

Coverage target is the Lupin-wide hard gate: 100% lines AND branches on flow.py.
Each guard is proven able to fail — the receptionist degradations, the write-back
kill-switch seam, the fail-loud construction guard, and the speak/compose forks
all have a test that would go red if the branch flipped.
"""

import types

import pytest

from cosa.rest.v2 import flow as flow_mod
from cosa.rest.v2.flow import AskFlow
from cosa.rest.v2.pending import PendingRequests


# ────────────────────────────────────────────────────────────── fakes

class FakeAgent:
    """Constructible on the shared 11-kwarg signature; never actually run (the
    executor is faked, so do_all() is never reached from the flow's view)."""

    def __init__( self, **kwargs ):
        self.kwargs = kwargs

    def do_all( self ):                       # pragma: no cover - executor is faked
        return "unused"


class FakeReceptionist( FakeAgent ):
    pass


class FakeSpec:
    """Stand-in for registry.AgentSpec: the three attrs the flow reads."""

    def __init__( self, required_args=(), factory=FakeAgent, snapshotable=True ):
        self.required_args = required_args
        self.factory       = factory
        self.snapshotable  = snapshotable


def _lookup( is_replay_hit=False, snapshot=None, tier=1, similarity=0.0, best_score=0.0,
             best_candidate=None, embed_cached=False, question_normalized="q",
             t_exact_ms=0.1, t_embed_ms=0.2, t_ann_ms=0.3 ):
    return types.SimpleNamespace(
        is_replay_hit=is_replay_hit, snapshot=snapshot, tier=tier, similarity=similarity,
        best_score=best_score, best_candidate=best_candidate, embed_cached=embed_cached,
        question_normalized=question_normalized, t_exact_ms=t_exact_ms,
        t_embed_ms=t_embed_ms, t_ann_ms=t_ann_ms,
    )


def _outcome( status="done", answer="the answer", answer_raw="raw", job_id=None, error=None ):
    return types.SimpleNamespace( status=status, answer=answer, answer_raw=answer_raw,
                                  job_id=job_id, error=error )


def _extraction( final_args=None, missing=(), fallback_questions=None ):
    return types.SimpleNamespace(
        final_args=final_args if final_args is not None else {},
        missing=list( missing ),
        fallback_questions=fallback_questions if fallback_questions is not None else {},
        fallback_defaults={}, special_handlers={},
    )


class FakeCache:
    def __init__( self, lookup_result=None, write_back_id="snap-123" ):
        self._lookup       = lookup_result if lookup_result is not None else _lookup()
        self._write_back_id = write_back_id
        self.snapshot_calls = []
        self.write_back_calls = []

    def lookup( self, question ):
        return self._lookup

    def snapshot_from_result( self, **kwargs ):
        self.snapshot_calls.append( kwargs )
        return types.SimpleNamespace( tag="snap-object" )

    def write_back( self, snapshot, writeback_enabled=True ):
        self.write_back_calls.append( ( snapshot, writeback_enabled ) )
        return self._write_back_id


class CacheNoWriteBack:
    """A cache missing the write-back methods — trips the fail-loud guard."""

    def lookup( self, question ):
        return _lookup()


class FakeRouter:
    def __init__( self, command="agent router go to math", raw_args="" ):
        self._command  = command
        self._raw_args = raw_args

    def route( self, question ):
        return ( self._command, self._raw_args )


class FakeExpeditor:
    def __init__( self, extraction=None, raise_exc=None ):
        self._extraction = extraction if extraction is not None else _extraction()
        self._raise_exc  = raise_exc
        self.calls       = []

    def extract( self, command, raw_args, question, spec ):
        self.calls.append( ( command, raw_args, question, spec ) )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._extraction


class FakeExecutor:
    def __init__( self, outcome=None ):
        self._outcome = outcome if outcome is not None else _outcome()
        self.works    = []

    def submit( self, work, trace ):
        self.works.append( work )
        return self._outcome


class FakePending:
    def __init__( self ):
        self.put_calls = []

    def put( self, **kwargs ):
        self.put_calls.append( kwargs )
        return "pend-1"

    def get( self, pending_id ):                 # pragma: no cover - unused by flow
        return None

    def set_status( self, pending_id, status ):  # pragma: no cover - unused by flow
        return None


class FakeNotifier:
    def __init__( self ):
        self.requests = []

    def __call__( self, request ):
        self.requests.append( request )


# ────────────────────────────────────────────────────────────── fixtures

@pytest.fixture
def notifier():
    return FakeNotifier()


def _make_flow( tmp_path, cache, router, expeditor, executor, pending, notifier,
                *, writeback_enabled=False, similarity_floor=100.0 ):
    return AskFlow(
        cache, router, expeditor, executor, pending,
        similarity_floor=similarity_floor, writeback_enabled=writeback_enabled,
        receptionist_factory=FakeReceptionist, notifier=notifier,
        trace_dir=str( tmp_path ),
    )


_CTX = dict( user_id="u1", user_email="u@x.com", session_id="s1", websocket_id="ws1" )


# ────────────────────────────────────────────────────────────── construction guard

def test_construction_raises_when_writeback_on_but_cache_lacks_methods( tmp_path, notifier ):
    with pytest.raises( ValueError, match="writeback enabled" ):
        AskFlow( CacheNoWriteBack(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                 FakePending(), writeback_enabled=True, notifier=notifier,
                 trace_dir=str( tmp_path ) )


def test_construction_ok_when_writeback_on_and_cache_has_methods( tmp_path, notifier ):
    f = AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(),
                 writeback_enabled=True, notifier=notifier, trace_dir=str( tmp_path ) )
    assert f.writeback_enabled is True


def test_construction_ok_when_writeback_off_even_without_methods( tmp_path, notifier ):
    f = AskFlow( CacheNoWriteBack(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                 FakePending(), writeback_enabled=False, notifier=notifier,
                 trace_dir=str( tmp_path ) )
    assert f.writeback_enabled is False


# ────────────────────────────────────────────────────────────── branch 1 — replay

def test_replay_hit_done_returns_replay_result( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    exe   = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
    f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.run( "what is 2+2", **_CTX, speak=True, interactive=True )
    assert r[ "path" ] == "replay"
    assert r[ "route_reason" ] == "exact_hit"
    assert r[ "cache_hit" ] is True
    assert r[ "command" ] == "agent router go to math"
    assert exe.works[ 0 ].kind == "replay"
    assert exe.works[ 0 ].snapshotable is False


def test_replay_hit_failed_degrades_to_receptionist( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    # first submit (replay) fails; the receptionist submit then succeeds.
    outcomes = [ _outcome( status="failed", answer=None, error="boom" ), _outcome( status="done" ) ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    exe = _SeqExecutor()
    f   = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.run( "what is 2+2", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "replay_error"


# ────────────────────────────────────────────────────────────── branch 2 — router

def test_router_unknown_degrades_to_receptionist( tmp_path, notifier ):
    router = FakeRouter( command="unknown", raw_args="" )
    f = _make_flow( tmp_path, FakeCache(), router, FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "gibberish", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "router_error"


def test_resolve_none_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command: None )
    router = FakeRouter( command="agent router go to deep research" )
    f = _make_flow( tmp_path, FakeCache(), router, FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "do deep research", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"


# ────────────────────────────────────────────────────────────── branch — args_none

def test_args_none_runs_agent_directly( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    exe = FakeExecutor( _outcome( status="done", answer="42", answer_raw="42" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "what time is it", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "args_none"
    assert exe.works[ 0 ].kind == "agent"


# ────────────────────────────────────────────────────────────── branch — extract fails

def test_extract_exception_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router    = FakeRouter( command="agent router go to weather" )
    expeditor = FakeExpeditor( raise_exc=RuntimeError( "extractor blew up" ) )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "weather", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "extract_error"


# ────────────────────────────────────────────────────────────── branch 3 — needs_input

def test_needs_input_interactive_parks_and_returns_first_question( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router    = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ],
                              fallback_questions={ "location": "Which city?" } )
    expeditor = FakeExpeditor( extraction=extraction )
    pending   = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )
    r = f.run( "what's the weather", **_CTX, interactive=True )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "parked"
    assert r[ "answer" ] == "Which city?"
    assert r[ "pending_id" ] == "pend-1"
    assert r[ "args_missing" ] == [ "location" ]
    assert len( pending.put_calls ) == 1


def test_needs_input_non_interactive_does_not_park( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ], fallback_questions={} )
    expeditor  = FakeExpeditor( extraction=extraction )
    pending    = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )
    r = f.run( "what's the weather", **_CTX, interactive=False )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "needs_input"
    assert r[ "pending_id" ] is None
    # fallback_questions empty → the synthesized default question is used.
    assert r[ "answer" ] == "What location would you like?"
    assert pending.put_calls == []


def test_non_interactive_spawns_no_background_thread( tmp_path, notifier, monkeypatch ):
    """
    The OTHER half of the never-blocks guarantee (plan DoD 3).

    Its sibling above pins "PendingRequests stays empty". The plan asks for two
    things, and this is the second: "and no background thread spawns". They are
    different failures — a flow that parks anyway returns a clean-looking 200
    while LEAKING a thread, which the eval cannot see because the response body
    looks identical.

    Today this passes because nothing in v2 spawns a thread at all. That is
    exactly why it is worth writing now rather than later: the resume path is
    still unbuilt, so the moment it lands this assertion is already standing
    guard. A guarantee nobody pinned while it was free stops holding silently.
    """
    import threading

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ], fallback_questions={} )
    expeditor  = FakeExpeditor( extraction=extraction )
    pending    = FakePending()
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), pending, notifier )

    before = { t.ident for t in threading.enumerate() }
    r      = f.run( "what's the weather", **_CTX, interactive=False )
    after  = { t.ident for t in threading.enumerate() }

    assert r[ "status" ] == "needs_input"
    assert after == before, (
        "non-interactive run spawned a background thread — the never-blocks "
        f"guarantee is broken. new thread ids: {after - before}"
    )


# ────────────────────────────────────────────────────────────── branch — args_complete

def test_args_complete_runs_agent_and_writes_back( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=True ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={ "location": "Boston" }, missing=[] )
    expeditor  = FakeExpeditor( extraction=extraction )
    cache      = FakeCache( write_back_id="snap-999" )
    exe        = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f = _make_flow( tmp_path, cache, router, expeditor, exe, FakePending(), notifier,
                    writeback_enabled=True )
    r = f.run( "weather in Chicago", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "args_complete"
    assert r[ "snapshot_id" ] == "snap-999"
    assert r[ "wrote_snapshot" ] is True
    assert len( cache.snapshot_calls ) == 1
    assert cache.write_back_calls[ 0 ][ 1 ] is True   # writeback_enabled forwarded


def test_agent_failure_degrades_to_receptionist( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    outcomes = [ _outcome( status="failed", error="agent boom" ), _outcome( status="done" ) ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    exe = _SeqExecutor()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "agent_error"


# ────────────────────────────────────────────────────────────── write-back seam

def test_no_write_back_when_agent_not_snapshotable( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=False ) )
    cache = FakeCache()
    f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier, writeback_enabled=True )
    r = f.run( "do a thing", **_CTX )
    assert r[ "path" ] == "agent"
    assert r[ "snapshot_id" ] is None
    assert r[ "wrote_snapshot" ] is False
    assert cache.snapshot_calls == []


def test_write_back_returning_none_marks_no_snapshot( tmp_path, notifier, monkeypatch ):
    # snapshotable+done, but write_back returns None (flag off inside the cache) →
    # snapshot_from_result IS called, but no t_writeback mark and wrote_snapshot False.
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    cache = FakeCache( write_back_id=None )
    f = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier, writeback_enabled=True )
    r = f.run( "do a thing", **_CTX )
    assert r[ "snapshot_id" ] is None
    assert r[ "wrote_snapshot" ] is False
    assert len( cache.snapshot_calls ) == 1


# ────────────────────────────────────────────────────────────── _speak forks

def test_speak_off_dispatches_no_notification( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=() ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(),
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX, speak=False )
    assert notifier.requests == []
    assert r[ "spoke" ] is False


def test_speak_on_with_answer_dispatches_notification( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=() ) )
    exe = FakeExecutor( _outcome( status="done", answer="hello", answer_raw="hello" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX, speak=True )
    assert len( notifier.requests ) == 1
    assert r[ "spoke" ] is True


def test_speak_on_but_empty_message_dispatches_nothing( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=() ) )
    exe = FakeExecutor( _outcome( status="done", answer=None, answer_raw=None ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "do a thing", **_CTX, speak=True )
    assert notifier.requests == []
    assert r[ "spoke" ] is False


# ────────────────────────────────────────────────────────────── _compose_question forks

def test_compose_question_appends_missing_skips_present_and_empty( tmp_path, notifier, monkeypatch ):
    captured = {}

    def _spec_capturing( command ):
        return FakeSpec( required_args=( "a", ), snapshotable=False )

    monkeypatch.setattr( flow_mod, "resolve", _spec_capturing )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={ "empty": "", "present": "already", "new": "Boston" }, missing=[] )
    expeditor  = FakeExpeditor( extraction=extraction )

    class _CapturingAgent( FakeAgent ):
        def __init__( self, **kwargs ):
            super().__init__( **kwargs )
            captured[ "question" ] = kwargs[ "question" ]

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "a", ), factory=_CapturingAgent,
                                                   snapshotable=False ) )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(),
                    FakePending(), notifier )
    f.run( "weather in already", **_CTX )
    q = captured[ "question" ]
    assert "Boston" in q            # truthy + absent → appended
    assert q.lower().count( "already" ) == 1  # present already → not re-appended
    assert q.count( "" ) >= 0       # empty value → skipped (no crash)


# ────────────────────────────────────────────────────────────── _arg_spec_for forks

def test_arg_spec_for_synthesizes_weather_when_not_in_table( tmp_path, notifier, monkeypatch ):
    # weather is NOT in JOB_ARG_CONTRACTS → the call-site ArgSpec is synthesized (R-B3).
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router  = FakeRouter( command="agent router go to weather" )
    spec = AskFlow( FakeCache(), router, FakeExpeditor(), FakeExecutor(), FakePending(),
                    notifier=notifier, trace_dir=str( tmp_path ) )._arg_spec_for(
                        "agent router go to weather", ( "location", ) )
    assert spec.required_user_args == [ "location" ]
    assert spec.cli_module is None
    assert "location" in spec.fallback_questions


def test_arg_spec_for_uses_table_entry_when_present( tmp_path, notifier, monkeypatch ):
    entry = {
        "arg_mapping"        : {},
        "system_provided"    : [],
        "required_user_args" : [ "foo" ],
        "fallback_questions" : { "foo": "Which foo?" },
    }
    monkeypatch.setattr( flow_mod, "JOB_ARG_CONTRACTS", { "agent router go to foo": entry } )
    f = AskFlow( FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), FakePending(),
                 notifier=notifier, trace_dir=str( tmp_path ) )
    spec = f._arg_spec_for( "agent router go to foo", ( "foo", ) )
    assert spec.required_user_args == [ "foo" ]
    assert spec.fallback_questions == { "foo": "Which foo?" }


# ────────────────────────────────────────────────────────────── the second turn — resume (DoD 4)
#
# These use the REAL PendingRequests, not a fake, on purpose: the plan's finding
# (§ reachability) was that the parked-request lifecycle was 100% covered and 0%
# reachable — put/get/set_status had no caller outside their own tests. Driving
# resume through the real store is the reachability assertion: it proves the flow
# is the caller that closes the loop. Still hermetic (in-process dict), :7999-safe.

def _park( pending, *, command="agent router go to weather", question="what's the weather",
           final_args=None, missing=( "location", ), fallback_questions=None ):
    """Park a real entry and return (pending_id, extraction) (mirrors flow.py:210's put)."""
    extraction = _extraction(
        final_args=final_args if final_args is not None else {},
        missing=missing,
        fallback_questions=fallback_questions if fallback_questions is not None else { "location": "Which city?" },
    )
    pid = pending.put( extraction=extraction, user_email="u@x.com", session_id="s1",
                       user_id="u1", command=command, question=question )
    return pid, extraction


def test_resume_completes_when_answer_fills_last_arg( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending      = PendingRequests()
    pid, _       = _park( pending )
    exe          = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f            = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "path" ] == "agent"
    assert r[ "route_reason" ] == "resumed"
    assert r[ "status" ] == "done"
    assert r[ "answer" ] == "sunny"
    # the executor saw the resumed arg folded into the composed question (R-B4)
    assert "Boston" in exe.works[ 0 ].job.kwargs[ "question" ]
    # the AI-observable seam advanced the real entry pending -> running -> done
    assert pending.get( pid ).status == "done"
    assert pending.get( pid ).answer == "sunny"


def test_resume_reasks_when_more_args_remain( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", "date" ) ) )
    pending  = PendingRequests()
    pid, _   = _park( pending, missing=[ "location", "date" ],
                      fallback_questions={ "location": "Which city?", "date": "Which day?" } )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "path" ] == "needs_input"
    assert r[ "status" ] == "parked"
    assert r[ "answer" ] == "Which day?"          # the NEXT question
    assert r[ "pending_id" ] == pid               # same id — the interview continues
    assert r[ "args_missing" ] == [ "date" ]
    # still parked, still pending — not advanced to running
    assert pending.get( pid ).status == "pending"


def test_resume_missing_pending_id_refuses_loudly( tmp_path, notifier ):
    pending = PendingRequests()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id="does-not-exist", answer="Boston", websocket_id="ws1" )
    assert r[ "status" ] == "expired"
    assert r[ "route_reason" ] == "pending_expired"
    assert r[ "path" ] == "needs_input"
    assert r[ "answer" ] is None                  # nothing rebuilt — a refusal, not a 500


def test_resume_expired_entry_refuses( tmp_path, notifier ):
    # a zero-TTL store expires the entry the instant it is read back.
    clock   = [ 0 ]
    pending = PendingRequests( ttl_seconds=0.0, clock=lambda: clock[ 0 ] )
    pid, _  = _park( pending )
    clock[ 0 ] = 1                                # advance past the (zero) TTL
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "status" ] == "expired"
    assert r[ "route_reason" ] == "pending_expired"


def test_second_resume_of_one_conversation_is_refused_as_already_resumed( tmp_path, notifier, monkeypatch ):
    """
    A second resume that loses the claim is refused, and says WHY in its own words.

    The first resume runs the agent and drives the entry to done; the second finds
    it no longer "pending" and must not run the agent again. Before claim(), the
    liveness read and the "running" write were two separate lock acquisitions with
    the agent run between them, so a second caller could pass the check and run a
    duplicate agent on the same conversation — unreachable while the handler was on
    the event loop, reachable the moment it moved to a worker thread.

    RED ON REVERT: put `self.pending.set_status( pending_id, "running" )` back in
    place of the claim() guard and the second resume runs the agent again.
    """
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )

    first = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert first[ "status" ] == "done"
    assert len( exe.works ) == 1

    second = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert second[ "route_reason" ] == "already_resumed"
    assert second[ "path" ] == "needs_input"
    assert second[ "answer" ] is None
    assert len( exe.works ) == 1, "the losing resume ran the agent a second time on one conversation"


def test_second_resume_never_raises_indexerror( tmp_path, notifier, monkeypatch ):
    """
    The 500 this route used to return, pinned by its exception type.

    At HEAD a second resume of a completed conversation reached
    `extraction.missing[ 0 ]` (flow.py:163) on a list the FIRST resume had already
    emptied, and raised IndexError — a 500 out of the one path whose docstring
    promises "never a 500". Nothing checked whether the conversation had already
    been answered. It needed no concurrency: the entry lives in the store until its
    TTL, so a retry or a double-clicked answer reached it on the single event loop.

    The sibling tests assert the REFUSAL; this one asserts the ABSENCE OF THE
    CRASH. They are not the same claim — a future edit could return a well-formed
    refusal on one branch and still raise on another, and only this test would say
    so.

    RED ON REVERT: remove the `entry.status != "pending"` early refusal and this
    raises IndexError instead of failing an assertion.
    """
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )

    try:
        second = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    except IndexError as e:
        raise AssertionError(
            f"second resume raised IndexError ({e}) — the 500 is back; the route's "
            f"contract says it degrades to a needs_input refusal, never a 500."
        )
    assert second[ "status" ] == "expired"
    assert second[ "path" ]   == "needs_input"


def test_a_second_resume_cannot_enter_the_interview_while_one_is_inside_it( tmp_path, notifier, monkeypatch ):
    """
    Two resumes must never both be inside the extraction mutation.

    María found this (row b28be422) and my first attempt to pin it FAILED TO
    DISCRIMINATE: racing two whole resumes, guarded and unguarded gave identical
    results in 30 runs each, because the critical section is a few statements wide
    and the threads almost never interleave inside it. I nearly reported the race
    as unobservable on that evidence.

    Holding one resume INSIDE the section makes it deterministic. `final_args` is a
    dict subclass whose first write parks until released, so the second resume
    arrives while the first is provably mid-mutation. Measured both ways:

        guarded   -> second refused "already_resumed"; writes = [ location ]
        unguarded -> second proceeds;                  writes = [ location, location ]

    Two writes to the SAME slot is one user's answer silently overwritten by
    another's. Not reachable while resume ran on the event loop; reachable the
    moment it moved to a worker thread — this commit.

    RED ON REVERT: drop the claim()/release_turn() pair from flow.resume and the
    second resume writes "location" a second time.
    """
    import threading

    inside  = threading.Event()
    hold    = threading.Event()
    writes  = []

    class ParkingArgs( dict ):
        """final_args whose FIRST write parks inside the critical section."""
        def __setitem__( self, key, value ):
            writes.append( key )
            if len( writes ) == 1:
                inside.set()
                hold.wait( timeout=5 )
            super().__setitem__( key, value )

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", "date" ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    entry   = pending.get( pid )
    entry.extraction.missing    = [ "location", "date" ]
    entry.extraction.final_args = ParkingArgs()

    exe = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="raw" ) )
    f   = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )

    first = threading.Thread(
        target=lambda: f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" ) )
    first.start()
    assert inside.wait( timeout=5 ), "the first resume never entered the mutation — nothing was tested"

    second = f.resume( pending_id=pid, answer="Tuesday", websocket_id="ws1" )

    hold.set()
    first.join( timeout=5 )

    assert second[ "route_reason" ] == "already_resumed", second
    assert writes == [ "location" ], (
        f"both resumes wrote into the interview: {writes} — the second overwrote the "
        f"first caller's answer in the same slot."
    )


def test_the_flow_never_routes_through_the_expeditors_stateful_half( tmp_path, notifier, monkeypatch ):
    """
    TRIPWIRE: the shared expeditor must stay stateless across a v2 request.

    `RuntimeArgumentExpeditor` keeps per-call state on the instance —
    `_job_id`, `_bearer_token`, `_last_expedite_reason` (expeditor.py:309-311) —
    and the flow holds ONE expeditor. Those writes live in `expedite()` and
    `collect()`; `extract()`, which is all the flow calls (flow.py:121), writes
    none of them. Verified by walking the call graph, not by grep: `extract()`
    touches none of the three even transitively.

    So there is no bearer-token crossover on the v2 path today. But the handlers
    now run OFF the event loop, so two v2 requests can be in the flow at once —
    and if anyone ever routes the flow through the stateful half, one user's
    bearer token becomes readable by another's request. That is a security-shaped
    failure that no existing test would notice, because every functional
    assertion would still pass.

    This test is the tripwire for that day. It does not test today's behaviour so
    much as pin the boundary that makes today's behaviour safe.

    It compares the expeditor's ENTIRE __dict__ before and after, rather than a
    list of the attribute names known today. A hand-list would pass the day
    someone adds a fifth per-call attribute — exactly the change worth catching.

    RED ON REVERT — the exact mutation, which was run: in `flow.py`, replace
    `self.expeditor.extract( command, raw_args, question, arg_spec )` with
    `self.expeditor.expedite( command, raw_args, ctx[ 1 ], ctx[ 2 ], ctx[ 0 ], question,
    job_id="job-1", bearer_token="tok-1" )`. `expedite` stamps `_job_id`,
    `_bearer_token` and `_last_expedite_reason` on the instance before it does
    anything else (`expeditor.py:309-311`), so the sentinels come back changed.

    ⚠️ TWO THINGS MAKE THAT MUTATION ACTUALLY BITE, and without either one this
    test passes under its own named revert:
      1. The stub below carries `expedite()` and `collect()`, not `extract()`
         alone. A stub missing the method answers `AttributeError`, which
         `flow.py`'s `except Exception` folds into the receptionist path — the
         real instance is never touched and the comparison stays green.
      2. The real instance is wired far enough for `extract()` to RUN. Built by
         `__new__` alone it raises at `self.debug` (`expeditor.py:367`) before
         reaching a line that could write anything, so the delegation proved
         nothing. It gets the five wiring attributes `extract()` reads, with a
         fake LLM client and a fake template read: no config, no network, and
         still the real code path.
    """
    import cosa.agents.runtime_argument_expeditor.expeditor as expeditor_mod
    from cosa.agents.runtime_argument_expeditor.expeditor import RuntimeArgumentExpeditor

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )

    class FakeLlmClient:
        def run( self, prompt ):
            return ( "<response><all_required_met>true</all_required_met>"
                     "<args_present>location=Boston</args_present>"
                     "<args_missing></args_missing></response>" )

    # Fake the template read rather than depend on a real prompt file's brace
    # content — the LLM call and the file read are the only two things standing
    # between this test and the real extract() body.
    monkeypatch.setattr(
        expeditor_mod.cu, "get_file_as_string",
        lambda path: "SYS {system_args} HELP {help_text} Q {voice_command} "
                     "EXTRACTED {extracted_args} REQUIRED {required_args}"
    )

    real = RuntimeArgumentExpeditor.__new__( RuntimeArgumentExpeditor )   # no __init__: no config, no network
    real.debug                = False
    real.verbose              = False
    real.prompt_template_path = "/unused — the read above is faked"
    real.llm_spec_key         = "fake-llm"
    real.llm_factory          = types.SimpleNamespace(
        get_client=lambda key, debug=False, verbose=False: FakeLlmClient()
    )

    # Sentinel the WHOLE instance state, not a hand-list of the names I happen to
    # know about. A list of four would pass the day someone adds a fifth per-call
    # attribute — which is precisely the change this tripwire needs to catch.
    for name in ( "_job_id", "_bearer_token", "_last_expedite_reason",
                  "_last_notification_status" ):
        setattr( real, name, f"SENTINEL-{name}" )
    before = dict( real.__dict__ )

    class DelegatingExpeditor:
        """Delegates EVERY method the flow could reach to the real class, so a
        change of which method the flow calls is felt on the real instance.

        A stub carrying extract() alone was not enough, and made this test
        vacuous under its own named mutation: point the flow at expedite() and
        the stub answers AttributeError, which flow.py:123's `except Exception`
        turns into the receptionist path — the real instance is never touched
        and the sentinel comparison below passes while the boundary it exists to
        guard is gone. Each name is appended AFTER the real call returns, so
        `delegated` records methods that actually RAN, not merely ones that were
        entered.
        """

        def __init__( self ):
            self.delegated = []

        def extract( self, command, raw_args, question, spec ):
            RuntimeArgumentExpeditor.extract( real, command, raw_args, question, spec )
            self.delegated.append( "extract" )
            return _extraction( final_args={ "location": "Boston" }, missing=[] )

        def expedite( self, command, raw_args, user_email, session_id, user_id, original_question,
                      job_id=None, bearer_token=None ):
            RuntimeArgumentExpeditor.expedite( real, command, raw_args, user_email, session_id,
                                               user_id, original_question,
                                               job_id=job_id, bearer_token=bearer_token )
            self.delegated.append( "expedite" )
            return _extraction( final_args={ "location": "Boston" }, missing=[] )

        def collect( self, extraction, command, original_question, spec,
                     user_email, session_id, user_id ):
            RuntimeArgumentExpeditor.collect( real, extraction, command, original_question, spec,
                                              user_email, session_id, user_id )
            self.delegated.append( "collect" )
            return _extraction( final_args={ "location": "Boston" }, missing=[] )

    stub = DelegatingExpeditor()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), stub,
                    FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="raw" ) ),
                    PendingRequests(), notifier )
    f.run( question="weather in Boston", user_id="u1", user_email="u@x", session_id="s1",
           websocket_id="ws1", speak=False, interactive=False )

    # Anti-vacuity control. Without this, a request that reached NO expeditor
    # method at all — or one whose real implementation threw before writing
    # anything — would leave the sentinels untouched and read as a pass.
    assert stub.delegated == [ "extract" ], (
        f"the flow ran {stub.delegated} to completion on the real expeditor. Empty means "
        f"no real method ran at all and the sentinel comparison below is vacuous; anything "
        f"other than ['extract'] means the flow has reached the stateful half"
    )

    after   = dict( real.__dict__ )
    changed = { k for k in set( before ) | set( after ) if before.get( k, object() ) != after.get( k, object() ) }
    assert not changed, (
        f"a v2 request wrote {sorted( changed )} on the SHARED expeditor. Both handlers "
        f"now run off the event loop, so two concurrent requests would read each other's "
        f"values — for _bearer_token that is one user's credential reaching another."
    )


def test_already_resumed_is_distinguishable_from_pending_expired( tmp_path, notifier, monkeypatch ):
    """
    The two refusals must not share a route_reason.

    They are the same SHAPE — status "expired", path needs_input, no answer — so a
    test asserting only the shape would pass with one reason serving both. A log
    that cannot tell a lost race from a timed-out conversation sends the reader
    looking at TTLs for a concurrency bug.

    RED ON REVERT: give the claim refusal route_reason="pending_expired" and this
    fails while every shape assertion above still passes.
    """
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )

    lost_race = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    dead_id   = f.resume( pending_id="does-not-exist", answer="Boston", websocket_id="ws1" )

    assert lost_race[ "route_reason" ] == "already_resumed"
    assert dead_id[ "route_reason" ]   == "pending_expired"
    assert lost_race[ "route_reason" ] != dead_id[ "route_reason" ]


def test_resume_unknown_command_degrades_and_marks_failed( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve", lambda command: None )   # command no longer resolvable
    pending = PendingRequests()
    pid, _  = _park( pending, command="agent router go to ghost" )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "path" ] == "receptionist"
    assert r[ "route_reason" ] == "unknown_command"
    assert pending.get( pid ).status == "failed"


def test_resume_spawns_no_background_thread( tmp_path, notifier, monkeypatch ):
    """With resume synchronous, 'no background thread spawns' is a PERMANENT design
    invariant — the sibling guard on run() pins the park side; this pins the resume
    side, so the guarantee holds across the whole two-turn mechanism."""
    import threading

    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )

    before = { t.ident for t in threading.enumerate() }
    f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    after  = { t.ident for t in threading.enumerate() }
    assert after == before, f"resume spawned a background thread: {after - before}"


# ────────────────────────────────────────────────────────────── t_complete span (row 76a3c32d)
#
# t_complete is the closing bookend of the completion-symmetric span (t_recv ->
# t_complete), mirroring v1's RUNNING->COMPLETED for the paired harness report
# note. It is stamped once at the _emit chokepoint, so EVERY terminal exit carries
# it. Each test below would go red if the mark were removed (KeyError → the `in`
# assertion fails) — RED-provable per the 100% mandate. perf_counter_ns is
# monotonic, so t_complete >= t_first_useful >= t_recv holds without an injected clock.

def test_agent_path_stamps_t_complete_after_first_useful( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    exe = FakeExecutor( _outcome( status="done", answer="42", answer_raw="42" ) )
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe,
                    FakePending(), notifier )
    r = f.run( "what time is it", **_CTX )
    timings = r[ "timings_ms" ]
    assert "t_complete" in timings                              # the completion bookend exists
    assert timings[ "t_complete" ] >= timings[ "t_first_useful" ]  # after the useful answer
    assert timings[ "t_complete" ] >= timings[ "t_recv" ]         # after the anchor (0.0)


def test_replay_path_stamps_t_complete( tmp_path, notifier ):
    snap  = types.SimpleNamespace( routing_command="agent router go to math" )
    cache = FakeCache( lookup_result=_lookup( is_replay_hit=True, snapshot=snap ) )
    exe   = FakeExecutor( _outcome( status="done", answer="4", answer_raw="4" ) )
    f     = _make_flow( tmp_path, cache, FakeRouter(), FakeExpeditor(), exe, FakePending(), notifier )
    r = f.run( "what is 2+2", **_CTX )
    assert "t_complete" in r[ "timings_ms" ]
    assert r[ "timings_ms" ][ "t_complete" ] >= r[ "timings_ms" ][ "t_first_useful" ]


def test_needs_input_path_stamps_t_complete( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ) ) )
    router     = FakeRouter( command="agent router go to weather" )
    extraction = _extraction( final_args={}, missing=[ "location" ],
                              fallback_questions={ "location": "Which city?" } )
    expeditor  = FakeExpeditor( extraction=extraction )
    f = _make_flow( tmp_path, FakeCache(), router, expeditor, FakeExecutor(), FakePending(), notifier )
    r = f.run( "what's the weather", **_CTX, interactive=True )
    timings = r[ "timings_ms" ]
    assert r[ "path" ] == "needs_input"
    assert "t_complete" in timings                              # needs_input turn is bookended too
    assert timings[ "t_complete" ] >= timings[ "t_first_useful" ]


def test_resume_complete_stamps_t_complete( tmp_path, notifier, monkeypatch ):
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=( "location", ), snapshotable=False ) )
    pending = PendingRequests()
    pid, _  = _park( pending )
    exe     = FakeExecutor( _outcome( status="done", answer="sunny", answer_raw="sunny raw" ) )
    f       = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), exe, pending, notifier )
    r = f.resume( pending_id=pid, answer="Boston", websocket_id="ws1" )
    assert r[ "status" ] == "done"
    assert "t_complete" in r[ "timings_ms" ]


def test_resume_expired_stamps_t_complete( tmp_path, notifier ):
    # even the refusal path is bookended: t_recv + t_complete, no t_first_useful.
    pending = PendingRequests()
    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), FakeExecutor(), pending, notifier )
    r = f.resume( pending_id="does-not-exist", answer="Boston", websocket_id="ws1" )
    timings = r[ "timings_ms" ]
    assert r[ "status" ] == "expired"
    assert "t_complete" in timings
    assert timings[ "t_complete" ] >= timings[ "t_recv" ]


# ──────────────────────────────────── the degrade must not hide the fault it was reached by
#
# Live receipt, :8000 run ts-333d04de (2026-08-19): the v2 resume of a weather
# question degraded to the receptionist and the emitted error was the
# RECEPTIONIST's. The weather agent's own failure — the reason the degrade
# happened at all — was dropped on the floor, so the run said why the fallback
# died and nothing about why the real agent did. These three tests pin the three
# shapes of the composed error.

def _degrade_flow( tmp_path, notifier, monkeypatch, primary_error, fallback_outcome ):
    """Run a flow whose primary agent fails and whose receptionist returns fallback_outcome."""
    monkeypatch.setattr( flow_mod, "resolve",
                         lambda command: FakeSpec( required_args=(), snapshotable=True ) )
    outcomes = [ _outcome( status="failed", error=primary_error ), fallback_outcome ]

    class _SeqExecutor( FakeExecutor ):
        def submit( self, work, trace ):
            self.works.append( work )
            return outcomes.pop( 0 )

    f = _make_flow( tmp_path, FakeCache(), FakeRouter(), FakeExpeditor(), _SeqExecutor(),
                    FakePending(), notifier )
    return f.run( "do a thing", **_CTX )


def test_degrade_keeps_the_primary_agent_error_when_receptionist_succeeds( tmp_path, notifier, monkeypatch ):
    """The cause survives even when the fallback answers fine — otherwise error is None."""
    r = _degrade_flow( tmp_path, notifier, monkeypatch,
                       primary_error="maximum context length is 8192 tokens",
                       fallback_outcome=_outcome( status="done", error=None ) )
    assert r[ "route_reason" ] == "agent_error"
    assert r[ "error" ] == "primary agent failed: maximum context length is 8192 tokens"


def test_degrade_reports_both_errors_when_the_receptionist_also_fails( tmp_path, notifier, monkeypatch ):
    """Tonight's live shape: both halves died and both must be readable."""
    r = _degrade_flow( tmp_path, notifier, monkeypatch,
                       primary_error="agent boom",
                       fallback_outcome=_outcome( status="failed", error="receptionist boom" ) )
    assert r[ "error" ] == "primary agent failed: agent boom | receptionist: receptionist boom"


def test_degrade_with_no_primary_error_still_reports_the_fallback_error( tmp_path, notifier, monkeypatch ):
    """Negative control — a primary that failed WITHOUT an error message must not
    invent a 'primary agent failed: None' prefix, and the fallback's error must
    still reach the caller unchanged."""
    r = _degrade_flow( tmp_path, notifier, monkeypatch,
                       primary_error=None,
                       fallback_outcome=_outcome( status="failed", error="receptionist boom" ) )
    assert r[ "error" ] == "receptionist boom"
